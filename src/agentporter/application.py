from __future__ import annotations

import getpass
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .execution import CommandExecutor
from .hermes import HermesDetection, detect_hermes
from .identity import INITIAL_PROFILE_NAMES, INSTALL_COMPONENT_IDS
from .legacy_migration import (
    LegacyMigrationResult,
    LegacyMigrationStatus,
    build_legacy_migration_plan,
    execute_legacy_migration,
    run_legacy_migration_confirmation,
)
from .native import NativeHermesAdapter
from .planning import InstallPlan, RuntimeBindingSelection, revalidate_install_plan
from .transaction import InstallTransactionResult, execute_install_transaction
from .uninstall_discovery import discover_installation
from .uninstall_planning import revalidate_uninstall_collection, revalidate_uninstall_target
from .workflow import WorkflowOutcome, WorkflowStatus, preflight_and_confirm


@dataclass(frozen=True)
class InstallerResult:
    workflow: WorkflowOutcome
    transaction: InstallTransactionResult | None
    binding_selection: Mapping[str, RuntimeBindingSelection]


def run_legacy_orchestrator_migration(
    env: Mapping[str, str],
    *,
    journal_path: Path,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    detector: Callable[..., HermesDetection] = detect_hermes,
    executor_factory: Callable[[], CommandExecutor] = CommandExecutor,
    adapter_factory: Callable[
        [CommandExecutor, Mapping[str, str], HermesDetection], NativeHermesAdapter
    ] = NativeHermesAdapter,
) -> LegacyMigrationResult:
    """Formal separately-authorized v0.2.0 component-set contraction lifecycle."""
    initial = detector(env=env)
    plan = build_legacy_migration_plan(
        discover_installation(initial.profiles_root),
        executable=initial.executable,
        journal_path=journal_path,
    )

    def continue_migration() -> LegacyMigrationResult:
        current = detector(env=env)
        if (
            current.executable != initial.executable
            or current.hermes_home != initial.hermes_home
            or current.profiles_root != initial.profiles_root
        ):
            return LegacyMigrationResult(LegacyMigrationStatus.STALE)
        executor = executor_factory()
        adapter = adapter_factory(executor, env, current)
        return execute_legacy_migration(
            plan,
            executor=executor,
            env=env,
            per_target_revalidate=revalidate_uninstall_target,
            enumerate_profiles=adapter.enumerate_profiles,
        )

    return run_legacy_migration_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=continue_migration,
        input_fn=input_fn,
        output=output,
    )


def run_installer(
    manifest_path: Path,
    staging_parent: Path,
    env: Mapping[str, str],
    *,
    input_fn: Callable[[str], str] = input,
    endpoint_reader: Callable[[str], str] = getpass.getpass,
    output: TextIO = sys.stdout,
    executor_factory: Callable[[], CommandExecutor] = CommandExecutor,
    detector: Callable[..., HermesDetection] = detect_hermes,
    adapter_factory: Callable[
        [CommandExecutor, Mapping[str, str], HermesDetection], NativeHermesAdapter
    ] = NativeHermesAdapter,
    **preflight_kwargs: object,
) -> InstallerResult:
    if "binding_selection" not in preflight_kwargs:
        bindings: dict[str, RuntimeBindingSelection] = {}
        for portable_id in INSTALL_COMPONENT_IDS:
            profile_name = INITIAL_PROFILE_NAMES[portable_id]
            model = input_fn(f"Model ID for {profile_name}: ")
            provider = input_fn(f"Provider ID for {profile_name}: ")
            endpoint = endpoint_reader(f"Endpoint for {profile_name} (hidden): ")
            bindings[portable_id] = RuntimeBindingSelection(model, provider, endpoint)
        preflight_kwargs["binding_selection"] = bindings
    transaction: InstallTransactionResult | None = None

    def current_detection() -> HermesDetection:
        return detector(env=env)

    def install(plan: InstallPlan) -> None:
        nonlocal transaction
        detection = current_detection()
        if not revalidate_install_plan(plan, detection):
            return
        executor = executor_factory()
        adapter = adapter_factory(executor, env, detection)
        transaction = execute_install_transaction(
            plan,
            executor=executor,
            env=env,
            enumerate_profiles=adapter.enumerate_profiles,
            set_description=adapter.set_description,
            read_distribution_info=adapter.read_distribution_info,
            read_description=adapter.read_description,
            current_detection=current_detection,
        )

    workflow = preflight_and_confirm(
        current_detection,
        manifest_path,
        staging_parent=staging_parent,
        continuation=install,
        input_fn=input_fn,
        output=output,
        **preflight_kwargs,
    )
    if workflow.status is WorkflowStatus.CONFIRMED:
        if transaction is None:
            workflow = WorkflowOutcome(
                WorkflowStatus.REJECTED,
                "plan became stale before transaction",
                workflow.cleanup_verified,
            )
    else:
        transaction = None
    binding_selection = preflight_kwargs["binding_selection"]
    if not isinstance(binding_selection, Mapping):
        raise TypeError("binding selection authority must be a mapping")
    return InstallerResult(workflow, transaction, binding_selection)  # type: ignore[arg-type]
