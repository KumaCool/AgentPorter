"""Immutable, secret-safe planning for staged Kanban dispatch."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

from .delegation_contract import DelegationContract, validate_delegation_contracts
from .readiness import ReadinessEvidence

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    kind: Literal["scratch", "worktree", "dir"]
    path: str
    branch: str | None
    base_sha: str

    def __post_init__(self) -> None:
        if not self.path or _SHA.fullmatch(self.base_sha) is None:
            raise ValueError("workspace path and base SHA are required")
        if self.kind == "worktree" and not self.branch:
            raise ValueError("worktree branch is required")


@dataclass(frozen=True, slots=True)
class NotificationRoute:
    platform: str
    chat_id: str
    chat_type: str
    thread_id: str | None
    notifier_profile: str
    delivery_metadata: tuple[tuple[str, str], ...]
    source: Literal["creator-session", "cli"]

    def __post_init__(self) -> None:
        if not all((self.platform, self.chat_id, self.chat_type, self.notifier_profile)):
            raise ValueError("notification route is incomplete")

    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class TaskSpec:
    local_id: str
    title: str
    body: str
    assignee: str
    component_id: str
    profile: str
    model: str
    provider: str
    config_digest: str
    hermes_version: str
    binding_fingerprint: str
    workspace: WorkspaceBinding
    parents: tuple[str, ...]
    idempotency_key: str
    contract: DelegationContract
    subscribe: bool
    initial_status: Literal["blocked"] = field(default="blocked", init=False)

    def __post_init__(self) -> None:
        required = (
            self.local_id, self.title, self.body, self.assignee, self.component_id,
            self.profile, self.model, self.provider, self.config_digest,
            self.hermes_version, self.binding_fingerprint, self.idempotency_key,
        )
        if not all(item.strip() for item in required):
            raise ValueError("task authority fields must be non-empty")
        if self.contract.base_sha != self.workspace.base_sha:
            raise ValueError("contract and workspace base SHA differ")


@dataclass(frozen=True, slots=True)
class DispatchPlan:
    board: str
    tenant: str
    creator_session: str
    route: NotificationRoute
    tasks: tuple[TaskSpec, ...]
    board_revision: str
    structural_roots: tuple[str, ...]
    fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        board: str,
        tenant: str,
        creator_session: str,
        route: NotificationRoute,
        tasks: tuple[TaskSpec, ...],
        readiness: tuple[ReadinessEvidence, ...],
        now: datetime,
        expected_base_sha: str,
        expected_board_revision: str,
        structural_roots: tuple[str, ...] = (),
    ) -> DispatchPlan:
        if not all((board, tenant, creator_session, expected_board_revision)):
            raise ValueError("board, tenant, creator session and revision are required")
        if route.source == "creator-session" and not creator_session:
            raise ValueError("creator session route is unbound")
        evidence_by_component = {item.binding.component_id: item for item in readiness}
        if len(evidence_by_component) != len(readiness):
            raise ValueError("duplicate readiness evidence")
        ids = {item.local_id for item in tasks}
        keys = [item.idempotency_key for item in tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate idempotency key")
        known_parents = ids | set(structural_roots)
        for item in tasks:
            if item.workspace.base_sha != expected_base_sha:
                raise ValueError("unexpected base SHA")
            if any(parent not in known_parents for parent in item.parents):
                raise ValueError("unbound parent")
            evidence = evidence_by_component.get(item.component_id)
            if evidence is None or evidence.status != "runtime-ready":
                raise ValueError("assignee lacks runtime-ready evidence")
            binding = evidence.binding
            checks = (
                (item.assignee == item.profile == binding.current_profile_name, "assignee/profile"),
                (item.model == binding.expected_model, "model"),
                (item.provider == binding.expected_provider, "provider"),
                (item.config_digest == binding.config_digest, "config"),
                (item.hermes_version == evidence.hermes_version, "Hermes"),
                (item.binding_fingerprint == binding.binding_fingerprint, "fingerprint"),
                (evidence.is_fresh(now), "fresh"),
            )
            for valid, name in checks:
                if not valid:
                    raise ValueError(f"{name} readiness mismatch")
        validate_delegation_contracts([item.contract for item in tasks])
        safe = {
            "board": board,
            "tenant": tenant,
            "creator_session_present": True,
            "route_digest": route.digest(),
            "board_revision": expected_board_revision,
            "roots": structural_roots,
            "tasks": [
                {
                    "id": item.local_id,
                    "assignee": item.assignee,
                    "component": item.component_id,
                    "workspace": asdict(item.workspace),
                    "parents": item.parents,
                    "idempotency_key": item.idempotency_key,
                    "writes": item.contract.writes,
                }
                for item in tasks
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(
            board, tenant, creator_session, route, tasks, expected_board_revision,
            structural_roots, fingerprint,
        )
