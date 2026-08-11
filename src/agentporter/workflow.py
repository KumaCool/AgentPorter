from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TextIO

from .interaction import ConfirmationDecision, ConfirmationRequest, confirm_then
from .planning import InstallPlan, cleanup_staging, confirm_install_plan


class WorkflowStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    CLEANUP_FAILED = "cleanup-failed"


@dataclass(frozen=True)
class WorkflowOutcome:
    status: WorkflowStatus
    reason: str
    cleanup_verified: bool


def render_plan_text(plan: InstallPlan) -> str:
    hermes_lines = [
        "Hermes executable: unavailable",
        "Hermes version: unavailable",
        "Hermes home: unavailable",
        "Hermes profiles root: unavailable",
    ]
    if plan.hermes is not None:
        hermes_lines = [
            f"Hermes executable: {plan.hermes.executable}",
            f"Hermes version: {plan.hermes.version}",
            f"Hermes home: {plan.hermes.home}",
            f"Hermes profiles root: {plan.hermes.profiles_root}",
        ]
    lines = [*hermes_lines, "Workers:"]
    for worker in plan.workers:
        lines.extend(
            (
                f"- Portable ID: {worker.portable_id}",
                f"  Component ID: {worker.component_id}",
                f"  Initial profile: {worker.profile_name}",
                f"  Display name: {worker.display_name}",
                f"  Model: {worker.model}",
                f"  Provider: {worker.provider or 'not selected'}",
                f"  Reasoning effort: {worker.reasoning_effort}",
                f"  Status: {worker.status}",
                f"  Reason: {worker.reason}",
            )
        )
    if plan.status == "configuration-required":
        lines.append("Next step: complete non-secret provider selection, then regenerate the plan.")
    lines.extend(
        (
            f"Distribution owned: {', '.join(plan.distribution_owned)}",
            "Copied data: none",
            "Modified data: none",
            "Model calls: false",
            "Runtime validated: false",
            f"Compensation boundary: {plan.compensation_boundary}",
            f"Collection status: {plan.status}",
            f"Collection reason: {plan.reason}",
            f"Fingerprint: {plan.fingerprint}",
        )
    )
    return "\n".join(lines)


def request_for_plan(plan: InstallPlan) -> ConfirmationRequest | None:
    if not confirm_install_plan(plan, plan.confirmation_token):
        return None
    return ConfirmationRequest(plan_text=render_plan_text(plan), fingerprint=plan.fingerprint)


def confirm_preflight_plan(
    plan: InstallPlan,
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    cleanup_fn: Callable[[InstallPlan], bool] = cleanup_staging,
) -> WorkflowOutcome:
    cleanup_plan = replace(plan)
    result = WorkflowOutcome(
        status=WorkflowStatus.REJECTED,
        reason="plan is not ready or its integrity cannot be verified",
        cleanup_verified=False,
    )
    pending_error: BaseException | None = None
    try:
        request = request_for_plan(plan)
        if request is not None:
            confirmation = confirm_then(
                request,
                lambda: confirm_install_plan(plan, request.fingerprint),
                input_fn=input_fn,
                output=output,
            )
            if confirmation.decision is ConfirmationDecision.CANCELLED:
                result = WorkflowOutcome(
                    status=WorkflowStatus.CANCELLED,
                    reason="confirmation cancelled",
                    cleanup_verified=False,
                )
            elif confirmation.continuation_result is True:
                result = WorkflowOutcome(
                    status=WorkflowStatus.CONFIRMED,
                    reason="plan confirmed; installation deferred to Phase 3",
                    cleanup_verified=False,
                )
    except BaseException as error:
        pending_error = error
    finally:
        try:
            cleanup_verified = cleanup_fn(cleanup_plan)
        except BaseException:
            cleanup_verified = False

    if not cleanup_verified:
        return WorkflowOutcome(
            status=WorkflowStatus.CLEANUP_FAILED,
            reason="staging cleanup could not be verified",
            cleanup_verified=False,
        )
    if pending_error is not None:
        raise pending_error
    return WorkflowOutcome(
        status=result.status,
        reason=result.reason,
        cleanup_verified=True,
    )
