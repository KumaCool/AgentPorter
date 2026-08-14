from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from agentporter.compensation import CompensationItemStatus, CompensationStatus, compensate_profiles
from agentporter.execution import CommandExecutor
from agentporter.hermes import HermesDetection, detect_hermes
from agentporter.install_workflow import InstallWorkflowStatus
from agentporter.native import NativeHermesAdapter
from agentporter.planning import cleanup_staging, confirm_install_plan, plan_installation
from agentporter.readback import validate_readback_collection
from agentporter.transaction import InstallTransactionStatus, execute_install_transaction
from agentporter.workflow import render_plan_text
from tests.plan06_support import runtime_bindings

plan_installation = partial(plan_installation, binding_selection=runtime_bindings())

HERMES = Path("/usr/local/lib/hermes-agent/venv/bin/hermes")
MANIFEST = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
MODEL_COMMANDS = frozenset({"chat", "run"})


@pytest.fixture
def isolated_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("phase3-real-hermes")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=False)
        assert not root.exists()


class AuditedRunner:
    def __init__(self, *, fault: str | None = None) -> None:
        self.fault = fault
        self.calls: list[tuple[str, ...]] = []
        self.install_calls = 0

    def __call__(
        self,
        argv: Sequence[str],
        *,
        shell: bool,
        env: Mapping[str, str],
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(argv)
        self.calls.append(normalized)
        assert shell is False
        assert check is False
        assert capture_output is True
        assert text is True
        assert not (set(normalized[1:]) & MODEL_COMMANDS)
        assert "--auto" not in normalized
        assert not any(key.endswith("API_KEY") and value for key, value in env.items())

        is_install = normalized[1:3] == ("profile", "install")
        if is_install:
            self.install_calls += 1
            if self.fault == "second-failed" and self.install_calls == 2:
                return subprocess.CompletedProcess(normalized, 73, "", "synthetic second failure")

        completed = subprocess.run(
            normalized,
            shell=False,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if is_install and self.fault == "first-uncertain" and self.install_calls == 1:
            assert completed.returncode == 0, completed.stderr
            return subprocess.CompletedProcess(
                normalized, 124, completed.stdout, "synthetic timeout"
            )
        return completed


def _environment(root: Path) -> dict[str, str]:
    home = root / "home"
    hermes_home = root / "hermes"
    home.mkdir()
    hermes_home.mkdir()
    return {
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "PATH": f"{HERMES.parent}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONIOENCODING": "utf-8",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "NOUS_API_KEY": "",
    }


def _detection(env: Mapping[str, str], runner: AuditedRunner) -> HermesDetection:
    return detect_hermes(env=env, runner=runner)


def _compose(
    root: Path, runner: AuditedRunner
) -> tuple[Any, NativeHermesAdapter, CommandExecutor, HermesDetection, dict[str, str]]:
    env = _environment(root)
    detection = _detection(env, runner)
    plan = plan_installation(detection, MANIFEST, staging_parent=root / "staging")
    executor = CommandExecutor(runner=runner, timeout_seconds=30)
    native = NativeHermesAdapter(executor, env, detection)
    return plan, native, executor, detection, env


def _transaction(
    plan: Any,
    native: NativeHermesAdapter,
    executor: CommandExecutor,
    env: Mapping[str, str],
    runner: AuditedRunner,
) -> Any:
    return execute_install_transaction(
        plan,
        executor=executor,
        env=env,
        enumerate_profiles=native.enumerate_profiles,
        set_description=native.set_description,
        read_distribution_info=native.read_distribution_info,
        read_description=native.read_description,
        current_detection=lambda: _detection(env, runner),
        validate_collection=validate_readback_collection,
    )


def _assert_inventory(runner: AuditedRunner) -> None:
    assert runner.calls
    for argv in runner.calls:
        assert argv[0] == str(HERMES.resolve())
        assert "--auto" not in argv
        assert not (set(argv[1:]) & MODEL_COMMANDS)
        if len(argv) > 1 and argv[1] != "--version":
            assert argv[1] == "profile"


def test_real_hermes_installs_reads_back_collects_and_compensates_two_profiles(
    isolated_root: Path,
) -> None:
    runner = AuditedRunner()
    plan, native, executor, detection, env = _compose(isolated_root, runner)

    rendered = render_plan_text(plan)
    assert plan.installable is True
    assert plan.status == "ready"
    assert all(worker.installable for worker in plan.workers)
    assert all(worker.provider == "test-provider" for worker in plan.workers)
    assert f"Fingerprint: {plan.fingerprint}" in rendered
    assert "Provider: test-provider" in rendered
    assert "Model calls: false" in rendered
    assert plan.confirmation_token == plan.fingerprint
    assert confirm_install_plan(plan, plan.confirmation_token) is True

    result = _transaction(plan, native, executor, env, runner)

    assert result.status is InstallTransactionStatus.INSTALLED
    assert result.install.status is InstallWorkflowStatus.SUCCEEDED
    assert result.compensation is None
    readbacks = result.install.verified_compensable
    assert validate_readback_collection(plan, readbacks) == readbacks
    assert {item.snapshot.installation_id for item in readbacks} == {plan.installation_id}
    assert {item.snapshot.component_id for item in readbacks} == {
        worker.component_id for worker in plan.workers
    }
    assert {item.snapshot.basename for item in readbacks} == {
        worker.profile_name for worker in plan.workers
    }
    for item in readbacks:
        profile = item.snapshot.path
        assert profile.is_dir()
        assert item.snapshot.source == (plan.staging_dir / item.worker.profile_name).resolve()
        assert native.read_description(item.worker, env=env) == item.worker.description
        assert set(path.name for path in profile.iterdir()) >= {
            "distribution.yaml",
            "config.yaml",
            "SOUL.md",
            "agentporter-profile.json",
        }

    compensation = compensate_profiles(
        readbacks,
        current_detection=lambda: _detection(env, runner),
        executor=executor,
        env=env,
        enumerate_profiles=native.enumerate_profiles,
    )
    assert compensation.status is CompensationStatus.COMPENSATED
    assert [item.basename for item in compensation.items] == [
        worker.profile_name for worker in reversed(plan.workers)
    ]
    assert all(item.status is CompensationItemStatus.DELETED for item in compensation.items)
    installed_names = {entry.name for entry in native.enumerate_profiles()}
    assert not ({worker.profile_name for worker in plan.workers} & installed_names)
    assert all(
        not (detection.profiles_root / worker.profile_name).exists() for worker in plan.workers
    )

    cleanup = cleanup_staging(plan)
    assert cleanup.status == "cleaned"
    assert plan.staging_dir is not None and not plan.staging_dir.exists()
    _assert_inventory(runner)


def test_real_hermes_second_install_failure_compensates_verified_first_profile(
    isolated_root: Path,
) -> None:
    runner = AuditedRunner(fault="second-failed")
    plan, native, executor, detection, env = _compose(isolated_root, runner)

    result = _transaction(plan, native, executor, env, runner)

    first, second, _orchestrator = plan.workers
    assert result.status is InstallTransactionStatus.INSTALLATION_FAILED_COMPENSATED
    assert result.install.status is InstallWorkflowStatus.ATTEMPT_NO_REMNANT
    assert [item.worker.profile_name for item in result.install.verified_compensable] == [
        first.profile_name
    ]
    assert result.compensation is not None
    assert result.compensation.status is CompensationStatus.COMPENSATED
    assert [item.basename for item in result.compensation.items] == [first.profile_name]
    assert not (detection.profiles_root / first.profile_name).exists()
    assert not (detection.profiles_root / second.profile_name).exists()
    assert result.remaining_uncertain == ()
    assert cleanup_staging(plan).status == "cleaned"
    _assert_inventory(runner)


def test_real_hermes_nonzero_after_first_install_is_uncertain_and_never_product_deleted(
    isolated_root: Path,
) -> None:
    runner = AuditedRunner(fault="first-uncertain")
    plan, native, executor, detection, env = _compose(isolated_root, runner)

    result = _transaction(plan, native, executor, env, runner)

    first, second, _orchestrator = plan.workers
    assert result.install.status is InstallWorkflowStatus.UNCERTAIN_REMNANT
    assert result.install.verified_compensable == ()
    assert result.status is InstallTransactionStatus.COMPENSATION_INCOMPLETE
    assert result.remaining_uncertain == (first.profile_name,)
    assert (detection.profiles_root / first.profile_name).is_dir()
    assert not (detection.profiles_root / second.profile_name).exists()
    assert not any(argv[1:3] == ("profile", "delete") for argv in runner.calls)
    assert plan.staging_dir is not None and plan.staging_dir.is_dir()
    _assert_inventory(runner)
