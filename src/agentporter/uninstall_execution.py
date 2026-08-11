from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Protocol

from .execution import CommandExecutor, CommandOutcome, CommandStatus
from .hermes import ProfileEntry
from .models import HermesProfileName
from .uninstall_planning import (
    PlanStatus,
    RevalidationStatus,
    TargetSnapshot,
    UninstallPlan,
    executable_identity_matches,
)


class UninstallItemStatus(StrEnum):
    DELETED = "deleted"
    DELETE_FAILED = "delete-failed"
    VERIFICATION_FAILED = "verification-failed"


class UninstallExecutionStatus(StrEnum):
    DELETED = "deleted"
    DELETE_FAILED = "delete-failed"
    VERIFICATION_FAILED = "verification-failed"
    MARKER_CHANGED = "marker-changed"
    UNSAFE_PATH = "unsafe-path"
    PARTIAL_DELETE = "partial-delete"


class ProfileEnumerator(Protocol):
    def __call__(self) -> Sequence[ProfileEntry]: ...


@dataclass(frozen=True)
class UninstallItemResult:
    target: TargetSnapshot
    status: UninstallItemStatus
    command: CommandOutcome
    profiles_after: tuple[ProfileEntry, ...] | None
    path_absent: bool | None


@dataclass(frozen=True)
class UninstallExecutionResult:
    status: UninstallExecutionStatus
    items: tuple[UninstallItemResult, ...]


def _valid_plan(plan: UninstallPlan) -> bool:
    unsealed = replace(plan, fingerprint="")
    payload = asdict(unsealed)
    payload.pop("fingerprint")
    payload.pop("confirmation_phrase")
    canonical = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    if (
        plan.status is not PlanStatus.READY
        or plan.hermes_home is None
        or plan.profiles_root is None
        or plan.fingerprint != fingerprint
    ):
        return False
    for target in plan.targets:
        try:
            name = str(HermesProfileName(target.current_name))
        except (TypeError, ValueError):
            return False
        if target.path != plan.profiles_root / name or target.path.parent != plan.profiles_root:
            return False
    return True


def execute_uninstall_plan(
    plan: UninstallPlan,
    *,
    executor: CommandExecutor,
    env: Mapping[str, str],
    per_target_revalidate: Callable[[UninstallPlan, TargetSnapshot], RevalidationStatus],
    enumerate_profiles: ProfileEnumerator,
) -> UninstallExecutionResult:
    if not _valid_plan(plan) or plan.executable is None:
        raise ValueError("uninstall plan is not ready, sealed, and executable-bound")
    try:
        canonical_executable = plan.executable.resolve(strict=True)
    except (OSError, RuntimeError):
        canonical_executable = None
    if not plan.executable.is_absolute() or plan.executable != canonical_executable:
        raise ValueError("Hermes executable must be an existing canonical absolute path")

    if not executable_identity_matches(plan):
        raise ValueError("sealed Hermes executable identity changed")

    items: list[UninstallItemResult] = []
    for target in plan.targets:
        validation = per_target_revalidate(plan, target)
        if validation is not RevalidationStatus.VALID:
            status = UninstallExecutionStatus(validation.value)
            if items:
                status = UninstallExecutionStatus.PARTIAL_DELETE
            return UninstallExecutionResult(status, tuple(items))

        argv = (str(plan.executable), "profile", "delete", target.current_name, "--yes")
        pending: BaseException | None = None
        command: CommandOutcome | None = None
        try:
            command = executor.run(argv, env=env)
        except BaseException as error:
            pending = error
        try:
            profiles_after: tuple[ProfileEntry, ...] | None = tuple(enumerate_profiles())
        except BaseException as enumeration_error:
            profiles_after = None
            if pending is not None:
                pending.add_note(
                    "post-delete enumeration raised "
                    f"{type(enumeration_error).__name__}; detail suppressed"
                )
        try:
            target.path.lstat()
        except FileNotFoundError:
            path_absent: bool | None = True
        except BaseException as lstat_error:
            path_absent = None
            if pending is not None:
                pending.add_note(
                    f"post-delete lstat raised {type(lstat_error).__name__}; detail suppressed"
                )
        else:
            path_absent = False
        if pending is not None:
            pending.add_note(
                "post-delete readback completed; deletion state is uncertain because "
                "command outcome is unavailable"
            )
            raise pending
        assert command is not None

        if command.status is not CommandStatus.SUCCEEDED:
            item_status = UninstallItemStatus.DELETE_FAILED
            collection_status = UninstallExecutionStatus.DELETE_FAILED
        elif (
            profiles_after is not None
            and not any(entry.name == target.current_name for entry in profiles_after)
            and path_absent is True
        ):
            item_status = UninstallItemStatus.DELETED
            collection_status = UninstallExecutionStatus.DELETED
        else:
            item_status = UninstallItemStatus.VERIFICATION_FAILED
            collection_status = UninstallExecutionStatus.VERIFICATION_FAILED
        items.append(UninstallItemResult(target, item_status, command, profiles_after, path_absent))
        if item_status is not UninstallItemStatus.DELETED:
            if len(items) > 1:
                collection_status = UninstallExecutionStatus.PARTIAL_DELETE
            return UninstallExecutionResult(collection_status, tuple(items))

    return UninstallExecutionResult(UninstallExecutionStatus.DELETED, tuple(items))
