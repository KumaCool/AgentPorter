"""Pure aggregation of authoritative task/run and secondary runtime evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

DerivedState = Literal[
    "launching", "active", "stale-or-wedged", "completed", "failed",
    "needs-input", "degraded", "inconsistent",
]
ContinuityLevel = Literal["event-durable", "orchestrator-resumed"]
_TERMINAL_OUTCOMES = frozenset({"completed", "blocked", "crashed", "timed_out", "gave_up"})
_EVENT_STATES = frozenset({"completed", "failed", "needs-input", "degraded", "inconsistent"})


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Literal["warning", "error", "critical"]
    code: str


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    status: Literal["launching", "running", "terminal"]
    outcome: str | None
    pid: int | None
    heartbeat_at: datetime | None


@dataclass(frozen=True, slots=True)
class ObservationInput:
    task_id: str
    task_status: str
    task_updated_at: datetime
    run: RunSnapshot | None
    pid_alive: bool
    latest_event: str | None
    latest_event_at: datetime | None
    diagnostics: tuple[Diagnostic, ...]
    log_digest: str | None
    worktree_digest: str | None
    head_sha: str
    diff_paths: tuple[str, ...]
    allowed_writes: tuple[str, ...]
    tests_running: bool
    tests_passed: bool | None


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    task_id: str
    state: DerivedState
    safe_reason: str
    requires_reread: bool
    integration_candidate: bool
    evidence_digest_tuple: tuple[object, ...]


def _allowed(path: str, allowed: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in allowed)


def derive_observation(
    item: ObservationInput,
    *,
    now: datetime,
    heartbeat_freshness: timedelta = timedelta(minutes=2),
) -> RuntimeObservation:
    if heartbeat_freshness <= timedelta(0):
        raise ValueError("heartbeat freshness must be positive")
    run = item.run
    state: DerivedState
    reason: str
    reread = False
    integration = False
    contradiction = (
        run is not None
        and run.status in {"launching", "running"}
        and item.task_status in {"done", "archived"}
    )
    escaped = any(not _allowed(path, item.allowed_writes) for path in item.diff_paths)
    if contradiction:
        state, reason = "inconsistent", "task-run-contradiction"
    elif escaped:
        state, reason = "inconsistent", "write-allowlist-violation"
    elif run is not None and run.status == "terminal":
        reread = True
        if run.outcome not in _TERMINAL_OUTCOMES:
            state, reason = "inconsistent", "unknown-terminal-outcome"
        elif run.outcome == "completed":
            state, reason = "completed", "run-completed"
            integration = bool(
                item.worktree_digest and item.head_sha and item.tests_passed is True and not escaped
            )
        elif run.outcome == "blocked":
            state, reason = "needs-input", "run-blocked"
        else:
            state, reason = "failed", f"run-{run.outcome}"
    elif item.task_status == "blocked":
        state, reason = "needs-input", "task-blocked"
    elif any(d.code == "creator-wake-unconfirmed" for d in item.diagnostics):
        state, reason = "degraded", "creator-wake-unconfirmed"
    elif run is None or run.status == "launching":
        state, reason = "launching", "run-not-active"
    elif run.status == "running":
        heartbeat_fresh = (
            run.heartbeat_at is not None and now - run.heartbeat_at <= heartbeat_freshness
        )
        if not item.pid_alive or run.pid is None or not heartbeat_fresh:
            state, reason = "stale-or-wedged", "runtime-liveness-failed"
        else:
            state, reason = "active", "current-run-live"
    else:
        state, reason = "inconsistent", "unclassified-runtime-state"
    digest = (
        item.task_status,
        run.run_id if run else None,
        run.status if run else None,
        run.outcome if run else None,
        item.pid_alive,
        run.heartbeat_at if run else None,
        item.latest_event,
        tuple((d.severity, d.code) for d in item.diagnostics),
        item.log_digest,
        item.worktree_digest,
        item.head_sha,
        item.diff_paths,
        item.tests_running,
        item.tests_passed,
    )
    return RuntimeObservation(item.task_id, state, reason, reread, integration, digest)


def should_emit_event(
    previous: RuntimeObservation | None, current: RuntimeObservation
) -> bool:
    if current.state not in _EVENT_STATES:
        return False
    return previous is None or previous.evidence_digest_tuple != current.evidence_digest_tuple


def derive_structural_continuation(
    *,
    root_status: str,
    parent_statuses: tuple[str, ...],
    previous_run_id: str | None,
    current_run_id: str | None,
) -> ContinuityLevel:
    if (
        parent_statuses
        and all(status == "done" for status in parent_statuses)
        and root_status in {"ready", "running"}
        and current_run_id is not None
        and current_run_id != previous_run_id
    ):
        return "orchestrator-resumed"
    return "event-durable"
