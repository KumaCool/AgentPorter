"""Fail-closed Kanban mutation orchestration through an injected public adapter."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from .dispatch_planning import NotificationRoute


@dataclass(frozen=True, slots=True)
class KanbanCapabilities:
    create_blocked: bool
    link: bool
    notify_subscribe: bool
    notify_list_json: bool
    delivery_metadata: bool
    task_readback: bool
    cas_revision: bool

    @classmethod
    def v020(cls) -> KanbanCapabilities:
        # Local v0.20 help proves create/link/subscribe/list/readback. It exposes neither an
        # exact delivery-metadata write surface nor a board-revision CAS surface, so formal
        # dispatch must fail closed rather than infer either capability.
        return cls(True, True, True, True, False, True, False)

    @classmethod
    def offline_contract(cls) -> KanbanCapabilities:
        """Synthetic complete capability set for injected-adapter contract tests only."""
        return cls(True, True, True, True, True, True, True)


@dataclass(frozen=True, slots=True)
class PlannedMutation:
    local_id: str
    board: str
    tenant: str
    assignee: str
    creator_session: str | None
    workspace: str
    branch: str | None
    base_sha: str
    parents: tuple[str, ...]
    idempotency_key: str
    ownership_digest: str
    route: NotificationRoute
    subscribe: bool
    runnable: bool


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    board: str
    tenant: str
    task_id: str | None
    task_status: Literal["blocked", "ready"]
    assignee: str
    session_id_attached: bool
    workspace_kind: str
    branch_name: str | None
    parents: tuple[str, ...]
    ownership_digest: str
    base_sha: str
    route_digest: str
    continuity_level: Literal["notification-only", "event-durable"]
    status: Literal["succeeded", "failed"]
    safe_reason: str

    def to_persisted_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class KanbanAdapter(Protocol):
    def board_revision(self, board: str, tenant: str) -> str: ...
    def create_blocked(self, mutation: PlannedMutation) -> str: ...
    def link(self, parent_id: str, child_id: str) -> None: ...
    def notify_subscribe(self, task_id: str, route: NotificationRoute) -> None: ...
    def show_json(self, task_id: str) -> dict[str, Any]: ...
    def notify_list_json(self, task_id: str) -> list[dict[str, Any]]: ...
    def unblock(self, task_id: str, expected_revision: str) -> None: ...
    def block(self, task_id: str, reason: str) -> None: ...


class _DispatchFailure(Exception):
    pass


def _workspace_kind(value: str) -> str:
    return "worktree" if "worktree" in value else "dir"


def _receipt(
    item: PlannedMutation,
    *,
    task_id: str | None,
    succeeded: bool,
    reason: str,
) -> DispatchReceipt:
    continuation: Literal["notification-only", "event-durable"] = (
        "event-durable" if item.route.source == "creator-session" else "notification-only"
    )
    return DispatchReceipt(
        item.board,
        item.tenant,
        task_id,
        "ready" if succeeded else "blocked",
        item.assignee,
        item.creator_session is not None,
        _workspace_kind(item.workspace),
        item.branch,
        item.parents,
        item.ownership_digest,
        item.base_sha,
        item.route.digest(),
        continuation,
        "succeeded" if succeeded else "failed",
        reason,
    )


def _route_matches(expected: NotificationRoute, actual: dict[str, Any]) -> bool:
    return (
        actual.get("platform") == expected.platform
        and actual.get("chat_id") == expected.chat_id
        and actual.get("chat_type") == expected.chat_type
        and actual.get("thread_id") == expected.thread_id
        and actual.get("notifier_profile") == expected.notifier_profile
        and actual.get("delivery_metadata") == dict(expected.delivery_metadata)
    )


def _task_matches(item: PlannedMutation, task_id: str, actual: dict[str, Any]) -> bool:
    return actual == {
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


class KanbanRuntime:
    def __init__(self, adapter: KanbanAdapter, capabilities: KanbanCapabilities) -> None:
        self._adapter = adapter
        self._capabilities = capabilities

    def execute(
        self,
        mutations: tuple[PlannedMutation, ...],
        *,
        known_assignees: set[str],
        expected_revision: str,
    ) -> tuple[DispatchReceipt, ...]:
        unsupported = self._unsupported_reason(mutations)
        if unsupported:
            return tuple(
                _receipt(item, task_id=None, succeeded=False, reason=unsupported)
                for item in mutations
            )
        unknown = next((item for item in mutations if item.assignee not in known_assignees), None)
        if unknown is not None:
            return tuple(
                _receipt(item, task_id=None, succeeded=False, reason="unknown-assignee")
                for item in mutations
            )
        actual_revision = self._adapter.board_revision(mutations[0].board, mutations[0].tenant)
        if actual_revision != expected_revision:
            return tuple(
                _receipt(item, task_id=None, succeeded=False, reason="board-drift")
                for item in mutations
            )
        receipts: list[DispatchReceipt] = []
        for item in mutations:
            task_id: str | None = None
            try:
                task_id = self._adapter.create_blocked(item)
                for parent in item.parents:
                    self._adapter.link(parent, task_id)
                if item.subscribe:
                    self._adapter.notify_subscribe(task_id, item.route)
                if not _task_matches(item, task_id, self._adapter.show_json(task_id)):
                    raise _DispatchFailure("task-readback-mismatch")
                if item.subscribe:
                    subscriptions = self._adapter.notify_list_json(task_id)
                    if len(subscriptions) != 1 or not _route_matches(item.route, subscriptions[0]):
                        raise _DispatchFailure("subscription-readback-mismatch")
                if self._adapter.board_revision(item.board, item.tenant) != expected_revision:
                    raise _DispatchFailure("board-drift")
                if item.runnable:
                    self._adapter.unblock(task_id, expected_revision)
                receipts.append(_receipt(item, task_id=task_id, succeeded=True, reason="verified"))
            except _DispatchFailure as exc:
                if task_id is not None:
                    self._adapter.block(task_id, str(exc))
                receipts.append(_receipt(item, task_id=task_id, succeeded=False, reason=str(exc)))
            except Exception:
                if task_id is not None:
                    self._adapter.block(task_id, "dispatch-step-failed")
                receipts.append(
                    _receipt(item, task_id=task_id, succeeded=False, reason="dispatch-step-failed")
                )
        return tuple(receipts)

    def _unsupported_reason(self, mutations: tuple[PlannedMutation, ...]) -> str | None:
        needed = {
            "create-blocked": self._capabilities.create_blocked,
            "link": self._capabilities.link,
            "notify-subscribe": self._capabilities.notify_subscribe,
            "notify-list-json": self._capabilities.notify_list_json,
            "task-readback": self._capabilities.task_readback,
            "cas-revision": self._capabilities.cas_revision,
        }
        if any(item.route.delivery_metadata for item in mutations):
            needed["delivery-metadata"] = self._capabilities.delivery_metadata
        missing = next((name for name, supported in needed.items() if not supported), None)
        return f"unsupported-{missing}" if missing else None
