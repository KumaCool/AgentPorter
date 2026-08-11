from __future__ import annotations

import ast
import hashlib
import inspect
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Never
from uuid import UUID

import pytest
import yaml

from agentporter.hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from agentporter.planning import CleanupOutcome, InstallPlan, cleanup_staging, plan_installation
from agentporter.workflow import (
    WorkflowStatus,
    confirm_preflight_plan,
    preflight_and_confirm,
    render_plan_text,
    request_for_plan,
)

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


def _detection(
    tmp_path: Path, *, profile_entries: tuple[ProfileEntry, ...] = ()
) -> HermesDetection:
    home = tmp_path / "private-hermes-home"
    return HermesDetection(
        executable=tmp_path / "private-bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=profile_entries,
    )


def _plan(tmp_path: Path, *, providers: bool = True) -> InstallPlan:
    return plan_installation(
        _detection(tmp_path),
        _manifest(tmp_path, providers=providers),
        staging_parent=tmp_path / "private-staging-parent",
        installation_id_factory=lambda: INSTALLATION_ID,
    )


def _forbidden(*_args: object, **_kwargs: object) -> Never:
    pytest.fail("forbidden credential/model/Hermes-write boundary was called")


def _confirm(
    plan: InstallPlan,
    tmp_path: Path,
    *,
    answer: str = "no",
    continuation: object = _forbidden,
    output: StringIO | None = None,
    cleanup_fn: object = cleanup_staging,
):
    return confirm_preflight_plan(
        plan,
        current_detection_provider=lambda: _detection(tmp_path),
        continuation=continuation,  # type: ignore[arg-type]
        input_fn=lambda _: answer,
        output=output or StringIO(),
        cleanup_fn=cleanup_fn,  # type: ignore[arg-type]
    )


def test_render_plan_text_is_explicit_privacy_allowlist(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    private_description = "/home/private/manifest description with secret prose"
    unsafe_reason = "/tmp/private-staging/reason copied verbatim"
    worker = replace(plan.workers[0], description=private_description, reason=unsafe_reason)
    projected = replace(plan, workers=(worker, *plan.workers[1:]), reason=unsafe_reason)

    text = render_plan_text(projected)

    assert f"Hermes executable: {plan.hermes.executable}" in text
    assert f"Hermes home: {plan.hermes.home}" in text
    assert f"Hermes profiles root: {plan.hermes.profiles_root}" in text
    assert "Model: " in text and "Provider: static-public-provider" in text
    assert "Copied data: none" in text and "Model calls: false" in text
    assert private_description not in text
    assert unsafe_reason not in text
    assert str(plan.staging_dir) not in text
    assert "private-staging-parent" not in text
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_request_is_canonical_and_binds_artifact_seal(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    request = request_for_plan(plan)

    assert request is not None
    assert request.plan_text == render_plan_text(plan)
    assert request.fingerprint == plan.fingerprint
    assert request.phrase == f"INSTALL AGENTPORTER {plan.fingerprint[:8]}"
    assert plan.staging_dir is not None
    artifact = plan.staging_dir / plan.artifacts[0].relative_path
    artifact.write_bytes(artifact.read_bytes() + b"\n")
    assert request_for_plan(plan) is None
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_configuration_required_plan_is_installable_and_confirmable(tmp_path: Path) -> None:
    plan = _plan(tmp_path, providers=False)

    request = request_for_plan(plan)

    assert plan.installable is True
    assert request is not None
    assert "Run configuration remains required after installation" in request.plan_text
    assert "not selected" in request.plan_text
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


@pytest.mark.parametrize("answer", ["", "no"])
def test_cancel_cleans_staging_with_zero_continuation(tmp_path: Path, answer: str) -> None:
    plan = _plan(tmp_path)
    output = StringIO()

    outcome = _confirm(plan, tmp_path, answer=answer, output=output)

    assert outcome.status is WorkflowStatus.CANCELLED
    assert outcome.cleanup_verified
    assert output.getvalue().count(render_plan_text(plan)) == 1
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_exact_phrase_revalidates_then_continues_once_before_cleanup(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    continued: list[InstallPlan] = []

    def continuation(candidate: InstallPlan) -> None:
        assert candidate.staging_dir is not None and candidate.staging_dir.exists()
        continued.append(candidate)

    outcome = _confirm(
        plan,
        tmp_path,
        answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
        continuation=continuation,
    )

    assert outcome.status is WorkflowStatus.CONFIRMED
    assert outcome.cleanup_verified
    assert continued == [plan]
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_artifact_tamper_after_prompt_rejects_with_zero_continuation(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.staging_dir is not None

    def tamper(_: str) -> str:
        artifact = plan.staging_dir / plan.artifacts[0].relative_path
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
        return f"INSTALL AGENTPORTER {plan.fingerprint[:8]}"

    outcome = confirm_preflight_plan(
        plan,
        current_detection_provider=lambda: _detection(tmp_path),
        continuation=_forbidden,
        input_fn=tamper,
        output=StringIO(),
    )

    assert outcome.status is WorkflowStatus.REJECTED
    assert outcome.cleanup_verified


def test_target_change_after_prompt_rejects_with_zero_continuation(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    detections = iter(
        (
            _detection(tmp_path),
            _detection(
                tmp_path,
                profile_entries=(
                    ProfileEntry(
                        plan.workers[0].profile_name,
                        _detection(tmp_path).profiles_root / plan.workers[0].profile_name,
                        ProfileEntryKind.PROFILE,
                    ),
                ),
            ),
        )
    )

    outcome = confirm_preflight_plan(
        plan,
        current_detection_provider=lambda: next(detections),
        continuation=_forbidden,
        input_fn=lambda _: f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
        output=StringIO(),
    )

    assert outcome.status is WorkflowStatus.REJECTED
    assert outcome.cleanup_verified


def test_continuation_baseexception_cleans_then_propagates_original(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def interrupt(_: InstallPlan) -> Never:
        raise KeyboardInterrupt("stop")

    with pytest.raises(KeyboardInterrupt, match="stop"):
        _confirm(
            plan,
            tmp_path,
            answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
            continuation=interrupt,
        )
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_pending_baseexception_is_not_masked_by_cleanup_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def interrupt(_: InstallPlan) -> Never:
        raise KeyboardInterrupt("stop")

    def failed_outcome(_: InstallPlan) -> CleanupOutcome:
        return CleanupOutcome("failed", "sensitive cleanup detail")

    with pytest.raises(KeyboardInterrupt, match="stop") as raised:
        _confirm(
            plan,
            tmp_path,
            answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
            continuation=interrupt,
            cleanup_fn=failed_outcome,
        )
    notes = raised.value.__notes__
    assert any("CleanupOutcome" in note for note in notes)
    assert all("sensitive cleanup detail" not in note for note in notes)
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_pending_baseexception_records_cleanup_exception_type_without_sensitive_detail(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    def interrupt(_: InstallPlan) -> Never:
        raise KeyboardInterrupt("stop")

    def cleanup_error(_: InstallPlan) -> Never:
        raise RuntimeError("sensitive cleanup detail")

    with pytest.raises(KeyboardInterrupt, match="stop") as raised:
        _confirm(
            plan,
            tmp_path,
            answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
            continuation=interrupt,
            cleanup_fn=cleanup_error,
        )
    assert any("RuntimeError" in note for note in raised.value.__notes__)
    assert all("sensitive cleanup detail" not in note for note in raised.value.__notes__)
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


@pytest.mark.parametrize("cleanup_error", [KeyboardInterrupt("stop"), SystemExit(17)])
def test_cleanup_baseexception_without_pending_error_propagates_unchanged(
    tmp_path: Path, cleanup_error: BaseException
) -> None:
    plan = _plan(tmp_path)

    def interrupt_cleanup(_: InstallPlan) -> Never:
        raise cleanup_error

    with pytest.raises(type(cleanup_error)) as raised:
        _confirm(plan, tmp_path, cleanup_fn=interrupt_cleanup)
    assert raised.value is cleanup_error
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_cleanup_exception_without_pending_error_is_explicit_typed_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def failed_cleanup(_: InstallPlan) -> Never:
        raise RuntimeError("sensitive cleanup detail")

    outcome = _confirm(plan, tmp_path, cleanup_fn=failed_cleanup)

    assert outcome.status is WorkflowStatus.CLEANUP_FAILED
    assert "sensitive cleanup detail" not in outcome.reason
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


@pytest.mark.parametrize("status", ["refused", "failed"])
def test_cleanup_refused_or_failed_is_explicit_typed_failure(tmp_path: Path, status: str) -> None:
    plan = _plan(tmp_path)

    outcome = _confirm(
        plan,
        tmp_path,
        cleanup_fn=lambda _: CleanupOutcome(status, "private detail"),  # type: ignore[arg-type]
    )

    assert outcome.status is WorkflowStatus.CLEANUP_FAILED
    assert not outcome.cleanup_verified
    assert "private detail" not in outcome.reason
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        if path.is_symlink():
            digest.update(b"symlink")
            digest.update(path.readlink().as_posix().encode())
        elif path.is_file():
            digest.update(b"file")
            digest.update(path.read_bytes())
        else:
            digest.update(b"directory")
    return digest.hexdigest()


def _forbidden_boundary_calls(source: str) -> list[str]:
    tree = ast.parse(source)
    forbidden: list[str] = []
    profile_mutations = {"install", "delete", "describe"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ""
        if isinstance(node.func, ast.Attribute):
            parts = [node.func.attr]
            value = node.func.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            name = ".".join(reversed(parts))
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        lowered = name.lower()
        is_sensitive_api = "credential" in lowered or (
            "model" in lowered and any(marker in lowered for marker in ("api", "client", "call"))
        )
        if lowered.startswith("subprocess.") or is_sensitive_api:
            forbidden.append(name)
            continue
        literals = {
            value
            for argument in node.args
            for value in (
                [argument.value]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                else [
                    item.value
                    for item in argument.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                ]
                if isinstance(argument, (ast.Tuple, ast.List))
                else []
            )
        }
        if "profile" in literals and literals & profile_mutations:
            forbidden.append(name or "<call>")
    return forbidden


def test_preflight_and_confirm_uses_three_fresh_detections(tmp_path: Path) -> None:
    calls: list[str] = []
    continued: list[InstallPlan] = []

    def detector() -> HermesDetection:
        calls.append("detect")
        return _detection(tmp_path)

    def continuation(plan: InstallPlan) -> None:
        calls.append("continue")
        continued.append(plan)

    def answer(_: str) -> str:
        calls.append("prompt")
        assert continued == []
        fingerprint = output.getvalue().split("Plan fingerprint: ", 1)[1].splitlines()[0]
        return f"INSTALL AGENTPORTER {fingerprint[:8]}"

    output = StringIO()
    outcome = preflight_and_confirm(
        detector,
        _manifest(tmp_path),
        staging_parent=tmp_path / "staging",
        continuation=continuation,
        input_fn=answer,
        output=output,
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert outcome.status is WorkflowStatus.CONFIRMED
    assert calls == ["detect", "detect", "prompt", "detect", "continue"]
    assert len(continued) == 1
    assert continued[0].staging_dir is not None and not continued[0].staging_dir.exists()


def test_fresh_conflict_before_prompt_blocks_input_and_continuation(tmp_path: Path) -> None:
    plan_detection = _detection(tmp_path)
    conflict_detection = _detection(
        tmp_path,
        profile_entries=(
            ProfileEntry(
                "luna_worker",
                plan_detection.profiles_root / "luna_worker",
                ProfileEntryKind.PROFILE,
            ),
        ),
    )
    detections = iter((plan_detection, conflict_detection))
    calls: list[str] = []

    def detector() -> HermesDetection:
        calls.append("detect")
        return next(detections)

    outcome = preflight_and_confirm(
        detector,
        _manifest(tmp_path),
        staging_parent=tmp_path / "external-staging",
        continuation=_forbidden,
        input_fn=_forbidden,
        output=StringIO(),
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert outcome.status is WorkflowStatus.REJECTED
    assert calls == ["detect", "detect"]


@pytest.mark.parametrize("answer", ["cancel", ""])
def test_preflight_cancel_does_not_modify_real_hermes_home(tmp_path: Path, answer: str) -> None:
    hermes_home = tmp_path / "actual-hermes-home"
    profiles = hermes_home / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "existing-profile").mkdir()
    (profiles / "existing-profile" / "config.yaml").write_text("preserve: true\n")
    detection = replace(_detection(tmp_path), hermes_home=hermes_home, profiles_root=profiles)
    before = _tree_hash(hermes_home)
    staging_parent = tmp_path / "external-staging"
    assert not staging_parent.is_relative_to(hermes_home)

    outcome = preflight_and_confirm(
        lambda: detection,
        _manifest(tmp_path),
        staging_parent=staging_parent,
        continuation=_forbidden,
        input_fn=lambda _: answer,
        output=StringIO(),
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert outcome.status is WorkflowStatus.CANCELLED
    assert _tree_hash(hermes_home) == before


def test_composition_exposes_only_one_write_seam() -> None:
    signature = inspect.signature(preflight_and_confirm)
    callable_parameters = {
        name
        for name, parameter in signature.parameters.items()
        if "Callable" in str(parameter.annotation)
    }
    assert callable_parameters == {"detector", "continuation", "input_fn"}
    assert "cleanup_fn" not in signature.parameters


def test_phase2_preconfirmation_modules_have_no_forbidden_boundary_calls() -> None:
    source_root = Path(__file__).parents[1] / "src" / "agentporter"
    for name in ("planning.py", "workflow.py", "interaction.py", "execution.py"):
        source = (source_root / name).read_text(encoding="utf-8")
        assert _forbidden_boundary_calls(source) == [], name


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nsubprocess.run(['hermes', 'profile', 'install'])\n",
        "credential_api()\n",
        "model_client.call()\n",
        "runner(('hermes', 'profile', 'delete'))\n",
        "runner(['hermes', 'profile', 'describe'])\n",
    ],
)
def test_forbidden_boundary_inventory_positive_controls(source: str) -> None:
    assert _forbidden_boundary_calls(source)
