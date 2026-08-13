from dataclasses import replace
from datetime import timedelta

import pytest
from test_dispatch_planning import NOW, SHA, evidence, route, task
from test_kanban_runtime import FakeAdapter, mutation
from test_runtime_observation import snapshot

from agentporter.dispatch_application import DispatchApplication, plan_to_mutations
from agentporter.dispatch_planning import DispatchPlan
from agentporter.kanban_runtime import KanbanCapabilities, KanbanRuntime
from agentporter.runtime_observation import (
    Diagnostic,
    RunSnapshot,
    derive_observation,
    derive_structural_continuation,
)


def make_plan(*tasks, roots=("root",)):
    return DispatchPlan.create(
        board="board",
        tenant="tenant",
        creator_session="session-secret",
        route=route(),
        tasks=tasks,
        readiness=(evidence(),),
        now=NOW,
        expected_base_sha=SHA,
        expected_board_revision="rev-1",
        structural_roots=roots,
    )


def test_plan_graph_and_repr_are_closed_and_secret_safe():
    for bad_tasks, roots, message in (
        ((task(), task()), ("root",), "duplicate task"),
        ((task(parents=("child-a",)),), ("root",), "self-parent"),
        (
            (
                task(local_id="a", parents=("b",), idempotency_key="ka"),
                task(local_id="b", parents=("a",), idempotency_key="kb"),
            ),
            ("root",),
            "cycle",
        ),
        ((task(),), ("child-a",), "root overlap"),
        ((task(parents=()),), ("root",), "reachable"),
    ):
        with pytest.raises(ValueError, match=message):
            make_plan(*bad_tasks, roots=roots)
    plan = make_plan(task())
    shown = repr(plan)
    for secret in (
        "session-secret",
        "runtime-chat-secret",
        "runtime-thread-secret",
        "contract body",
        "/safe/worktree",
    ):
        assert secret not in shown


def test_plan_bridge_is_complete_and_v020_is_zero_mutation_fail_closed():
    plan = make_plan(task())
    mutations = plan_to_mutations(plan)
    assert mutations[0].local_id == "child-a"
    assert mutations[0].ownership_digest
    adapter = FakeAdapter()
    result = DispatchApplication(adapter, KanbanCapabilities.v020()).dispatch(
        plan, known_assignees={"worker-a"}
    )
    assert result[0].safe_reason.startswith("unsupported-")
    assert adapter.calls == []


class TransactionAdapter(FakeAdapter):
    def __post_init__(self):
        super().__post_init__()
        self.counter = 1

    def board_revision(self, board, tenant):
        self.calls.append(("revision", board, tenant))
        return f"rev-{self.counter}"

    def create_blocked(self, mutation, expected_revision):
        assert expected_revision == f"rev-{self.counter}"
        self.calls.append(("create", mutation.local_id, expected_revision))
        task_id = f"task-{mutation.local_id}"
        self.tasks[task_id] = mutation
        self.counter += 1
        return task_id, f"rev-{self.counter}"

    def lookup_by_idempotency(self, board, tenant, key):
        self.calls.append(("lookup", key))
        return None

    def link(self, parent_id, child_id, expected_revision):
        self.calls.append(("link", parent_id, child_id, expected_revision))
        self.counter += 1
        return f"rev-{self.counter}"

    def notify_subscribe(self, task_id, route, expected_revision):
        self.calls.append(("subscribe", task_id, expected_revision))
        self.subscriptions[task_id] = route
        self.counter += 1
        return f"rev-{self.counter}"

    def unblock(self, task_id, expected_revision):
        self.calls.append(("unblock", task_id, expected_revision))
        self.counter += 1
        return f"rev-{self.counter}"


def test_multicard_uses_global_phases_and_adapter_revision_tokens():
    adapter = TransactionAdapter()
    items = (
        mutation(local_id="a", idempotency_key="ka"),
        mutation(local_id="b", idempotency_key="kb"),
    )
    receipts = KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
        items, known_assignees={"worker-a"}, expected_revision="rev-1"
    )
    names = [call[0] for call in adapter.calls]
    assert names == [
        "revision",
        "lookup",
        "create",
        "lookup",
        "create",
        "link",
        "link",
        "subscribe",
        "subscribe",
        "show",
        "notify-list",
        "show",
        "notify-list",
        "unblock",
        "unblock",
    ]
    assert all(r.status == "succeeded" for r in receipts)
    assert (
        KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
            (), known_assignees=set(), expected_revision="rev-99"
        )
        == ()
    )


def test_baseexception_compensates_then_preserves_identity_without_leak():
    class Abort(TransactionAdapter):
        def link(self, parent_id, child_id, expected_revision):
            raise KeyboardInterrupt("raw-secret")

        def block(self, task_id, reason):
            self.calls.append(("block", task_id, reason))
            raise RuntimeError("compensation-secret")

    adapter = Abort()
    error = KeyboardInterrupt("raw-secret")
    adapter.link = lambda *_args: (_ for _ in ()).throw(error)
    with pytest.raises(KeyboardInterrupt) as caught:
        KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
            (mutation(),), known_assignees={"worker-a"}, expected_revision="rev-1"
        )
    assert caught.value is error
    assert any(c[0] == "block" and "secret" not in c[2] for c in adapter.calls)


def test_observation_rejects_noncurrent_evidence_and_requires_bound_integration():
    current = RunSnapshot("current", "running", None, 123, NOW - timedelta(seconds=1))
    old = RunSnapshot("old", "terminal", "completed", None, NOW)
    item = snapshot(
        current_run_id="current",
        runs=(old, current),
        run=old,
        workspace="/safe/worktree",
        base_sha=SHA,
        evidence_run_id="old",
        evidence_workspace="/safe/worktree",
        evidence_base_sha=SHA,
        tests_run_id="old",
        tests_passed=True,
    )
    result = derive_observation(item, now=NOW)
    assert result.state == "inconsistent" and not result.integration_candidate
    future = replace(
        item,
        run=current,
        evidence_run_id="current",
        tests_run_id="current",
        runs=(current,),
        current_run_id="current",
    )
    future = replace(future, run=replace(current, heartbeat_at=NOW + timedelta(seconds=1)))
    assert derive_observation(future, now=NOW).state == "stale-or-wedged"
    critical = replace(future, run=current, diagnostics=(Diagnostic("critical", "disk-corrupt"),))
    assert derive_observation(critical, now=NOW).state in {"degraded", "failed"}
    with pytest.raises(ValueError, match="allowed write"):
        derive_observation(replace(future, allowed_writes=("../escape",)), now=NOW)


def test_continuation_requires_exact_root_parent_and_new_run_identity():
    common = dict(
        root_id="root",
        root_status="ready",
        expected_parent_ids=frozenset({"a", "b"}),
        actual_parent_statuses=(("a", "done"), ("b", "done")),
        previous_run_id="old",
        current_run_id="new",
        current_run_root_id="root",
        current_run_task_id="root",
    )
    assert derive_structural_continuation(**common) == "orchestrator-resumed"
    assert (
        derive_structural_continuation(
            **(common | {"actual_parent_statuses": (("x", "done"), ("b", "done"))})
        )
        == "event-durable"
    )
    assert (
        derive_structural_continuation(**(common | {"current_run_root_id": "other"}))
        == "event-durable"
    )
