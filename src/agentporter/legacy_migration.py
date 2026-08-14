"""Explicit, sealed legacy v0.2.0 orchestrator-removal migration."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TextIO

from .execution import CommandOutcome
from .hermes import ProfileEntry
from .identity import INSTALL_COMPONENT_IDS, LEGACY_V020_COMPONENT_IDS
from .uninstall_discovery import DiscoveryResult
from .uninstall_planning import (
    PlanStatus,
    RevalidationStatus,
    TargetSnapshot,
    UninstallPlan,
    build_uninstall_plan,
)


class LegacyMigrationStatus(StrEnum):
    READY = "ready"
    INVALID = "invalid"
    CANCELLED = "cancelled"
    STALE = "stale"
    MIGRATED = "migrated"
    FAILED = "failed"


@dataclass(frozen=True)
class LegacyMigrationPlan:
    status: LegacyMigrationStatus
    sealed_installation: UninstallPlan
    target: TargetSnapshot | None
    retained_component_ids: tuple[str, ...]
    journal_path: Path
    fingerprint: str = field(repr=False)
    confirmation_phrase: str | None = field(repr=False)


@dataclass(frozen=True)
class LegacyMigrationResult:
    status: LegacyMigrationStatus
    command: CommandOutcome | None = None
    target_absent: bool | None = None
    current_component_set_observed: bool | None = None


class Executor(Protocol):
    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome: ...


_ORCHESTRATOR_ID = LEGACY_V020_COMPONENT_IDS["agentporter_orchestrator"]
_RETAINED_IDS = tuple(INSTALL_COMPONENT_IDS.values())


def _fingerprint(plan: LegacyMigrationPlan) -> str:
    payload = asdict(plan)
    payload.pop("fingerprint")
    payload.pop("confirmation_phrase")
    return hashlib.sha256(
        json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _invalid(journal_path: Path) -> LegacyMigrationPlan:
    empty = build_uninstall_plan((), executable=Path("/invalid"))
    return LegacyMigrationPlan(
        LegacyMigrationStatus.INVALID, empty, None, _RETAINED_IDS, journal_path, "", None
    )


def build_legacy_migration_plan(
    discovery: DiscoveryResult, *, executable: Path, journal_path: Path
) -> LegacyMigrationPlan:
    """Seal the exact released three-component set and select only its marker-owned control."""
    sealed = build_uninstall_plan(discovery, executable=executable)
    if sealed.status is not PlanStatus.READY:
        return _invalid(journal_path)
    if tuple(target.component_id for target in sealed.targets) != tuple(
        LEGACY_V020_COMPONENT_IDS.values()
    ):
        return _invalid(journal_path)
    targets = tuple(target for target in sealed.targets if target.component_id == _ORCHESTRATOR_ID)
    if len(targets) != 1 or sealed.installation_id is None or not journal_path.is_absolute():
        return _invalid(journal_path)
    plan = LegacyMigrationPlan(
        LegacyMigrationStatus.READY,
        sealed,
        targets[0],
        _RETAINED_IDS,
        journal_path,
        "",
        f"REMOVE LEGACY ORCHESTRATOR {sealed.installation_id[:8]}",
    )
    return replace(plan, fingerprint=_fingerprint(plan))


def _valid(plan: LegacyMigrationPlan) -> bool:
    return (
        plan.status is LegacyMigrationStatus.READY
        and plan.target is not None
        and plan.target in plan.sealed_installation.targets
        and plan.target.component_id == _ORCHESTRATOR_ID
        and tuple(
            target.component_id
            for target in plan.sealed_installation.targets
            if target.component_id != _ORCHESTRATOR_ID
        )
        == plan.retained_component_ids
        == _RETAINED_IDS
        and plan.fingerprint == _fingerprint(replace(plan, fingerprint=""))
        and plan.confirmation_phrase is not None
    )


def _write_journal(plan: LegacyMigrationPlan, **state: object) -> None:
    """Durably record sealed authority and post-attempt truth without credentials."""
    target = plan.target
    sealed = plan.sealed_installation
    assert target is not None
    payload: dict[str, object] = {
        "schema_version": 1,
        "state": "authorized",
        "fingerprint": plan.fingerprint,
        "installation_id": sealed.installation_id,
        "component_id": target.component_id,
        "current_name": target.current_name,
        "profile_path": str(target.path),
        "profiles_root": str(sealed.profiles_root),
        "executable": str(sealed.executable),
        **state,
    }
    plan.journal_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = plan.journal_path.with_name(f".{plan.journal_path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, plan.journal_path)
        directory = os.open(plan.journal_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _observe(
    plan: LegacyMigrationPlan,
    enumerate_profiles: Callable[[], Sequence[ProfileEntry]],
    revalidate: Callable[[UninstallPlan, TargetSnapshot], RevalidationStatus],
) -> tuple[bool | None, bool | None]:
    assert plan.target is not None
    try:
        entries = tuple(enumerate_profiles())
        name_absent = not any(entry.name == plan.target.current_name for entry in entries)
    except BaseException:
        name_absent = None
    try:
        plan.target.path.lstat()
    except FileNotFoundError:
        path_absent: bool | None = True
    except BaseException:
        path_absent = None
    else:
        path_absent = False
    target_absent = True if name_absent is True and path_absent is True else None
    if name_absent is False or path_absent is False:
        target_absent = False
    try:
        retained = tuple(
            target
            for target in plan.sealed_installation.targets
            if target.component_id in plan.retained_component_ids
        )
        retained_valid = all(
            revalidate(plan.sealed_installation, target) is RevalidationStatus.VALID
            for target in retained
        )
    except BaseException:
        retained_valid = False
    current = target_absent is True and retained_valid
    return target_absent, current


def execute_legacy_migration(
    plan: LegacyMigrationPlan,
    *,
    executor: Executor,
    env: Mapping[str, str],
    per_target_revalidate: Callable[[UninstallPlan, TargetSnapshot], RevalidationStatus],
    enumerate_profiles: Callable[[], Sequence[ProfileEntry]],
) -> LegacyMigrationResult:
    """Delete only the sealed orchestrator through Hermes and mandatorily observe every attempt."""
    if not _valid(plan):
        raise ValueError("legacy migration plan is not sealed and ready")
    assert plan.target is not None
    if per_target_revalidate(plan.sealed_installation, plan.target) is not RevalidationStatus.VALID:
        return LegacyMigrationResult(LegacyMigrationStatus.STALE)
    _write_journal(plan, state="authorized")
    argv = (
        str(plan.sealed_installation.executable),
        "profile",
        "delete",
        plan.target.current_name,
        "--yes",
    )
    command: CommandOutcome | None = None
    pending: BaseException | None = None
    try:
        command = executor.run(argv, env=env)
    except BaseException as error:
        pending = error
    target_absent, current = _observe(plan, enumerate_profiles, per_target_revalidate)
    _write_journal(
        plan,
        state="effect-attempted",
        command_status=command.status.value if command is not None else "interrupted",
        returncode=command.returncode if command is not None else None,
        target_absent=target_absent,
        current_component_set_observed=current,
    )
    if pending is not None:
        pending.add_note("legacy migration post-attempt observation recorded")
        raise pending
    assert command is not None
    # A nonzero/timeout may still have completed deletion; authoritative observation wins.
    if current:
        plan.journal_path.unlink()
        return LegacyMigrationResult(
            LegacyMigrationStatus.MIGRATED, command, target_absent, current
        )
    return LegacyMigrationResult(LegacyMigrationStatus.FAILED, command, target_absent, current)


def run_legacy_migration_confirmation(
    plan: LegacyMigrationPlan,
    *,
    revalidate_collection: Callable[[UninstallPlan], bool],
    continuation: Callable[[], LegacyMigrationResult],
    input_fn: Callable[[str], str] = input,
    output: TextIO,
) -> LegacyMigrationResult:
    """Require a separate exact authorization and collection revalidation before effect."""
    if not _valid(plan):
        return LegacyMigrationResult(LegacyMigrationStatus.INVALID)
    print("Legacy v0.2.0 orchestrator Profile removal is separately destructive.", file=output)
    answer = input_fn(f"Type exactly '{plan.confirmation_phrase}' to continue: ")
    if answer != plan.confirmation_phrase:
        return LegacyMigrationResult(LegacyMigrationStatus.CANCELLED)
    if not revalidate_collection(plan.sealed_installation):
        return LegacyMigrationResult(LegacyMigrationStatus.STALE)
    return continuation()
