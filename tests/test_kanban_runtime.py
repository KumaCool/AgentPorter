from dataclasses import dataclass, replace

from agentporter.dispatch_planning import NotificationRoute
from agentporter.kanban_runtime import (
    KanbanCapabilities,
    KanbanRuntime,
    PlannedMutation,
)


@dataclass
class FakeAdapter:
    revision: str = "rev-1"
    fail_at: str | None = None

    def __post_init__(self):
        self.calls = []
        self.tasks = {}
        self.subscriptions = {}

    def board_revision(self, board, tenant):
        self.calls.append(("revision", board, tenant))
        return self.revision

    def create_blocked(self, mutation):
        self.calls.append(("create", mutation.local_id))
        if self.fail_at == "create":
            raise RuntimeError("boom")
        task_id = f"task-{mutation.local_id}"
        self.tasks[task_id] = mutation
        return task_id

    def link(self, parent_id, child_id):
        self.calls.append(("link", parent_id, child_id))
        if self.fail_at == "link":
            raise RuntimeError("boom")

    def notify_subscribe(self, task_id, route):
        self.calls.append(("subscribe", task_id))
        if self.fail_at == "subscribe":
            raise RuntimeError("boom")
        self.subscriptions[task_id] = route

    def show_json(self, task_id):
        self.calls.append(("show", task_id))
        item = self.tasks[task_id]
        return {
            "id": task_id,
            "status": "blocked",
            "assignee": item.assignee,
            "session_id": item.creator_session,
            "workspace": item.workspace,
            "branch": item.branch,
            "base_sha": item.base_sha,
            "parents": list(item.parents),
            "idempotency_key": item.idempotency_key,
            "ownership_digest": item.ownership_digest,
            "board": item.board,
            "tenant": item.tenant,
        }

    def notify_list_json(self, task_id):
        self.calls.append(("notify-list", task_id))
        route = self.subscriptions[task_id]
        return [{
            "platform": route.platform,
            "chat_id": route.chat_id,
            "chat_type": route.chat_type,
            "thread_id": route.thread_id,
            "notifier_profile": route.notifier_profile,
            "delivery_metadata": dict(route.delivery_metadata),
        }]

    def unblock(self, task_id, expected_revision):
        self.calls.append(("unblock", task_id, expected_revision))
        if self.revision != expected_revision:
            raise RuntimeError("CAS board drift")

    def block(self, task_id, reason):
        self.calls.append(("block", task_id, reason))


def route():
    return NotificationRoute(
        "telegram", "secret-chat", "group", "secret-thread", "default",
        (("reply_anchor", "secret-anchor"),), "creator-session"
    )


def mutation(**changes):
    values = dict(
        local_id="child", board="board", tenant="tenant", assignee="worker-a",
        creator_session="session-secret", workspace="/worktree", branch="phase-e",
        base_sha="7cc1dad4e49aecfeadf4eb033802a5a990794c69", parents=("root-id",),
        idempotency_key="key-child", ownership_digest="ownership", route=route(),
        subscribe=True, runnable=True,
    )
    values.update(changes)
    return PlannedMutation(**values)


def test_unknown_assignee_and_unsupported_capability_make_zero_adapter_calls():
    adapter = FakeAdapter()
    runtime = KanbanRuntime(adapter, KanbanCapabilities.offline_contract())
    receipt = runtime.execute((mutation(assignee="missing"),), known_assignees={"worker-a"},
                              expected_revision="rev-1")
    assert receipt[0].status == "failed"
    assert receipt[0].safe_reason == "unknown-assignee"
    assert adapter.calls == []

    capabilities = replace(KanbanCapabilities.offline_contract(), delivery_metadata=False)
    unsupported = KanbanRuntime(adapter, capabilities)
    result = unsupported.execute((mutation(),), known_assignees={"worker-a"},
                                 expected_revision="rev-1")
    assert result[0].safe_reason == "unsupported-delivery-metadata"
    assert adapter.calls == []

    native = KanbanRuntime(adapter, KanbanCapabilities.v020())
    result = native.execute((mutation(),), known_assignees={"worker-a"},
                            expected_revision="rev-1")
    assert result[0].safe_reason in {
        "unsupported-delivery-metadata", "unsupported-cas-revision"
    }
    assert adapter.calls == []


def test_exact_order_readback_then_unblock_and_secret_safe_receipt():
    adapter = FakeAdapter()
    receipts = KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
        (mutation(),), known_assignees={"worker-a"}, expected_revision="rev-1"
    )
    assert [call[0] for call in adapter.calls] == [
        "revision", "create", "link", "subscribe", "show", "notify-list", "revision", "unblock"
    ]
    receipt = receipts[0]
    assert receipt.status == "succeeded"
    assert receipt.task_status == "ready"
    assert receipt.continuity_level == "event-durable"
    serialized = receipt.to_persisted_json()
    assert receipt.route_digest in serialized
    for secret in ("secret-chat", "secret-thread", "session-secret", "secret-anchor"):
        assert secret not in serialized


def test_partial_failure_keeps_card_blocked_and_records_failed_receipt():
    adapter = FakeAdapter(fail_at="subscribe")
    receipt = KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
        (mutation(),), known_assignees={"worker-a"}, expected_revision="rev-1"
    )[0]
    assert receipt.status == "failed"
    assert receipt.task_status == "blocked"
    assert any(call[0] == "block" for call in adapter.calls)
    assert not any(call[0] == "unblock" for call in adapter.calls)


def test_exact_subscription_mismatch_and_cas_drift_never_unblock():
    class Mismatch(FakeAdapter):
        def notify_list_json(self, task_id):
            value = super().notify_list_json(task_id)
            value[0]["thread_id"] = "wrong"
            return value

    adapter = Mismatch()
    receipt = KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
        (mutation(),), known_assignees={"worker-a"}, expected_revision="rev-1"
    )[0]
    assert receipt.safe_reason == "subscription-readback-mismatch"
    assert not any(call[0] == "unblock" for call in adapter.calls)

    class Drift(FakeAdapter):
        def notify_list_json(self, task_id):
            value = super().notify_list_json(task_id)
            self.revision = "rev-2"
            return value

    drift = Drift()
    receipt = KanbanRuntime(drift, KanbanCapabilities.offline_contract()).execute(
        (mutation(),), known_assignees={"worker-a"}, expected_revision="rev-1"
    )[0]
    assert receipt.safe_reason == "board-drift"
    assert not any(call[0] == "unblock" for call in drift.calls)


def test_cli_route_is_notification_only_not_creator_continuation():
    adapter = FakeAdapter()
    cli_route = replace(route(), source="cli")
    receipt = KanbanRuntime(adapter, KanbanCapabilities.offline_contract()).execute(
        (mutation(route=cli_route, creator_session=None),), known_assignees={"worker-a"},
        expected_revision="rev-1"
    )[0]
    assert receipt.continuity_level == "notification-only"
    assert not receipt.session_id_attached
