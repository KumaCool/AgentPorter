from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .execution import CommandExecutor, CommandOutcome, CommandStatus
from .hermes import ProfileEntry, ProfileEntryKind
from .planning import InstallPlan, revalidate_install_plan


class AttemptClassification(StrEnum):
    CONFIRMED_CREATED = "confirmed-created"
    ATTEMPT_FAILED_NO_REMNANT = "attempt-failed-no-remnant"
    UNCERTAIN_REMNANT = "uncertain-remnant"


@dataclass(frozen=True)
class SafeCommandResult:
    status: CommandStatus
    returncode: int | None


@dataclass(frozen=True)
class InstallAttempt:
    portable_id: str
    profile_name: str
    classification: AttemptClassification
    command: SafeCommandResult
    reason: str
    before: tuple[ProfileEntry, ...]
    after: tuple[ProfileEntry, ...] | None


@dataclass(frozen=True)
class NativeInstallResult:
    attempts: tuple[InstallAttempt, ...]
    completed: bool
    reason: str


class ProfileEnumerator(Protocol):
    def __call__(self) -> Sequence[ProfileEntry]: ...


def _target(entries: Sequence[ProfileEntry], name: str) -> tuple[ProfileEntry, ...]:
    return tuple(entry for entry in entries if entry.name == name)


def _classify(
    *,
    profile_name: str,
    profiles_root: Path,
    command: CommandOutcome,
    before: tuple[ProfileEntry, ...],
    after: tuple[ProfileEntry, ...] | None,
) -> tuple[AttemptClassification, str]:
    if after is None:
        return AttemptClassification.UNCERTAIN_REMNANT, "post-attempt enumeration failed"
    before_target = _target(before, profile_name)
    after_target = _target(after, profile_name)
    if before_target or len(after_target) > 1:
        return AttemptClassification.UNCERTAIN_REMNANT, "profile observations are contradictory"
    expected_path = profiles_root / profile_name
    reliable_new_target = (
        len(after_target) == 1
        and after_target[0].kind is ProfileEntryKind.PROFILE
        and after_target[0].path == expected_path
    )
    if command.status is CommandStatus.SUCCEEDED and reliable_new_target:
        return (
            AttemptClassification.CONFIRMED_CREATED,
            "command succeeded and target newly appeared",
        )
    if command.status is not CommandStatus.SUCCEEDED and not after_target:
        return (
            AttemptClassification.ATTEMPT_FAILED_NO_REMNANT,
            "command did not succeed and target remains absent",
        )
    return AttemptClassification.UNCERTAIN_REMNANT, "creation or identity readback is uncertain"


def attempt_native_installation(
    plan: InstallPlan,
    *,
    executor: CommandExecutor,
    env: Mapping[str, str],
    enumerate_profiles: ProfileEnumerator,
    revalidate: Callable[[InstallPlan, object], bool] | None = None,
) -> NativeInstallResult:
    if plan.hermes is None or plan.staging_dir is None:
        return NativeInstallResult((), False, "install plan is incomplete")
    validate = revalidate_install_plan if revalidate is None else revalidate
    attempts: list[InstallAttempt] = []
    confirmed_names: set[str] = set()
    for worker in plan.workers:
        try:
            before = tuple(enumerate_profiles())
        except BaseException:
            return NativeInstallResult(tuple(attempts), False, "pre-attempt enumeration failed")
        validation_entries = tuple(entry for entry in before if entry.name not in confirmed_names)
        current = _detection_from_observations(plan, validation_entries)
        if not validate(plan, current) or _target(before, worker.profile_name):
            return NativeInstallResult(tuple(attempts), False, "pre-attempt revalidation failed")
        argv = (
            str(plan.hermes.executable),
            "profile",
            "install",
            str(plan.staging_dir / worker.profile_name),
            "--yes",
        )
        pending: BaseException | None = None
        command: CommandOutcome | None = None
        try:
            command = executor.run(argv, env=env)
        except BaseException as error:
            pending = error
        try:
            after: tuple[ProfileEntry, ...] | None = tuple(enumerate_profiles())
        except BaseException as post_error:
            after = None
            if pending is not None:
                post_type = type(post_error).__name__
                pending.add_note(f"post-attempt enumeration raised {post_type}; detail suppressed")
            else:
                post_error = None
        if pending is not None:
            pending.add_note(
                "post-attempt classification: uncertain-remnant; command outcome unavailable"
            )
            raise pending
        assert command is not None
        classification, reason = _classify(
            profile_name=worker.profile_name,
            profiles_root=plan.hermes.profiles_root,
            command=command,
            before=before,
            after=after,
        )
        attempts.append(
            InstallAttempt(
                worker.portable_id,
                worker.profile_name,
                classification,
                SafeCommandResult(command.status, command.returncode),
                reason,
                before,
                after,
            )
        )
        if classification is not AttemptClassification.CONFIRMED_CREATED:
            return NativeInstallResult(tuple(attempts), False, reason)
        confirmed_names.add(worker.profile_name)
    return NativeInstallResult(
        tuple(attempts), True, "all native install attempts confirmed created"
    )


def _detection_from_observations(plan: InstallPlan, entries: tuple[ProfileEntry, ...]):
    from .hermes import HermesCapabilities, HermesDetection

    assert plan.hermes is not None
    required = frozenset({"install", "delete", "describe", "list", "info"})
    return HermesDetection(
        executable=plan.hermes.executable,
        version=plan.hermes.version,
        hermes_home=plan.hermes.home,
        profiles_root=plan.hermes.profiles_root,
        capabilities=HermesCapabilities(required, frozenset()),
        profile_entries=entries,
    )
