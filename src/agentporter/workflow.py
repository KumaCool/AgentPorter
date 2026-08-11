from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TextIO, TypeVar

from . import planning
from .hermes import HermesDetection
from .interaction import ConfirmationDecision, ConfirmationRequest, confirm_once
from .planning import InstallPlan

_T = TypeVar("_T")


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
    """Project a sealed plan through an explicit, non-free-text display allowlist."""
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
            )
        )
    if plan.status == "configuration-required":
        lines.append(
            "Run configuration remains required after installation (no secrets collected)."
        )
    lines.extend(
        (
            f"Distribution owned: {', '.join(plan.distribution_owned)}",
            "Copied data: none",
            "Modified data: none",
            "Model calls: false",
            "Runtime validated: false",
            f"Compensation boundary: {plan.compensation_boundary}",
            f"Collection status: {plan.status}",
            f"Fingerprint: {plan.fingerprint}",
        )
    )
    return "\n".join(lines)


def request_for_plan(plan: InstallPlan) -> ConfirmationRequest | None:
    """Build the only application-level confirmation request from a sealed plan."""
    if not planning.confirm_install_plan(plan, plan.confirmation_token):
        return None
    return ConfirmationRequest(plan_text=render_plan_text(plan), fingerprint=plan.fingerprint)


def _cleanup_verified(outcome: object) -> bool:
    verified = getattr(outcome, "cleanup_verified", None)
    if isinstance(verified, bool):
        return verified
    status = getattr(outcome, "status", None)
    if status in {"cleaned", "already-absent"}:
        return True
    return outcome is True


def _revalidate(plan: InstallPlan, detection: HermesDetection) -> bool:
    revalidate = getattr(planning, "revalidate_install_plan", None)
    if revalidate is None:
        return False
    return bool(revalidate(plan, detection))


def confirm_preflight_plan(
    plan: InstallPlan,
    *,
    current_detection_provider: Callable[[], HermesDetection],
    continuation: Callable[[InstallPlan], _T],
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    cleanup_fn: Callable[[InstallPlan], object] = planning.cleanup_staging,
) -> WorkflowOutcome:
    """Confirm a live plan, invoke its sole write continuation, then clean staging."""
    result = WorkflowOutcome(
        status=WorkflowStatus.REJECTED,
        reason="plan is not installable or is stale",
        cleanup_verified=False,
    )
    pending_error: BaseException | None = None
    cleanup_issue: object | None = None
    cleanup_verified = False
    try:
        if _revalidate(plan, current_detection_provider()):
            request = request_for_plan(plan)
            if request is not None:
                decision = confirm_once(request, input_fn=input_fn, output=output)
                if decision is ConfirmationDecision.CANCELLED:
                    result = WorkflowOutcome(
                        status=WorkflowStatus.CANCELLED,
                        reason="confirmation cancelled",
                        cleanup_verified=False,
                    )
                elif _revalidate(plan, current_detection_provider()):
                    continuation(plan)
                    result = WorkflowOutcome(
                        status=WorkflowStatus.CONFIRMED,
                        reason="confirmed continuation completed",
                        cleanup_verified=False,
                    )
    except BaseException as error:
        pending_error = error
    finally:
        try:
            cleanup_outcome = cleanup_fn(plan)
            cleanup_verified = _cleanup_verified(cleanup_outcome)
            if not cleanup_verified:
                cleanup_issue = cleanup_outcome
        except Exception as error:
            cleanup_issue = error
        except BaseException as error:
            if pending_error is None:
                raise
            cleanup_issue = error

    if pending_error is not None:
        if not cleanup_verified:
            cleanup_type = type(cleanup_issue).__name__
            pending_error.add_note(f"AgentPorter staging cleanup was not verified ({cleanup_type})")
        raise pending_error
    if not cleanup_verified:
        return WorkflowOutcome(
            status=WorkflowStatus.CLEANUP_FAILED,
            reason="staging cleanup was refused or could not be verified",
            cleanup_verified=False,
        )
    return WorkflowOutcome(
        status=result.status,
        reason=result.reason,
        cleanup_verified=True,
    )


def preflight_and_confirm(
    detector: Callable[[], HermesDetection],
    manifest_path: Path,
    *,
    staging_parent: Path,
    continuation: Callable[[InstallPlan], _T],
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    **preflight_kwargs: object,
) -> WorkflowOutcome:
    """Production Phase-2 composition from preflight through the sole continuation."""
    plan = planning.preflight_installation(
        detector,
        manifest_path,
        staging_parent=staging_parent,
        **preflight_kwargs,
    )

    return confirm_preflight_plan(
        plan,
        current_detection_provider=detector,
        continuation=continuation,
        input_fn=input_fn,
        output=output,
    )
