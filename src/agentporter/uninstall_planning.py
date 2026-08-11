from __future__ import annotations

import hashlib
import json
import re
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Generic, Protocol, TextIO, TypeVar
from uuid import UUID

from .identity import COMPONENT_IDS, PRODUCT_ID
from .models import HermesProfileName

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")


class PlanStatus(StrEnum):
    READY = "ready"
    INVALID = "invalid"


class InteractionStatus(StrEnum):
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    STALE = "stale"


class UninstallCandidate(Protocol):
    @property
    def current_name(self) -> str: ...

    @property
    def path(self) -> Path: ...

    @property
    def product_id(self) -> str: ...

    @property
    def component_id(self) -> str: ...

    @property
    def installation_id(self) -> str: ...

    @property
    def profile_device(self) -> int: ...

    @property
    def profile_inode(self) -> int: ...

    @property
    def profile_type(self) -> int: ...

    @property
    def marker_device(self) -> int: ...

    @property
    def marker_inode(self) -> int: ...

    @property
    def marker_type(self) -> int: ...

    @property
    def marker_sha256(self) -> str: ...

    @property
    def hermes_home(self) -> Path: ...

    @property
    def profiles_root(self) -> Path: ...


@dataclass(frozen=True)
class TargetSnapshot:
    current_name: str
    path: Path
    product_id: str
    component_id: str
    installation_id: str
    profile_device: int
    profile_inode: int
    profile_type: int
    marker_device: int
    marker_inode: int
    marker_type: int
    marker_sha256: str = field(repr=False)


@dataclass(frozen=True)
class UninstallPlan:
    status: PlanStatus
    hermes_home: Path | None
    profiles_root: Path | None
    installation_id: str | None
    targets: tuple[TargetSnapshot, ...]
    fingerprint: str = field(repr=False)
    confirmation_phrase: str | None = field(repr=False)


@dataclass(frozen=True)
class InteractionOutcome(Generic[_T]):
    status: InteractionStatus
    detail: str | None = None
    continuation_result: _T | None = None


def _canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _is_canonical(path: Path) -> bool:
    return path.is_absolute() and path == path.resolve(strict=False)


def _invalid_plan() -> UninstallPlan:
    return UninstallPlan(
        status=PlanStatus.INVALID,
        hermes_home=None,
        profiles_root=None,
        installation_id=None,
        targets=(),
        fingerprint="",
        confirmation_phrase=None,
    )


def _snapshot(candidate: UninstallCandidate) -> TargetSnapshot:
    return TargetSnapshot(
        current_name=candidate.current_name,
        path=candidate.path,
        product_id=candidate.product_id,
        component_id=candidate.component_id,
        installation_id=candidate.installation_id,
        profile_device=candidate.profile_device,
        profile_inode=candidate.profile_inode,
        profile_type=candidate.profile_type,
        marker_device=candidate.marker_device,
        marker_inode=candidate.marker_inode,
        marker_type=candidate.marker_type,
        marker_sha256=candidate.marker_sha256,
    )


def _fingerprint(plan: UninstallPlan) -> str:
    payload = asdict(plan)
    payload.pop("fingerprint")
    payload.pop("confirmation_phrase")
    canonical = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_uninstall_plan(candidates: Sequence[UninstallCandidate]) -> UninstallPlan:
    """Seal an already-discovered, exact AgentPorter installation collection."""
    if len(candidates) != len(COMPONENT_IDS):
        return _invalid_plan()

    expected = tuple(COMPONENT_IDS.values())
    by_component: dict[str, UninstallCandidate] = {}
    for candidate in candidates:
        if candidate.component_id in by_component:
            return _invalid_plan()
        by_component[candidate.component_id] = candidate
    if set(by_component) != set(expected):
        return _invalid_plan()

    ordered = tuple(by_component[component_id] for component_id in expected)
    first = ordered[0]
    home = first.hermes_home
    root = first.profiles_root
    installation_id = first.installation_id
    if (
        not _is_canonical(home)
        or not _is_canonical(root)
        or root != home / "profiles"
        or not _canonical_uuid(installation_id)
    ):
        return _invalid_plan()

    for candidate in ordered:
        try:
            HermesProfileName(candidate.current_name)
        except (TypeError, ValueError):
            return _invalid_plan()
        if (
            candidate.hermes_home != home
            or candidate.profiles_root != root
            or candidate.path != root / candidate.current_name
            or candidate.path.parent != root
            or not _is_canonical(candidate.path)
            or candidate.product_id != PRODUCT_ID
            or candidate.installation_id != installation_id
            or not _canonical_uuid(candidate.product_id)
            or not _canonical_uuid(candidate.component_id)
            or stat.S_IFMT(candidate.profile_type) != stat.S_IFDIR
            or stat.S_IFMT(candidate.marker_type) != stat.S_IFREG
            or _SHA256.fullmatch(candidate.marker_sha256) is None
        ):
            return _invalid_plan()

    plan = UninstallPlan(
        status=PlanStatus.READY,
        hermes_home=home,
        profiles_root=root,
        installation_id=installation_id,
        targets=tuple(_snapshot(candidate) for candidate in ordered),
        fingerprint="",
        confirmation_phrase=f"DELETE AGENTPORTER {installation_id[:8]}",
    )
    return replace(plan, fingerprint=_fingerprint(plan))


def render_uninstall_plan(plan: UninstallPlan) -> str:
    if plan.status is not PlanStatus.READY or plan.installation_id is None:
        raise ValueError("only a ready uninstall plan can be rendered")
    lines = [
        "AgentPorter uninstall plan (explicit allowlist):",
        f"Installation ID: {plan.installation_id}",
    ]
    for target in plan.targets:
        lines.extend(
            (
                f"- Current name: {target.current_name}",
                f"  Authoritative path: {target.path}",
                f"  Component: {target.component_id}",
            )
        )
    lines.extend(
        (
            "",
            "WARNING: Each listed Profile will be permanently deleted in its entirety.",
            "This includes user-added config, SOUL, .env, auth.json, memories, sessions,",
            "skills, cron, MCP, logs, state databases, and all other Profile-local files.",
            "Do not concurrently rename/replace either Profile during uninstall.",
        )
    )
    return "\n".join(lines)


def run_uninstall_confirmation(
    plan: UninstallPlan,
    *,
    revalidate_collection: Callable[[UninstallPlan], bool],
    continuation: Callable[[], _T],
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
) -> InteractionOutcome[_T]:
    """Confirm once, then apply the collection-wide zero-deletion revalidation gate."""
    if (
        plan.status is not PlanStatus.READY
        or plan.confirmation_phrase is None
        or plan.fingerprint != _fingerprint(replace(plan, fingerprint=""))
    ):
        return InteractionOutcome(status=InteractionStatus.REJECTED)

    print(render_uninstall_plan(plan), file=output)
    try:
        answer = input_fn(f"Type {plan.confirmation_phrase} to confirm: ")
    except (EOFError, KeyboardInterrupt):
        return InteractionOutcome(status=InteractionStatus.CANCELLED)
    if answer != plan.confirmation_phrase:
        return InteractionOutcome(status=InteractionStatus.REJECTED)
    if not revalidate_collection(plan):
        return InteractionOutcome(
            status=InteractionStatus.STALE,
            detail="marker-changed/unsafe-path",
        )
    return InteractionOutcome(
        status=InteractionStatus.CONFIRMED,
        continuation_result=continuation(),
    )
