from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import pytest

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import ProfileEntry, ProfileEntryKind
from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.uninstall_execution import (
    RevalidationStatus,
    UninstallExecutionStatus,
    UninstallItemStatus,
    execute_uninstall_plan,
)
from agentporter.uninstall_planning import build_uninstall_plan


@dataclass(frozen=True)
class Candidate:
    current_name: str
    path: Path
    product_id: str
    component_id: str
    installation_id: str
    profile_device: int
    profile_inode: int
    profile_type: int
    marker_device: int
    marker_inode: int
    marker_type: int
    marker_sha256: str
    hermes_home: Path
    profiles_root: Path


def ready_plan(tmp_path: Path):
    home = (tmp_path / ".hermes").resolve()
    root = home / "profiles"
    root.mkdir(parents=True)
    installation_id = str(uuid4())
    candidates = []
    for index, (portable_id, component_id) in enumerate(COMPONENT_IDS.items(), start=1):
        name = f"renamed-{portable_id.replace('_', '-')}"
        path = root / name
        path.mkdir()
        candidates.append(
            Candidate(
                current_name=name,
                path=path,
                product_id=PRODUCT_ID,
                component_id=component_id,
                installation_id=installation_id,
                profile_device=1,
                profile_inode=100 + index,
                profile_type=stat.S_IFDIR,
                marker_device=1,
                marker_inode=200 + index,
                marker_type=stat.S_IFREG,
                marker_sha256=hashlib.sha256(name.encode()).hexdigest(),
                hermes_home=home,
                profiles_root=root,
            )
        )
    return build_uninstall_plan(candidates)


def enumerate_root(root: Path) -> tuple[ProfileEntry, ...]:
    return tuple(
        ProfileEntry(path.name, path, ProfileEntryKind.PROFILE)
        for path in sorted(root.iterdir())
    )


def executable_at(tmp_path: Path) -> Path:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir(exist_ok=True)
    executable.touch()
    return executable.resolve(strict=True)


def test_deletes_each_target_in_plan_order_with_exact_native_argv(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)
    executable = executable_at(tmp_path)
    calls: list[tuple[str, ...]] = []

    class DeletingExecutor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            normalized = tuple(argv)
            calls.append(normalized)
            (plan.profiles_root / normalized[3]).rmdir()  # type: ignore[operator]
            return CommandOutcome(CommandStatus.SUCCEEDED, normalized, 0)

    validations: list[str] = []
    result = execute_uninstall_plan(
        plan,
        executable=executable,
        executor=DeletingExecutor(),  # type: ignore[arg-type]
        env={"HOME": str(tmp_path)},
        per_target_revalidate=lambda bound, target: (
            validations.append(target.current_name) or RevalidationStatus.VALID
        ),
        enumerate_profiles=lambda: enumerate_root(plan.profiles_root),  # type: ignore[arg-type]
    )

    names = [target.current_name for target in plan.targets]
    assert result.status is UninstallExecutionStatus.DELETED
    assert [item.status for item in result.items] == [
        UninstallItemStatus.DELETED,
        UninstallItemStatus.DELETED,
    ]
    assert validations == names
    assert calls == [
        (str(executable), "profile", "delete", name, "--yes") for name in names
    ]


def test_first_command_failure_stops_with_delete_failed_even_when_target_absent(
    tmp_path: Path,
) -> None:
    plan = ready_plan(tmp_path)
    calls = 0

    class FailedAfterDeletion:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            nonlocal calls
            calls += 1
            normalized = tuple(argv)
            (plan.profiles_root / normalized[3]).rmdir()  # type: ignore[operator]
            return CommandOutcome(CommandStatus.FAILED, normalized, 9, stderr="native failure")

    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=FailedAfterDeletion(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=lambda _plan, _target: RevalidationStatus.VALID,
        enumerate_profiles=lambda: enumerate_root(plan.profiles_root),  # type: ignore[arg-type]
    )

    assert result.status is UninstallExecutionStatus.DELETE_FAILED
    assert len(result.items) == 1
    assert result.items[0].status is UninstallItemStatus.DELETE_FAILED
    assert result.items[0].path_absent is True
    assert result.items[0].profiles_after is not None
    assert calls == 1


def test_second_command_failure_after_first_delete_is_partial_delete(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)
    calls = 0

    class SecondFails:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            nonlocal calls
            calls += 1
            normalized = tuple(argv)
            (plan.profiles_root / normalized[3]).rmdir()  # type: ignore[operator]
            status = CommandStatus.SUCCEEDED if calls == 1 else CommandStatus.TIMED_OUT
            return CommandOutcome(status, normalized, 0 if calls == 1 else None)

    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=SecondFails(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=lambda _plan, _target: RevalidationStatus.VALID,
        enumerate_profiles=lambda: enumerate_root(plan.profiles_root),  # type: ignore[arg-type]
    )

    assert result.status is UninstallExecutionStatus.PARTIAL_DELETE
    assert [item.status for item in result.items] == [
        UninstallItemStatus.DELETED,
        UninstallItemStatus.DELETE_FAILED,
    ]
    assert calls == 2


def test_second_marker_change_stops_without_second_command_as_partial_delete(
    tmp_path: Path,
) -> None:
    plan = ready_plan(tmp_path)
    calls = 0
    validations = 0

    class DeleteFirst:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            nonlocal calls
            calls += 1
            normalized = tuple(argv)
            (plan.profiles_root / normalized[3]).rmdir()  # type: ignore[operator]
            return CommandOutcome(CommandStatus.SUCCEEDED, normalized, 0)

    def revalidate(_plan: object, _target: object) -> RevalidationStatus:
        nonlocal validations
        validations += 1
        return (
            RevalidationStatus.VALID
            if validations == 1
            else RevalidationStatus.MARKER_CHANGED
        )

    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=DeleteFirst(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=revalidate,  # type: ignore[arg-type]
        enumerate_profiles=lambda: enumerate_root(plan.profiles_root),  # type: ignore[arg-type]
    )

    assert result.status is UninstallExecutionStatus.PARTIAL_DELETE
    assert [item.status for item in result.items] == [UninstallItemStatus.DELETED]
    assert calls == 1
    assert validations == 2


def test_success_with_path_still_present_is_verification_failed(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)

    class NonDeletingExecutor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            return CommandOutcome(CommandStatus.SUCCEEDED, tuple(argv), 0)

    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=NonDeletingExecutor(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=lambda _plan, _target: RevalidationStatus.VALID,
        enumerate_profiles=lambda: (),
    )

    assert result.status is UninstallExecutionStatus.VERIFICATION_FAILED
    assert result.items[0].status is UninstallItemStatus.VERIFICATION_FAILED
    assert result.items[0].profiles_after == ()
    assert result.items[0].path_absent is False


def test_enumeration_error_makes_successful_command_verification_failed(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)

    class DeletingExecutor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            normalized = tuple(argv)
            (plan.profiles_root / normalized[3]).rmdir()  # type: ignore[operator]
            return CommandOutcome(CommandStatus.SUCCEEDED, normalized, 0)

    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=DeletingExecutor(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=lambda _plan, _target: RevalidationStatus.VALID,
        enumerate_profiles=lambda: (_ for _ in ()).throw(OSError("enumeration failed")),
    )

    assert result.status is UninstallExecutionStatus.VERIFICATION_FAILED
    assert result.items[0].profiles_after is None
    assert result.items[0].path_absent is True


def test_lstat_error_makes_successful_command_verification_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = ready_plan(tmp_path)
    original_lstat = Path.lstat
    target_path = plan.targets[0].path

    class DeletingExecutor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            normalized = tuple(argv)
            (plan.profiles_root / normalized[3]).rmdir()  # type: ignore[operator]
            return CommandOutcome(CommandStatus.SUCCEEDED, normalized, 0)

    def selective_lstat(path: Path):
        if path == target_path:
            raise PermissionError("lstat denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", selective_lstat)
    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=DeletingExecutor(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=lambda _plan, _target: RevalidationStatus.VALID,
        enumerate_profiles=lambda: enumerate_root(plan.profiles_root),  # type: ignore[arg-type]
    )

    assert result.status is UninstallExecutionStatus.VERIFICATION_FAILED
    assert result.items[0].profiles_after is not None
    assert result.items[0].path_absent is None


@pytest.mark.parametrize("error", [SystemExit("stop"), KeyboardInterrupt()])
def test_command_baseexception_runs_both_readbacks_then_propagates_with_note(
    tmp_path: Path, error: BaseException
) -> None:
    plan = ready_plan(tmp_path)
    observations: list[str] = []
    target_path = plan.targets[0].path

    class RaisingExecutor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            observations.append("command")
            raise error

    def enumerate_after() -> tuple[ProfileEntry, ...]:
        observations.append("enumerate")
        return enumerate_root(plan.profiles_root)  # type: ignore[arg-type]

    original_lstat = Path.lstat

    def recording_lstat(path: Path):
        if path == target_path:
            observations.append("lstat")
        return original_lstat(path)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(Path, "lstat", recording_lstat)
        with pytest.raises(type(error)) as raised:
            execute_uninstall_plan(
                plan,
                executable=executable_at(tmp_path),
                executor=RaisingExecutor(),  # type: ignore[arg-type]
                env={},
                per_target_revalidate=lambda _plan, _target: RevalidationStatus.VALID,
                enumerate_profiles=enumerate_after,
            )

    assert raised.value is error
    assert observations == ["command", "enumerate", "lstat"]
    assert any("post-delete" in note for note in getattr(error, "__notes__", ()))


def test_pre_command_revalidation_baseexception_propagates_without_readback(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)
    error = SystemExit("revalidation stopped")

    with pytest.raises(SystemExit) as raised:
        execute_uninstall_plan(
            plan,
            executable=executable_at(tmp_path),
            executor=pytest.fail,  # type: ignore[arg-type]
            env={},
            per_target_revalidate=lambda _plan, _target: (_ for _ in ()).throw(error),
            enumerate_profiles=lambda: pytest.fail("must not read back before command"),
        )

    assert raised.value is error


def test_first_unsafe_path_stops_with_zero_commands(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)
    calls = 0

    class MustNotRun:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            nonlocal calls
            calls += 1
            raise AssertionError("command must not run")

    result = execute_uninstall_plan(
        plan,
        executable=executable_at(tmp_path),
        executor=MustNotRun(),  # type: ignore[arg-type]
        env={},
        per_target_revalidate=lambda _plan, _target: RevalidationStatus.UNSAFE_PATH,
        enumerate_profiles=lambda: pytest.fail("must not read back"),
    )

    assert result.status is UninstallExecutionStatus.UNSAFE_PATH
    assert result.items == ()
    assert calls == 0


def test_rejects_tampered_fingerprint_before_any_callback(tmp_path: Path) -> None:
    plan = replace(ready_plan(tmp_path), fingerprint="0" * 64)

    with pytest.raises(ValueError, match="ready and sealed"):
        execute_uninstall_plan(
            plan,
            executable=executable_at(tmp_path),
            executor=pytest.fail,  # type: ignore[arg-type]
            env={},
            per_target_revalidate=lambda _plan, _target: pytest.fail("must not revalidate"),
            enumerate_profiles=lambda: pytest.fail("must not enumerate"),
        )


def test_rejects_noncanonical_or_missing_executable_before_revalidation(tmp_path: Path) -> None:
    plan = ready_plan(tmp_path)
    missing = (tmp_path / "bin" / "missing").absolute()

    with pytest.raises(ValueError, match="existing canonical absolute"):
        execute_uninstall_plan(
            plan,
            executable=missing,
            executor=pytest.fail,  # type: ignore[arg-type]
            env={},
            per_target_revalidate=lambda _plan, _target: pytest.fail("must not revalidate"),
            enumerate_profiles=lambda: pytest.fail("must not enumerate"),
        )
