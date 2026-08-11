from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from agentporter.installation import AttemptClassification, attempt_native_installation
from agentporter.planning import InstallPlan, cleanup_staging, plan_installation

REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})
INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")


def _manifest(tmp_path: Path) -> Path:
    data = yaml.safe_load((Path(__file__).parents[1] / "workers.yaml").read_text(encoding="utf-8"))
    for worker in data["workers"].values():
        worker["provider"] = "static-public-provider"
    path = tmp_path / "workers.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _detection(tmp_path: Path, entries: tuple[ProfileEntry, ...] = ()) -> HermesDetection:
    home = tmp_path / "hermes-home"
    return HermesDetection(
        executable=tmp_path / "bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=entries,
    )


def _plan(tmp_path: Path) -> InstallPlan:
    return plan_installation(
        _detection(tmp_path),
        _manifest(tmp_path),
        staging_parent=tmp_path / "staging",
        installation_id_factory=lambda: INSTALLATION_ID,
    )


def _entry(
    plan: InstallPlan, index: int, *, kind: ProfileEntryKind = ProfileEntryKind.PROFILE
) -> ProfileEntry:
    assert plan.hermes is not None
    worker = plan.workers[index]
    return ProfileEntry(worker.profile_name, plan.hermes.profiles_root / worker.profile_name, kind)


class FakeExecutor:
    def __init__(self, outcomes: Sequence[CommandOutcome | BaseException]) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str]]] = []

    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
        normalized = tuple(argv)
        self.calls.append((normalized, env))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _outcome(status: CommandStatus, returncode: int | None = None) -> CommandOutcome:
    return CommandOutcome(
        status, ("ignored",), returncode, stdout="private stdout", stderr="private stderr"
    )


def test_successful_installs_are_attempted_in_manifest_order_and_confirmed(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    executor = FakeExecutor(
        [_outcome(CommandStatus.SUCCEEDED, 0), _outcome(CommandStatus.SUCCEEDED, 0)]
    )
    snapshots = iter(
        [
            (),
            (_entry(plan, 0),),
            (_entry(plan, 0),),
            (_entry(plan, 0), _entry(plan, 1)),
        ]
    )
    env = {"HOME": str(tmp_path / "home"), "HERMES_HOME": str(plan.hermes.home)}  # type: ignore[union-attr]

    result = attempt_native_installation(
        plan,
        executor=executor,  # type: ignore[arg-type]
        env=env,
        enumerate_profiles=lambda: next(snapshots),
    )

    assert [attempt.classification for attempt in result.attempts] == [
        AttemptClassification.CONFIRMED_CREATED,
        AttemptClassification.CONFIRMED_CREATED,
    ]
    assert [call[0] for call in executor.calls] == [
        (
            str(plan.hermes.executable),  # type: ignore[union-attr]
            "profile",
            "install",
            str(plan.staging_dir / plan.workers[0].profile_name),  # type: ignore[operator]
            "--yes",
        ),
        (
            str(plan.hermes.executable),  # type: ignore[union-attr]
            "profile",
            "install",
            str(plan.staging_dir / plan.workers[1].profile_name),  # type: ignore[operator]
            "--yes",
        ),
    ]
    assert all(call_env is env for _, call_env in executor.calls)
    assert "private stdout" not in repr(result)
    assert "private stderr" not in repr(result)
    assert cleanup_staging(plan).status == "cleaned"


@pytest.mark.parametrize(
    ("status", "returncode"),
    [
        (CommandStatus.FAILED, 7),
        (CommandStatus.TIMED_OUT, None),
        (CommandStatus.INTERRUPTED, None),
    ],
)
def test_non_success_with_reliable_absence_is_closed_failure_and_stops(
    tmp_path: Path, status: CommandStatus, returncode: int | None
) -> None:
    plan = _plan(tmp_path)
    executor = FakeExecutor([_outcome(status, returncode), _outcome(CommandStatus.SUCCEEDED, 0)])
    enumerations = iter([(), ()])

    result = attempt_native_installation(
        plan,
        executor=executor,  # type: ignore[arg-type]
        env={"HERMES_HOME": str(plan.hermes.home)},  # type: ignore[union-attr]
        enumerate_profiles=lambda: next(enumerations),
    )

    assert len(executor.calls) == 1
    assert result.completed is False
    assert result.attempts[0].classification is AttemptClassification.ATTEMPT_FAILED_NO_REMNANT
    assert result.attempts[0].command.status is status
    assert result.attempts[0].command.returncode == returncode
    assert cleanup_staging(plan).status == "cleaned"


@pytest.mark.parametrize(
    "status", [CommandStatus.FAILED, CommandStatus.TIMED_OUT, CommandStatus.INTERRUPTED]
)
def test_new_target_after_non_success_is_uncertain_and_stops(
    tmp_path: Path, status: CommandStatus
) -> None:
    plan = _plan(tmp_path)
    executor = FakeExecutor([_outcome(status)])
    enumerations = iter([(), (_entry(plan, 0),)])

    result = attempt_native_installation(
        plan,
        executor=executor,  # type: ignore[arg-type]
        env={},
        enumerate_profiles=lambda: next(enumerations),
    )

    assert result.attempts[0].classification is AttemptClassification.UNCERTAIN_REMNANT
    assert len(executor.calls) == 1
    assert cleanup_staging(plan).status == "cleaned"


def test_post_attempt_enumeration_error_is_uncertain_and_does_not_leak_detail(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    calls = 0

    def enumerate_profiles() -> tuple[ProfileEntry, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private enumeration detail")
        return ()

    result = attempt_native_installation(
        plan,
        executor=FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0)]),  # type: ignore[arg-type]
        env={},
        enumerate_profiles=enumerate_profiles,
    )

    assert calls == 2
    assert result.attempts[0].classification is AttemptClassification.UNCERTAIN_REMNANT
    assert "private enumeration detail" not in repr(result)
    assert cleanup_staging(plan).status == "cleaned"


@pytest.mark.parametrize("kind", [ProfileEntryKind.SYMLINK, ProfileEntryKind.NON_DIRECTORY])
def test_success_with_non_profile_target_is_uncertain(
    tmp_path: Path, kind: ProfileEntryKind
) -> None:
    plan = _plan(tmp_path)
    enumerations = iter([(), (_entry(plan, 0, kind=kind),)])

    result = attempt_native_installation(
        plan,
        executor=FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0)]),  # type: ignore[arg-type]
        env={},
        enumerate_profiles=lambda: next(enumerations),
    )

    assert result.attempts[0].classification is AttemptClassification.UNCERTAIN_REMNANT
    assert cleanup_staging(plan).status == "cleaned"


def test_success_with_target_still_absent_is_uncertain(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    enumerations = iter([(), ()])

    result = attempt_native_installation(
        plan,
        executor=FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0)]),  # type: ignore[arg-type]
        env={},
        enumerate_profiles=lambda: next(enumerations),
    )

    assert result.attempts[0].classification is AttemptClassification.UNCERTAIN_REMNANT
    assert cleanup_staging(plan).status == "cleaned"


def test_system_exit_from_executor_runs_post_attempt_enumeration_then_propagates(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    exit_error = SystemExit(17)
    observations: list[str] = []

    def enumerate_profiles() -> tuple[ProfileEntry, ...]:
        observations.append("enumerate")
        return ()

    with pytest.raises(SystemExit) as raised:
        attempt_native_installation(
            plan,
            executor=FakeExecutor([exit_error]),  # type: ignore[arg-type]
            env={},
            enumerate_profiles=enumerate_profiles,
        )

    assert raised.value is exit_error
    assert observations == ["enumerate", "enumerate"]
    assert any("uncertain-remnant" in note for note in raised.value.__notes__)
    assert cleanup_staging(plan).status == "cleaned"


def test_pending_system_exit_is_not_masked_by_post_attempt_baseexception(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    exit_error = SystemExit(23)
    calls = 0

    def enumerate_profiles() -> tuple[ProfileEntry, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("private post detail")
        return ()

    with pytest.raises(SystemExit) as raised:
        attempt_native_installation(
            plan,
            executor=FakeExecutor([exit_error]),  # type: ignore[arg-type]
            env={},
            enumerate_profiles=enumerate_profiles,
        )

    assert raised.value is exit_error
    assert calls == 2
    assert any("KeyboardInterrupt" in note for note in raised.value.__notes__)
    assert all("private post detail" not in note for note in raised.value.__notes__)
    assert cleanup_staging(plan).status == "cleaned"


def test_pre_attempt_revalidation_failure_makes_zero_install_calls(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    executor = FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0)])

    result = attempt_native_installation(
        plan,
        executor=executor,  # type: ignore[arg-type]
        env={},
        enumerate_profiles=lambda: (),
        revalidate=lambda _plan, _current: False,
    )

    assert result.attempts == ()
    assert executor.calls == []
    assert cleanup_staging(plan).status == "cleaned"
