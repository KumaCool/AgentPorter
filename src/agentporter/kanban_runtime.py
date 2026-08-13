"""Fail-closed staged Kanban mutation orchestration through an injected adapter."""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, cast

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
        return cls(True, True, True, True, False, True, False)

    @classmethod
    def offline_contract(cls) -> KanbanCapabilities:
        return cls(True, True, True, True, True, True, True)


@dataclass(frozen=True, slots=True, repr=False)
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
    def create_blocked(
        self, mutation: PlannedMutation, expected_revision: str
    ) -> tuple[str, str]: ...
    def lookup_by_idempotency(self, board: str, tenant: str, key: str) -> str | None: ...
    def link(self, parent_id: str, child_id: str, expected_revision: str) -> str: ...
    def notify_subscribe(
        self, task_id: str, route: NotificationRoute, expected_revision: str
    ) -> str: ...
    def show_json(self, task_id: str) -> dict[str, Any]: ...
    def notify_list_json(self, task_id: str) -> list[dict[str, Any]]: ...
    def unblock(self, task_id: str, expected_revision: str) -> str: ...
    def block(self, task_id: str, reason: str) -> None: ...


class _DispatchFailure(Exception):
    pass


def _workspace_kind(value: str) -> str:
    return "worktree" if "worktree" in value else "dir"


def _receipt(
    item: PlannedMutation, *, task_id: str | None, succeeded: bool, reason: str
) -> DispatchReceipt:
    continuity: Literal["notification-only", "event-durable"] = (
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
        continuity,
        "succeeded" if succeeded else "failed",
        reason,
    )


def _route_matches(expected: NotificationRoute, actual: dict[str, Any]) -> bool:
    return all(
        (
            actual.get("platform") == expected.platform,
            actual.get("chat_id") == expected.chat_id,
            actual.get("chat_type") == expected.chat_type,
            actual.get("thread_id") == expected.thread_id,
            actual.get("notifier_profile") == expected.notifier_profile,
            actual.get("delivery_metadata") == dict(expected.delivery_metadata),
        )
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

    def _next_revision(self, item: PlannedMutation) -> str:
        return self._adapter.board_revision(item.board, item.tenant)

    def _create(self, item: PlannedMutation, revision: str) -> tuple[str, str]:
        method = cast(Any, self._adapter.create_blocked)
        try:
            value = method(item, revision)
        except TypeError:
            return cast(str, method(item)), self._next_revision(item)
        if not isinstance(value, tuple) or len(cast(tuple[object, ...], value)) != 2:
            raise _DispatchFailure("invalid-revision-token")
        return cast(tuple[str, str], value)

    def _mutate(self, name: str, item: PlannedMutation, revision: str, *args: object) -> str:
        method: Any = getattr(self._adapter, name)
        try:
            value = method(*args, revision)
        except TypeError:
            method(*args)
            return self._next_revision(item)
        if not isinstance(value, str) or not value:
            raise _DispatchFailure("invalid-revision-token")
        return value

    def _lookup(self, item: PlannedMutation) -> str | None:
        method = getattr(self._adapter, "lookup_by_idempotency", None)
        if method is None:
            return None
        return cast(str | None, method(item.board, item.tenant, item.idempotency_key))

    def _compensate(self, task_ids: list[str]) -> None:
        for task_id in task_ids:
            with contextlib.suppress(BaseException):
                self._adapter.block(task_id, "dispatch-transaction-failed")

    def execute(
        self,
        mutations: tuple[PlannedMutation, ...],
        *,
        known_assignees: set[str],
        expected_revision: str,
    ) -> tuple[DispatchReceipt, ...]:
        if not mutations:
            return ()
        unsupported = self._unsupported_reason(mutations)
        if unsupported:
            return tuple(
                _receipt(item, task_id=None, succeeded=False, reason=unsupported)
                for item in mutations
            )
        if any(item.assignee not in known_assignees for item in mutations):
            return tuple(
                _receipt(item, task_id=None, succeeded=False, reason="unknown-assignee")
                for item in mutations
            )
        if (
            self._adapter.board_revision(mutations[0].board, mutations[0].tenant)
            != expected_revision
        ):
            return tuple(
                _receipt(item, task_id=None, succeeded=False, reason="board-drift")
                for item in mutations
            )

        task_ids: list[str] = []
        revision = expected_revision
        try:
            # Global transaction phases: create/reuse, link, subscribe, readback, CAS-unblock.
            for item in mutations:
                existing = self._lookup(item)
                if existing is None:
                    task_id, revision = self._create(item, revision)
                else:
                    task_id = existing
                    if not _task_matches(item, task_id, self._adapter.show_json(task_id)):
                        raise _DispatchFailure("idempotency-readback-mismatch")
                task_ids.append(task_id)
            for item, task_id in zip(mutations, task_ids, strict=True):
                for parent in item.parents:
                    revision = self._mutate("link", item, revision, parent, task_id)
            for item, task_id in zip(mutations, task_ids, strict=True):
                if item.subscribe:
                    revision = self._mutate("notify_subscribe", item, revision, task_id, item.route)
            for item, task_id in zip(mutations, task_ids, strict=True):
                if not _task_matches(item, task_id, self._adapter.show_json(task_id)):
                    raise _DispatchFailure("task-readback-mismatch")
                if item.subscribe:
                    subscriptions = self._adapter.notify_list_json(task_id)
                    if len(subscriptions) != 1 or not _route_matches(item.route, subscriptions[0]):
                        raise _DispatchFailure("subscription-readback-mismatch")
            for item, task_id in zip(mutations, task_ids, strict=True):
                if item.runnable:
                    revision = self._mutate("unblock", item, revision, task_id)
            return tuple(
                _receipt(item, task_id=task_id, succeeded=True, reason="verified")
                for item, task_id in zip(mutations, task_ids, strict=True)
            )
        except BaseException as exc:
            self._compensate(task_ids)
            if not isinstance(exc, Exception):
                raise
            reason = (
                str(exc)
                if isinstance(exc, _DispatchFailure)
                else ("board-drift" if "CAS board drift" in str(exc) else "dispatch-step-failed")
            )
            return tuple(
                _receipt(
                    item,
                    task_id=task_ids[index] if index < len(task_ids) else None,
                    succeeded=False,
                    reason=reason,
                )
                for index, item in enumerate(mutations)
            )

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
