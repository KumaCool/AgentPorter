from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import yaml

from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import COMPONENT_IDS, INSTALL_COMPONENT_IDS, PRODUCT_ID
from agentporter.transaction import InstallTransactionStatus
from agentporter.workflow import WorkflowOutcome, WorkflowStatus

REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})
INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")


def _manifest(tmp_path: Path, *, providers: bool = True) -> Path:
    source = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if providers:
        for worker in data["workers"].values():
            worker["provider"] = "static-public-provider"
    path = tmp_path / "workers.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _detection(tmp_path: Path) -> HermesDetection:
    home = tmp_path / "hermes-home"
    return HermesDetection(
        executable=tmp_path / "bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=(),
    )


def _installed_marker(
    detection: HermesDetection,
    name: str,
    component_id: str,
    *,
    installation_id: UUID = INSTALLATION_ID,
) -> Path:
    profile = detection.profiles_root / name
    profile.mkdir(parents=True, exist_ok=True)
    marker = profile / "agentporter-profile.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_id": PRODUCT_ID,
                "component_id": component_id,
                "installation_id": str(installation_id),
                "distribution_version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    (profile / "config.yaml").write_text(f"sentinel: {name}\n", encoding="utf-8")
    return profile


def _answer(output: StringIO):
    def answer(_: str) -> str:
        fingerprint = output.getvalue().split("Plan fingerprint: ", 1)[1].splitlines()[0]
        return f"INSTALL AGENTPORTER {fingerprint[:8]}"

    return answer


def test_confirmed_application_composes_fresh_native_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentporter.application as application

    events: list[object] = []
    detections: list[HermesDetection] = []
    sealed_env = {"HOME": str(tmp_path), "PATH": "/safe/bin"}

    def detector(*, env: object) -> HermesDetection:
        assert env is sealed_env
        detection = _detection(tmp_path)
        detections.append(detection)
        events.append("detect")
        return detection

    executor = object()

    def executor_factory() -> object:
        events.append("executor")
        return executor

    class Adapter:
        def __init__(
            self, actual_executor: object, env: object, detection: HermesDetection
        ) -> None:
            assert actual_executor is executor
            assert env is sealed_env
            assert detection is detections[-1]
            self._executor = actual_executor
            events.append("adapter")

        def enumerate_profiles(self) -> tuple[object, ...]:
            return ()

        def set_description(self, *args: object, **kwargs: object) -> object:
            raise AssertionError

        def read_distribution_info(self, *args: object, **kwargs: object) -> object:
            raise AssertionError

        def read_description(self, *args: object, **kwargs: object) -> object:
            raise AssertionError

    transaction = SimpleNamespace(status=InstallTransactionStatus.INSTALLED)

    def execute(plan: object, **kwargs: object) -> object:
        events.append("transaction")
        assert kwargs == {
            "executor": executor,
            "env": sealed_env,
            "enumerate_profiles": adapter.enumerate_profiles,
            "set_description": adapter.set_description,
            "read_distribution_info": adapter.read_distribution_info,
            "read_description": adapter.read_description,
            "current_detection": current_detection,
        }
        provider = kwargs["current_detection"]
        assert callable(provider)
        assert provider() is not provider()
        return transaction

    adapter: Adapter
    current_detection: object

    def adapter_factory(
        actual_executor: object, env: object, detection: HermesDetection
    ) -> Adapter:
        nonlocal adapter
        adapter = Adapter(actual_executor, env, detection)
        return adapter

    def execute_capture(plan: object, **kwargs: object) -> object:
        nonlocal current_detection
        current_detection = kwargs["current_detection"]
        return execute(plan, **kwargs)

    monkeypatch.setattr(application, "execute_install_transaction", execute_capture)
    output = StringIO()
    result = application.run_installer(
        _manifest(tmp_path),
        tmp_path / "staging",
        sealed_env,
        input_fn=_answer(output),
        output=output,
        executor_factory=executor_factory,
        detector=detector,
        adapter_factory=adapter_factory,
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert result.workflow.status is WorkflowStatus.CONFIRMED
    assert result.transaction is transaction
    assert events == [
        "detect",
        "detect",
        "detect",
        "detect",
        "executor",
        "adapter",
        "transaction",
        "detect",
        "detect",
    ]
    assert len(detections) == 6


def test_formal_installer_discovers_renamed_legacy_and_stages_only_orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentporter.application as application

    detection = _detection(tmp_path)
    legacy = [
        _installed_marker(detection, name, component)
        for name, component in zip(
            ("renamed-luna", "renamed-codex"), COMPONENT_IDS.values(), strict=True
        )
    ]
    before = {
        path: (
            (path / "agentporter-profile.json").read_bytes(),
            (path / "config.yaml").read_bytes(),
            (path / "agentporter-profile.json").stat().st_mtime_ns,
            (path / "config.yaml").stat().st_mtime_ns,
        )
        for path in legacy
    }
    captured: list[object] = []
    transaction = SimpleNamespace(status=InstallTransactionStatus.INSTALLED)
    monkeypatch.setattr(
        application,
        "execute_install_transaction",
        lambda plan, **kwargs: captured.append(plan) or transaction,
    )
    adapter = SimpleNamespace(
        enumerate_profiles=lambda: (),
        set_description=object(),
        read_distribution_info=object(),
        read_description=object(),
    )
    output = StringIO()

    result = application.run_installer(
        _manifest(tmp_path),
        tmp_path / "staging",
        {},
        input_fn=_answer(output),
        output=output,
        detector=lambda **kwargs: detection,
        executor_factory=lambda: object(),  # type: ignore[arg-type]
        adapter_factory=lambda *args: adapter,  # type: ignore[arg-type]
        installation_id_factory=lambda: pytest.fail("legacy upgrade must retain installation id"),
    )

    assert result.workflow.status is WorkflowStatus.CONFIRMED
    plan = captured[0]
    assert plan.installation_id == str(INSTALLATION_ID)  # type: ignore[attr-defined]
    assert [worker.component_id for worker in plan.workers] == [  # type: ignore[attr-defined]
        INSTALL_COMPONENT_IDS["agentporter_orchestrator"]
    ]
    assert before == {
        path: (
            (path / "agentporter-profile.json").read_bytes(),
            (path / "config.yaml").read_bytes(),
            (path / "agentporter-profile.json").stat().st_mtime_ns,
            (path / "config.yaml").stat().st_mtime_ns,
        )
        for path in legacy
    }


def test_formal_installer_rejects_complete_current_installation_without_writes(
    tmp_path: Path,
) -> None:
    import agentporter.application as application

    detection = _detection(tmp_path)
    for name, component in zip(
        ("renamed-luna", "renamed-codex", "renamed-orchestrator"),
        INSTALL_COMPONENT_IDS.values(),
        strict=True,
    ):
        _installed_marker(detection, name, component)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in detection.profiles_root.rglob("*")
        if path.is_file()
    }

    result = application.run_installer(
        _manifest(tmp_path),
        tmp_path / "staging",
        {},
        output=StringIO(),
        detector=lambda **kwargs: detection,
        executor_factory=lambda: pytest.fail("already installed must not execute"),
        installation_id_factory=lambda: pytest.fail("already installed must not create an id"),
        existing_installation=None,
    )

    assert result.workflow.status is WorkflowStatus.REJECTED
    assert "already installed" in result.workflow.reason
    assert result.transaction is None
    assert not (tmp_path / "staging").exists()
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in detection.profiles_root.rglob("*")
        if path.is_file()
    }


def test_cancel_has_zero_adapter_or_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentporter.application as application

    detection_calls = 0

    def detector(*, env: object) -> HermesDetection:
        nonlocal detection_calls
        detection_calls += 1
        return _detection(tmp_path)

    monkeypatch.setattr(
        application,
        "execute_install_transaction",
        lambda *args, **kwargs: pytest.fail("cancel must not enter transaction"),
    )
    result = application.run_installer(
        _manifest(tmp_path),
        tmp_path / "staging",
        {},
        input_fn=lambda _: "no",
        output=StringIO(),
        detector=detector,
        executor_factory=lambda: pytest.fail("cancel must not create executor"),
        adapter_factory=lambda *args: pytest.fail("cancel must not create adapter"),
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert result.workflow.status is WorkflowStatus.CANCELLED
    assert result.transaction is None
    assert detection_calls == 2


def test_transaction_finishes_before_staging_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentporter.application as application

    events: list[str] = []
    output = StringIO()
    transaction = SimpleNamespace(status=InstallTransactionStatus.INSTALLED)

    class Adapter:
        enumerate_profiles = set_description = read_distribution_info = read_description = object()

    monkeypatch.setattr(
        application,
        "execute_install_transaction",
        lambda plan, **kwargs: events.append("transaction") or transaction,
    )
    original_cleanup = application.preflight_and_confirm

    def workflow(*args: object, **kwargs: object) -> WorkflowOutcome:
        outcome = original_cleanup(*args, **kwargs)
        events.append("cleanup-complete")
        return outcome

    monkeypatch.setattr(application, "preflight_and_confirm", workflow)
    result = application.run_installer(
        _manifest(tmp_path),
        tmp_path / "staging",
        {},
        input_fn=_answer(output),
        output=output,
        detector=lambda **kwargs: _detection(tmp_path),
        executor_factory=lambda: object(),  # type: ignore[arg-type]
        adapter_factory=lambda *args: Adapter(),  # type: ignore[arg-type]
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert result.transaction is transaction
    assert events == ["transaction", "cleanup-complete"]


def test_cleanup_failure_discards_transaction_from_typed_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentporter.application as application

    transaction = SimpleNamespace(status=InstallTransactionStatus.INSTALLED)
    monkeypatch.setattr(
        application,
        "preflight_and_confirm",
        lambda *args, **kwargs: (
            kwargs["continuation"](SimpleNamespace())
            or WorkflowOutcome(WorkflowStatus.CLEANUP_FAILED, "cleanup failed", False)
        ),
    )
    monkeypatch.setattr(application, "revalidate_install_plan", lambda plan, detection: True)
    monkeypatch.setattr(
        application, "execute_install_transaction", lambda *args, **kwargs: transaction
    )
    adapter = SimpleNamespace(
        enumerate_profiles=object(),
        set_description=object(),
        read_distribution_info=object(),
        read_description=object(),
    )

    result = application.run_installer(
        _manifest(tmp_path),
        tmp_path / "staging",
        {},
        detector=lambda **kwargs: _detection(tmp_path),
        executor_factory=lambda: object(),  # type: ignore[arg-type]
        adapter_factory=lambda *args: adapter,  # type: ignore[arg-type]
    )

    assert result.workflow.status is WorkflowStatus.CLEANUP_FAILED
    assert result.transaction is None


def test_transaction_baseexception_propagates_after_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentporter.application as application

    output = StringIO()
    original = KeyboardInterrupt("stop")
    staging: Path | None = None

    class Adapter:
        enumerate_profiles = set_description = read_distribution_info = read_description = object()

    def interrupt(plan: object, **kwargs: object) -> object:
        nonlocal staging
        staging = plan.staging_dir  # type: ignore[attr-defined]
        raise original

    monkeypatch.setattr(application, "execute_install_transaction", interrupt)
    with pytest.raises(KeyboardInterrupt) as raised:
        application.run_installer(
            _manifest(tmp_path),
            tmp_path / "staging",
            {},
            input_fn=_answer(output),
            output=output,
            detector=lambda **kwargs: _detection(tmp_path),
            executor_factory=lambda: object(),  # type: ignore[arg-type]
            adapter_factory=lambda *args: Adapter(),  # type: ignore[arg-type]
            installation_id_factory=lambda: INSTALLATION_ID,
        )

    assert raised.value is original
    assert staging is not None and not staging.exists()
