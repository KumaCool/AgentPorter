"""Formal composition root for dispatch, observation, and continuation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .dispatch_planning import DispatchPlan
from .kanban_runtime import (
    DispatchReceipt,
    KanbanAdapter,
    KanbanCapabilities,
    KanbanRuntime,
    PlannedMutation,
)
from .runtime_observation import (
    ContinuityLevel,
    ObservationInput,
    RuntimeObservation,
    derive_observation,
    derive_structural_continuation,
)


def plan_to_mutations(plan: DispatchPlan) -> tuple[PlannedMutation, ...]:
    """Bridge the validated authority plan into runtime mutations without dropping fields."""
    result: list[PlannedMutation] = []
    for task in plan.tasks:
        ownership = hashlib.sha256(
            json.dumps(
                {"owner": task.contract.shared_owner, "writes": task.contract.writes},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        result.append(
            PlannedMutation(
                local_id=task.local_id,
                board=plan.board,
                tenant=plan.tenant,
                assignee=task.assignee,
                creator_session=plan.creator_session
                if plan.route.source == "creator-session"
                else None,
                workspace=task.workspace.path,
                branch=task.workspace.branch,
                base_sha=task.workspace.base_sha,
                parents=task.parents,
                idempotency_key=task.idempotency_key,
                ownership_digest=ownership,
                route=plan.route,
                subscribe=task.subscribe,
                runnable=True,
            )
        )
    return tuple(result)


class DispatchApplication:
    """Only production composition root for Phase E operations."""

    def __init__(self, adapter: KanbanAdapter, capabilities: KanbanCapabilities) -> None:
        self._runtime = KanbanRuntime(adapter, capabilities)

    def dispatch(
        self, plan: DispatchPlan, *, known_assignees: set[str]
    ) -> tuple[DispatchReceipt, ...]:
        return self._runtime.execute(
            plan_to_mutations(plan),
            known_assignees=known_assignees,
            expected_revision=plan.board_revision,
        )

    @staticmethod
    def observe(item: ObservationInput, **kwargs: Any) -> RuntimeObservation:
        return derive_observation(item, **kwargs)

    @staticmethod
    def continuation(**kwargs: Any) -> ContinuityLevel:
        return derive_structural_continuation(**kwargs)
