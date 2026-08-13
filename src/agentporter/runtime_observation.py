"""Pure aggregation of authoritative task/run and bound secondary evidence."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

DerivedState = Literal[
    "launching",
    "active",
    "stale-or-wedged",
    "completed",
    "failed",
    "needs-input",
    "degraded",
    "inconsistent",
]
ContinuityLevel = Literal["event-durable", "orchestrator-resumed"]
_TERMINAL_OUTCOMES = frozenset({"completed", "blocked", "crashed", "timed_out", "gave_up"})
_EVENT_STATES = frozenset({"completed", "failed", "needs-input", "degraded", "inconsistent"})
_SHA = re.compile(r"^[0-9a-f]{40}$")


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


@dataclass(frozen=True, slots=True, repr=False)
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
    current_run_id: str | None = None
    runs: tuple[RunSnapshot, ...] = ()
    workspace: str | None = None
    base_sha: str | None = None
    evidence_run_id: str | None = None
    evidence_workspace: str | None = None
    evidence_base_sha: str | None = None
    tests_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    task_id: str
    state: DerivedState
    safe_reason: str
    requires_reread: bool
    integration_candidate: bool
    evidence_digest_tuple: tuple[object, ...]


def _canonical(path: str, *, label: str) -> str:
    value = path.replace("\\", "/").strip()
    normalized = posixpath.normpath(value)
    if (
        not value
        or value.startswith("/")
        or normalized in {".", ".."}
        or normalized.startswith("../")
    ):
        raise ValueError(f"{label} must be a canonical relative path")
    return normalized


def derive_observation(
    item: ObservationInput, *, now: datetime, heartbeat_freshness: timedelta = timedelta(minutes=2)
) -> RuntimeObservation:
    if heartbeat_freshness <= timedelta(0):
        raise ValueError("heartbeat freshness must be positive")
    allowed = tuple(_canonical(path, label="allowed write") for path in item.allowed_writes)
    paths = tuple(_canonical(path, label="diff path") for path in item.diff_paths)
    escaped = any(
        not any(path == root or path.startswith(root + "/") for root in allowed) for path in paths
    )
    run = item.run
    authoritative_ids = {candidate.run_id for candidate in item.runs}
    current_id = item.current_run_id or (run.run_id if run else None)
    noncurrent = run is not None and (
        run.run_id != current_id or (item.runs and run.run_id not in authoritative_ids)
    )
    evidence_mismatch = any(
        (
            item.evidence_run_id is not None and item.evidence_run_id != current_id,
            item.tests_run_id is not None and item.tests_run_id != current_id,
            item.workspace is not None and item.evidence_workspace != item.workspace,
            item.base_sha is not None and item.evidence_base_sha != item.base_sha,
        )
    )
    serious = next((d for d in item.diagnostics if d.severity in {"error", "critical"}), None)
    contradiction = (
        run is not None
        and run.status in {"launching", "running"}
        and item.task_status in {"done", "archived"}
    )
    reread = False
    integration = False
    if noncurrent:
        state, reason = "inconsistent", "noncurrent-run-evidence"
    elif contradiction:
        state, reason = "inconsistent", "task-run-contradiction"
    elif escaped:
        state, reason = "inconsistent", "write-allowlist-violation"
    elif serious:
        state, reason = (
            ("failed" if serious.severity == "critical" else "degraded"),
            "runtime-diagnostic",
        )
    elif run is not None and run.status == "terminal":
        reread = True
        if run.outcome not in _TERMINAL_OUTCOMES:
            state, reason = "inconsistent", "unknown-terminal-outcome"
        elif run.outcome == "completed":
            state, reason = "completed", "run-completed"
            changed = bool(paths) and item.base_sha is not None and item.head_sha != item.base_sha
            valid_sha = (
                _SHA.fullmatch(item.head_sha) is not None
                and _SHA.fullmatch(item.base_sha or "") is not None
            )
            integration = bool(
                not evidence_mismatch
                and valid_sha
                and changed
                and item.worktree_digest
                and item.log_digest
                and not item.tests_running
                and item.tests_passed is True
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
            run.heartbeat_at is not None
            and timedelta(0) <= now - run.heartbeat_at <= heartbeat_freshness
        )
        if not item.pid_alive or run.pid is None or not heartbeat_fresh:
            state, reason = "stale-or-wedged", "runtime-liveness-failed"
        else:
            state, reason = "active", "current-run-live"
    else:
        state, reason = "inconsistent", "unclassified-runtime-state"
    digest = (
        item.task_status,
        current_id,
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
        paths,
        item.tests_running,
        item.tests_passed,
        item.workspace,
        item.base_sha,
        item.evidence_run_id,
        item.tests_run_id,
    )
    return RuntimeObservation(item.task_id, state, reason, reread, integration, digest)


def should_emit_event(previous: RuntimeObservation | None, current: RuntimeObservation) -> bool:
    return current.state in _EVENT_STATES and (
        previous is None or previous.evidence_digest_tuple != current.evidence_digest_tuple
    )


def derive_structural_continuation(
    *,
    root_status: str,
    previous_run_id: str | None,
    current_run_id: str | None,
    root_id: str | None = None,
    expected_parent_ids: frozenset[str] | None = None,
    actual_parent_statuses: tuple[tuple[str, str], ...] | None = None,
    current_run_root_id: str | None = None,
    current_run_task_id: str | None = None,
    parent_statuses: tuple[str, ...] | None = None,
) -> ContinuityLevel:
    # Legacy status-only calls intentionally cannot establish structural continuity.
    if root_id is None or expected_parent_ids is None or actual_parent_statuses is None:
        return "event-durable"
    actual = dict(actual_parent_statuses)
    exact = len(actual) == len(actual_parent_statuses) and frozenset(actual) == expected_parent_ids
    if (
        exact
        and expected_parent_ids
        and all(value == "done" for value in actual.values())
        and root_status in {"ready", "running"}
        and current_run_id is not None
        and current_run_id != previous_run_id
        and current_run_root_id == root_id
        and current_run_task_id == root_id
    ):
        return "orchestrator-resumed"
    return "event-durable"
