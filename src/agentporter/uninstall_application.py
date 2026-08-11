from __future__ import annotations

import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TextIO

from .execution import CommandExecutor
from .hermes import HermesDetection, detect_hermes
from .native import NativeHermesAdapter
from .uninstall_discovery import DiscoveryStatus, Finding, discover_installation
from .uninstall_execution import (
    UninstallExecutionResult,
    UninstallExecutionStatus,
    execute_uninstall_plan,
)
from .uninstall_planning import (
    InteractionStatus,
    PlanStatus,
    RevalidationStatus,
    TargetSnapshot,
    UninstallPlan,
    build_uninstall_plan,
    revalidate_uninstall_collection,
    revalidate_uninstall_target,
    run_uninstall_confirmation,
)

_ENTRY_ENV_ALLOWLIST = frozenset(
    {
        "HOME",
        "HERMES_HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONIOENCODING",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TMP",
        "TEMP",
        "TMPDIR",
    }
)


def minimal_process_environment(source: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Copy only non-credential process state required by Hermes CLI execution."""
    return {key: source[key] for key in _ENTRY_ENV_ALLOWLIST if source.get(key)}


class UninstallerStatus(StrEnum):
    ALREADY_ABSENT = "already-absent"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"
    STALE = "stale"
    FAILED = "failed"
    DELETED = "deleted"
    PARTIAL_DELETE = "partial-delete"


@dataclass(frozen=True)
class UninstallerResult:
    status: UninstallerStatus
    findings: tuple[Finding, ...] = ()
    execution: UninstallExecutionResult | None = None


def _application_status(execution: UninstallExecutionResult) -> UninstallerStatus:
    if execution.status is UninstallExecutionStatus.DELETED:
        return UninstallerStatus.DELETED
    if execution.status is UninstallExecutionStatus.PARTIAL_DELETE:
        return UninstallerStatus.PARTIAL_DELETE
    return UninstallerStatus.FAILED


def run_uninstaller(
    env: Mapping[str, str],
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    detector: Callable[..., HermesDetection] = detect_hermes,
    executor_factory: Callable[[], CommandExecutor] = CommandExecutor,
    adapter_factory: Callable[
        [CommandExecutor, Mapping[str, str], HermesDetection], NativeHermesAdapter
    ] = NativeHermesAdapter,
) -> UninstallerResult:
    """Discover, confirm, freshly revalidate, and uninstall one exact installation."""
    initial = detector(env=env)
    discovery = discover_installation(initial.profiles_root)
    if discovery.status is DiscoveryStatus.ALREADY_ABSENT:
        return UninstallerResult(UninstallerStatus.ALREADY_ABSENT)
    if discovery.status is DiscoveryStatus.AMBIGUOUS:
        counts = Counter(finding.code for finding in discovery.findings)
        print(f"AgentPorter uninstall blocked: {len(discovery.findings)} finding(s)", file=output)
        for code, count in sorted(counts.items(), key=lambda item: item[0].value):
            print(f"- {code.value}: {count}", file=output)
        return UninstallerResult(UninstallerStatus.AMBIGUOUS, discovery.findings)

    plan = build_uninstall_plan(discovery, executable=initial.executable)
    if plan.status is not PlanStatus.READY:
        return UninstallerResult(UninstallerStatus.FAILED)

    execution: UninstallExecutionResult | None = None

    def continue_uninstall() -> UninstallExecutionResult:
        nonlocal execution
        executor = executor_factory()
        adapter = adapter_factory(executor, env, initial)

        def validate_target(
            bound_plan: UninstallPlan, target: TargetSnapshot
        ) -> RevalidationStatus:
            current = detector(env=env)
            if (
                current.executable != bound_plan.executable
                or current.hermes_home != bound_plan.hermes_home
                or current.profiles_root != bound_plan.profiles_root
            ):
                return RevalidationStatus.UNSAFE_PATH
            return revalidate_uninstall_target(bound_plan, target)

        assert plan.executable is not None
        execution = execute_uninstall_plan(
            plan,
            executable=plan.executable,
            executor=executor,
            env=env,
            per_target_revalidate=validate_target,
            enumerate_profiles=adapter.enumerate_profiles,
        )
        return execution

    interaction = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=continue_uninstall,
        input_fn=input_fn,
        output=output,
    )
    if interaction.status in (InteractionStatus.CANCELLED, InteractionStatus.REJECTED):
        return UninstallerResult(UninstallerStatus.CANCELLED)
    if interaction.status is InteractionStatus.STALE:
        return UninstallerResult(UninstallerStatus.STALE)
    if interaction.status is not InteractionStatus.CONFIRMED or execution is None:
        return UninstallerResult(UninstallerStatus.FAILED)
    return UninstallerResult(_application_status(execution), execution=execution)
