"""Formal activation gate for role-name migration before binding authorization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .execution import CommandExecutor
from .hermes import HermesDetection, detect_hermes
from .native import NativeHermesAdapter
from .role_name_migration import (
    MigrationAction,
    MigrationResult,
    MigrationStatus,
    RoleNameMigrationPlan,
    build_role_name_migration_plan,
    execute_role_name_migration,
)
from .uninstall_discovery import discover_installation


class RoleMigrationApplicationStatus(StrEnum):
    LEGACY_NAME_MIGRATION_REQUIRED = "legacy-name-migration-required"
    MIGRATION_AMBIGUOUS = "migration-state-ambiguous"
    NAME_CONFLICT = "name-conflict"
    BINDING_GATE_REACHED = "binding-gate-reached"
    MIGRATION_FAILED = "migration-failed"


@dataclass(frozen=True, slots=True)
class RoleMigrationApplicationResult:
    status: RoleMigrationApplicationStatus
    migration: RoleNameMigrationPlan | MigrationResult


Detector = Callable[..., HermesDetection]
ExecutorFactory = Callable[[], CommandExecutor]
Continuation = Callable[[], object]


def run_role_name_migration_gate(
    env: Mapping[str, str],
    *,
    detector: Detector = detect_hermes,
    executor_factory: ExecutorFactory = CommandExecutor,
    journal_path: Path,
    input_fn: Callable[[str], str] = input,
    binding_continuation: Continuation,
) -> RoleMigrationApplicationResult:
    """Run the independently confirmed static rename gate, then binding continuation."""
    detected = detector(env=env)
    discovery = discover_installation(detected.profiles_root)
    plan = build_role_name_migration_plan(discovery, journal_path)
    if plan.status is MigrationStatus.AMBIGUOUS:
        return RoleMigrationApplicationResult(
            RoleMigrationApplicationStatus.MIGRATION_AMBIGUOUS, plan
        )
    if plan.status is MigrationStatus.CONFLICT:
        return RoleMigrationApplicationResult(RoleMigrationApplicationStatus.NAME_CONFLICT, plan)
    if plan.status is MigrationStatus.CURRENT:
        binding_continuation()
        return RoleMigrationApplicationResult(
            RoleMigrationApplicationStatus.BINDING_GATE_REACHED, plan
        )

    action = MigrationAction.APPLY
    prompt = "Migrate legacy AgentPorter Profile names? [yes/no]: "
    if plan.status is MigrationStatus.RECOVERY_REQUIRED:
        response = input_fn(
            "Recover interrupted Profile rename [continue/rollback/cancel]: "
        ).strip()
        if response == "continue":
            action = MigrationAction.CONTINUE
        elif response == "rollback":
            action = MigrationAction.ROLLBACK
        else:
            return RoleMigrationApplicationResult(
                RoleMigrationApplicationStatus.LEGACY_NAME_MIGRATION_REQUIRED, plan
            )
    elif input_fn(prompt).strip().lower() != "yes":
        return RoleMigrationApplicationResult(
            RoleMigrationApplicationStatus.LEGACY_NAME_MIGRATION_REQUIRED, plan
        )

    # Create the write-capable boundary only after the independent name authorization.
    fresh_detection = detector(env=env)
    fresh_discovery = discover_installation(fresh_detection.profiles_root)
    fresh_plan = build_role_name_migration_plan(fresh_discovery, journal_path)
    if fresh_plan.fingerprint != plan.fingerprint:
        return RoleMigrationApplicationResult(
            RoleMigrationApplicationStatus.MIGRATION_AMBIGUOUS, fresh_plan
        )
    executor = executor_factory()
    adapter = NativeHermesAdapter(executor, env, fresh_detection)
    result = execute_role_name_migration(
        fresh_plan,
        action=action,
        rename=adapter.rename,
        rediscover=lambda: discover_installation(fresh_detection.profiles_root),
    )
    if result.status in {MigrationStatus.COMPLETE, MigrationStatus.COMPENSATED}:
        if result.status is MigrationStatus.COMPLETE:
            binding_continuation()
            return RoleMigrationApplicationResult(
                RoleMigrationApplicationStatus.BINDING_GATE_REACHED, result
            )
        return RoleMigrationApplicationResult(
            RoleMigrationApplicationStatus.LEGACY_NAME_MIGRATION_REQUIRED, result
        )
    return RoleMigrationApplicationResult(RoleMigrationApplicationStatus.MIGRATION_FAILED, result)


def activation_after_software_update(
    env: Mapping[str, str],
    **kwargs: object,
) -> RoleMigrationApplicationResult:
    """Public post-update reachability; update itself performs no rename or binding write."""
    return run_role_name_migration_gate(env, **kwargs)  # type: ignore[arg-type]
