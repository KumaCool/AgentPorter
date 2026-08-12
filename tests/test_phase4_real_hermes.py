from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from agentporter.execution import CommandExecutor, CommandStatus
from agentporter.hermes import HermesDetection, detect_hermes
from agentporter.install_workflow import InstallWorkflowStatus
from agentporter.native import NativeHermesAdapter
from agentporter.planning import cleanup_staging, plan_installation
from agentporter.readback import validate_readback_collection
from agentporter.transaction import InstallTransactionStatus, execute_install_transaction
from agentporter.uninstall_discovery import MARKER_NAME, DiscoveryStatus, discover_installation
from agentporter.uninstall_execution import (
    RevalidationStatus,
    UninstallExecutionStatus,
    UninstallItemStatus,
    execute_uninstall_plan,
)
from agentporter.uninstall_planning import (
    InteractionStatus,
    PlanStatus,
    TargetSnapshot,
    UninstallPlan,
    build_uninstall_plan,
    render_uninstall_plan,
    revalidate_uninstall_collection,
    run_uninstall_confirmation,
)

HERMES = Path("/usr/local/lib/hermes-agent/venv/bin/hermes")
MANIFEST = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
MODEL_COMMANDS = frozenset({"chat", "run"})
RENAMED = (
    "zz-phase4-renamed-luna",
    "aa-phase4-renamed-orion",
    "mm-phase4-renamed-orchestrator",
)


@pytest.fixture
def isolated_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("phase4-real-hermes")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=False)
        assert not root.exists()


class AuditedRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

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
        return subprocess.run(
            normalized,
            shell=False,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


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


def _detect(env: Mapping[str, str], runner: AuditedRunner) -> HermesDetection:
    detection = detect_hermes(env=env, runner=runner)
    assert detection.executable == HERMES.resolve(strict=True)
    assert detection.version.startswith("0.20")
    return detection


def _install_and_rename(
    root: Path,
) -> tuple[
    UninstallPlan,
    NativeHermesAdapter,
    CommandExecutor,
    HermesDetection,
    dict[str, str],
    AuditedRunner,
]:
    runner = AuditedRunner()
    env = _environment(root)
    detection = _detect(env, runner)
    install_plan = plan_installation(detection, MANIFEST, staging_parent=root / "staging")
    executor = CommandExecutor(runner=runner, timeout_seconds=30)
    native = NativeHermesAdapter(executor, env, detection)
    installed = execute_install_transaction(
        install_plan,
        executor=executor,
        env=env,
        enumerate_profiles=native.enumerate_profiles,
        set_description=native.set_description,
        read_distribution_info=native.read_distribution_info,
        read_description=native.read_description,
        current_detection=lambda: _detect(env, runner),
        validate_collection=validate_readback_collection,
    )
    assert installed.status is InstallTransactionStatus.INSTALLED
    assert installed.install.status is InstallWorkflowStatus.SUCCEEDED
    assert (
        validate_readback_collection(install_plan, installed.install.verified_compensable)
        == installed.install.verified_compensable
    )

    old_paths: list[Path] = []
    for worker, new_name in zip(install_plan.workers, RENAMED, strict=True):
        old_path = detection.profiles_root / worker.profile_name
        marker = old_path / MARKER_NAME
        marker_bytes = marker.read_bytes()
        old_paths.append(old_path)
        outcome = executor.run(
            (str(detection.executable), "profile", "rename", worker.profile_name, new_name),
            env=env,
        )
        assert outcome.status is CommandStatus.SUCCEEDED, outcome.stderr
        new_path = detection.profiles_root / new_name
        assert not old_path.exists()
        assert new_path.is_dir()
        assert (new_path / MARKER_NAME).read_bytes() == marker_bytes
    assert all(not path.exists() for path in old_paths)
    assert {entry.name for entry in native.enumerate_profiles()} == set(RENAMED)
    assert cleanup_staging(install_plan).status == "cleaned"

    discovery = discover_installation(detection.profiles_root)
    assert discovery.status is DiscoveryStatus.READY
    plan = build_uninstall_plan(discovery, executable=detection.executable)
    assert plan.status is PlanStatus.READY
    # Discovery is name-sorted, but a sealed plan is in fixed component registry order.
    assert [target.current_name for target in discovery.targets] == sorted(RENAMED)
    assert [target.current_name for target in plan.targets] == list(RENAMED)
    assert revalidate_uninstall_collection(plan)
    return plan, native, executor, detection, env, runner


def _same_identity(info: os.stat_result, expected: tuple[int, int, int]) -> bool:
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)) == expected


def _revalidate_exact_target(plan: UninstallPlan, target: TargetSnapshot) -> RevalidationStatus:
    """Descriptor-bind only the next target; earlier targets may already be absent."""
    assert plan.hermes_home is not None
    assert plan.profiles_root is not None
    if target.path != plan.profiles_root / target.current_name:
        return RevalidationStatus.UNSAFE_PATH
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        home_fd = os.open(plan.hermes_home, directory_flags)
        descriptors.append(home_fd)
        root_info = os.stat("profiles", dir_fd=home_fd, follow_symlinks=False)
        if not _same_identity(
            root_info, (plan.root_device or -1, plan.root_inode or -1, plan.root_type or -1)
        ):
            return RevalidationStatus.UNSAFE_PATH
        root_fd = os.open("profiles", directory_flags, dir_fd=home_fd)
        descriptors.append(root_fd)
        profile_info = os.stat(target.current_name, dir_fd=root_fd, follow_symlinks=False)
        if not _same_identity(
            profile_info, (target.profile_device, target.profile_inode, target.profile_type)
        ):
            return RevalidationStatus.UNSAFE_PATH
        profile_fd = os.open(target.current_name, directory_flags, dir_fd=root_fd)
        descriptors.append(profile_fd)
        marker_info = os.stat(MARKER_NAME, dir_fd=profile_fd, follow_symlinks=False)
        if not _same_identity(
            marker_info, (target.marker_device, target.marker_inode, target.marker_type)
        ):
            return RevalidationStatus.MARKER_CHANGED
        marker_fd = os.open(MARKER_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=profile_fd)
        descriptors.append(marker_fd)
        opened = os.fstat(marker_fd)
        payload = b""
        while chunk := os.read(marker_fd, 65536):
            payload += chunk
        rebound = os.stat(MARKER_NAME, dir_fd=profile_fd, follow_symlinks=False)
        if not _same_identity(opened, (marker_info.st_dev, marker_info.st_ino, stat.S_IFREG)):
            return RevalidationStatus.MARKER_CHANGED
        if not _same_identity(rebound, (opened.st_dev, opened.st_ino, stat.S_IFREG)):
            return RevalidationStatus.MARKER_CHANGED
        if hashlib.sha256(payload).hexdigest() != target.marker_sha256:
            return RevalidationStatus.MARKER_CHANGED
        return RevalidationStatus.VALID
    except OSError:
        return RevalidationStatus.UNSAFE_PATH
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _delete(
    plan: UninstallPlan,
    native: NativeHermesAdapter,
    executor: CommandExecutor,
    detection: HermesDetection,
    env: Mapping[str, str],
    *,
    revalidator: Any = _revalidate_exact_target,
):
    return execute_uninstall_plan(
        plan,
        executor=executor,
        env=env,
        per_target_revalidate=revalidator,
        enumerate_profiles=native.enumerate_profiles,
    )


def _delete_calls(runner: AuditedRunner) -> list[tuple[str, ...]]:
    return [argv for argv in runner.calls if argv[1:3] == ("profile", "delete")]


def _assert_audit(runner: AuditedRunner) -> None:
    assert runner.calls
    assert all(argv[0] == str(HERMES.resolve(strict=True)) for argv in runner.calls)
    assert all("--auto" not in argv for argv in runner.calls)
    assert all(not (set(argv[1:]) & MODEL_COMMANDS) for argv in runner.calls)


def test_real_renamed_collection_confirms_and_deletes_in_fixed_component_order(
    isolated_root: Path,
) -> None:
    plan, native, executor, detection, env, runner = _install_and_rename(isolated_root)
    output = StringIO()

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=lambda: _delete(plan, native, executor, detection, env),
        input_fn=lambda _: plan.confirmation_phrase or "",
        output=output,
    )

    assert outcome.status is InteractionStatus.CONFIRMED
    result = outcome.continuation_result
    assert result is not None
    assert result.status is UninstallExecutionStatus.DELETED
    assert [item.status for item in result.items] == [UninstallItemStatus.DELETED] * 3
    rendered = output.getvalue()
    assert render_uninstall_plan(plan) in rendered
    assert "WARNING:" in rendered
    assert "permanently deleted in its entirety" in rendered
    assert [argv[3] for argv in _delete_calls(runner)] == list(RENAMED)
    assert not ({entry.name for entry in native.enumerate_profiles()} & set(RENAMED))
    assert all(not (detection.profiles_root / name).exists() for name in RENAMED)
    _assert_audit(runner)


def test_real_renamed_collection_cancel_keeps_both_with_zero_delete(isolated_root: Path) -> None:
    plan, native, _, detection, _, runner = _install_and_rename(isolated_root)

    def cancel(_: str) -> str:
        raise EOFError

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=lambda: pytest.fail("cancel must not continue"),
        input_fn=cancel,
        output=StringIO(),
    )

    assert outcome.status is InteractionStatus.CANCELLED
    assert _delete_calls(runner) == []
    assert {entry.name for entry in native.enumerate_profiles()} == set(RENAMED)
    assert all((detection.profiles_root / name).is_dir() for name in RENAMED)
    _assert_audit(runner)


def test_real_corrupt_renamed_marker_is_ambiguous_with_zero_delete(isolated_root: Path) -> None:
    plan, native, _, detection, _, runner = _install_and_rename(isolated_root)
    (plan.targets[0].path / MARKER_NAME).write_bytes(b"{corrupt")

    discovery = discover_installation(detection.profiles_root)

    assert discovery.status is DiscoveryStatus.AMBIGUOUS
    assert discovery.targets == ()
    assert (
        build_uninstall_plan(discovery, executable=detection.executable).status
        is PlanStatus.INVALID
    )
    assert _delete_calls(runner) == []
    assert {entry.name for entry in native.enumerate_profiles()} == set(RENAMED)
    _assert_audit(runner)


def test_real_marker_replacement_after_answer_stales_collection_before_first_delete(
    isolated_root: Path,
) -> None:
    plan, native, executor, detection, env, runner = _install_and_rename(isolated_root)
    marker = plan.targets[0].path / MARKER_NAME

    def confirm_then_replace(_: str) -> str:
        replacement = isolated_root / "replacement-marker"
        replacement.write_bytes(marker.read_bytes())
        os.replace(replacement, marker)
        return plan.confirmation_phrase or ""

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=lambda: _delete(plan, native, executor, detection, env),
        input_fn=confirm_then_replace,
        output=StringIO(),
    )

    assert outcome.status is InteractionStatus.STALE
    assert _delete_calls(runner) == []
    assert {entry.name for entry in native.enumerate_profiles()} == set(RENAMED)
    assert all((detection.profiles_root / name).is_dir() for name in RENAMED)
    _assert_audit(runner)


def test_real_second_rename_at_callback_barrier_is_partial_and_never_deletes_replacement(
    isolated_root: Path,
) -> None:
    plan, native, executor, detection, env, runner = _install_and_rename(isolated_root)
    second = plan.targets[1]
    survivor = detection.profiles_root / "phase4-survivor"
    validations = 0

    def mutate_before_second(bound: UninstallPlan, target: TargetSnapshot) -> RevalidationStatus:
        nonlocal validations
        validations += 1
        if validations == 2:
            target.path.rename(survivor)
            target.path.mkdir()
            (target.path / "occupant-sentinel").write_text("must survive", encoding="utf-8")
        return _revalidate_exact_target(bound, target)

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=lambda: _delete(
            plan,
            native,
            executor,
            detection,
            env,
            revalidator=mutate_before_second,
        ),
        input_fn=lambda _: plan.confirmation_phrase or "",
        output=StringIO(),
    )

    assert outcome.status is InteractionStatus.CONFIRMED
    result = outcome.continuation_result
    assert result is not None
    assert result.status is UninstallExecutionStatus.PARTIAL_DELETE
    assert [item.status for item in result.items] == [UninstallItemStatus.DELETED]
    assert validations == 2
    assert [argv[3] for argv in _delete_calls(runner)] == [plan.targets[0].current_name]
    assert not plan.targets[0].path.exists()
    assert survivor.is_dir() and (survivor / MARKER_NAME).is_file()
    assert second.path.is_dir()
    assert (second.path / "occupant-sentinel").read_text(encoding="utf-8") == "must survive"
    assert {entry.name for entry in native.enumerate_profiles()} == {
        survivor.name,
        second.current_name,
        plan.targets[2].current_name,
    }
    _assert_audit(runner)
