from datetime import UTC, datetime, timedelta

from agentporter.runtime_observation import (
    Diagnostic,
    ObservationInput,
    RunSnapshot,
    derive_observation,
    should_emit_event,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def snapshot(**changes):
    values = dict(
        task_id="task-a",
        task_status="running",
        task_updated_at=NOW,
        run=RunSnapshot("run-a", "running", None, 1234, NOW - timedelta(seconds=5)),
        pid_alive=True,
        latest_event="heartbeat",
        latest_event_at=NOW - timedelta(seconds=5),
        diagnostics=(),
        log_digest="log-a",
        worktree_digest="tree-a",
        head_sha="7cc1dad4e49aecfeadf4eb033802a5a990794c69",
        diff_paths=("src/agentporter/new.py",),
        allowed_writes=("src/agentporter/new.py", "tests/test_new.py"),
        tests_running=False,
        tests_passed=None,
        current_run_id="run-a",
        runs=(RunSnapshot("run-a", "running", None, 1234, NOW - timedelta(seconds=5)),),
        workspace="/safe/worktree",
        base_sha="0" * 40,
        evidence_run_id="run-a",
        evidence_workspace="/safe/worktree",
        evidence_base_sha="0" * 40,
        tests_run_id="run-a",
    )
    values.update(changes)
    return ObservationInput(**values)


def test_running_requires_current_run_live_pid_and_fresh_heartbeat():
    assert derive_observation(snapshot(), now=NOW).state == "active"
    assert derive_observation(snapshot(pid_alive=False), now=NOW).state == "stale-or-wedged"
    stale = snapshot(run=RunSnapshot("run-a", "running", None, 1234, NOW - timedelta(minutes=10)))
    assert derive_observation(stale, now=NOW).state == "stale-or-wedged"


def test_terminal_run_overrides_old_running_task_snapshot():
    item = snapshot(run=RunSnapshot("run-a", "terminal", "completed", None, NOW))
    result = derive_observation(item, now=NOW)
    assert result.state == "completed"
    assert result.requires_reread


def test_contradictions_are_inconsistent_and_never_active():
    item = snapshot(task_status="done", run=RunSnapshot("run-a", "running", None, 1234, NOW))
    result = derive_observation(item, now=NOW)
    assert result.state == "inconsistent"
    assert result.safe_reason == "task-run-contradiction"


def test_terminal_candidate_requires_worktree_head_allowlist_and_tests():
    complete = snapshot(
        task_status="done",
        run=RunSnapshot("run-a", "terminal", "completed", None, NOW),
        runs=(RunSnapshot("run-a", "terminal", "completed", None, NOW),),
        tests_passed=True,
    )
    assert derive_observation(complete, now=NOW).integration_candidate
    escaped = snapshot(
        task_status="done",
        run=RunSnapshot("run-a", "terminal", "completed", None, NOW),
        diff_paths=(".env",),
        tests_passed=True,
    )
    result = derive_observation(escaped, now=NOW)
    assert result.state == "inconsistent"
    assert not result.integration_candidate


def test_degraded_needs_input_and_silent_no_change_event_policy():
    degraded = derive_observation(
        snapshot(diagnostics=(Diagnostic("warning", "creator-wake-unconfirmed"),)), now=NOW
    )
    assert degraded.state == "degraded"
    needs_input = derive_observation(snapshot(task_status="blocked"), now=NOW)
    assert needs_input.state == "needs-input"
    assert should_emit_event(None, degraded)
    assert not should_emit_event(degraded, degraded)
    assert should_emit_event(degraded, needs_input)


def test_structural_root_continuation_requires_all_parents_done_and_new_run():
    from agentporter.runtime_observation import derive_structural_continuation

    result = derive_structural_continuation(
        root_id="root",
        root_status="ready",
        expected_parent_ids=frozenset({"a", "b"}),
        actual_parent_statuses=(("a", "done"), ("b", "done")),
        previous_run_id="old",
        current_run_id="new",
        current_run_root_id="root",
        current_run_task_id="root",
    )
    assert result == "orchestrator-resumed"
    assert (
        derive_structural_continuation(
            root_status="blocked",
            parent_statuses=("done", "done"),
            previous_run_id="old",
            current_run_id="old",
        )
        == "event-durable"
    )
