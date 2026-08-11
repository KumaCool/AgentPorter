from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .execution import CommandExecutor
from .hermes import HermesDetection, detect_hermes
from .native import NativeHermesAdapter
from .planning import InstallPlan, revalidate_install_plan
from .transaction import InstallTransactionResult, execute_install_transaction
from .workflow import WorkflowOutcome, WorkflowStatus, preflight_and_confirm


@dataclass(frozen=True)
class InstallerResult:
    workflow: WorkflowOutcome
    transaction: InstallTransactionResult | None


def run_installer(
    manifest_path: Path,
    staging_parent: Path,
    env: Mapping[str, str],
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    executor_factory: Callable[[], CommandExecutor] = CommandExecutor,
    detector: Callable[..., HermesDetection] = detect_hermes,
    adapter_factory: Callable[
        [CommandExecutor, Mapping[str, str], HermesDetection], NativeHermesAdapter
    ] = NativeHermesAdapter,
    **preflight_kwargs: object,
) -> InstallerResult:
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
    return InstallerResult(workflow, transaction)
