from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Generic, Protocol, TextIO, TypeVar, cast
from uuid import UUID

from .identity import COMPONENT_IDS, PRODUCT_ID
from .models import HermesProfileName, MarkerV1
from .uninstall_discovery import (
    MARKER_NAME,
    MAX_MARKER_BYTES,
    DiscoveryResult,
    DiscoveryStatus,
)

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
    root_device: int | None
    root_inode: int | None
    root_type: int | None
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
        root_device=None,
        root_inode=None,
        root_type=None,
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


def build_uninstall_plan(
    source: Sequence[UninstallCandidate] | DiscoveryResult,
) -> UninstallPlan:
    """Seal an already-discovered, exact AgentPorter installation collection."""
    root_device: int | None = None
    root_inode: int | None = None
    root_type: int | None = None
    if isinstance(source, DiscoveryResult):
        if (
            source.status is not DiscoveryStatus.READY
            or source.findings
            or source.hermes_home is None
            or source.profiles_root is None
            or source.root_identity is None
        ):
            return _invalid_plan()
        candidates = cast(Sequence[UninstallCandidate], source.targets)
        home = source.hermes_home
        root = source.profiles_root
        root_device = source.root_identity.device
        root_inode = source.root_identity.inode
        root_type = source.root_identity.mode_type
    else:
        candidates = source
        if not candidates:
            return _invalid_plan()
        home = candidates[0].hermes_home
        root = candidates[0].profiles_root
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
            (not isinstance(source, DiscoveryResult) and candidate.hermes_home != home)
            or (not isinstance(source, DiscoveryResult) and candidate.profiles_root != root)
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
        root_device=root_device,
        root_inode=root_inode,
        root_type=root_type,
        fingerprint="",
        confirmation_phrase=f"DELETE AGENTPORTER {installation_id[:8]}",
    )
    return replace(plan, fingerprint=_fingerprint(plan))


def _revalidation_supported() -> bool:
    return (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )


def _stat_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)


def _read_bounded_marker(marker_fd: int) -> bytes | None:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(marker_fd, min(65536, MAX_MARKER_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_MARKER_BYTES:
            return None


def revalidate_uninstall_collection(plan: UninstallPlan) -> bool:
    """Revalidate every sealed target without searching, renaming, or writing."""
    if (
        plan.status is not PlanStatus.READY
        or plan.hermes_home is None
        or plan.profiles_root is None
        or plan.root_device is None
        or plan.root_inode is None
        or plan.root_type != stat.S_IFDIR
        or plan.fingerprint != _fingerprint(replace(plan, fingerprint=""))
        or not _revalidation_supported()
        or not _is_canonical(plan.hermes_home)
        or not _is_canonical(plan.profiles_root)
        or plan.profiles_root != plan.hermes_home / "profiles"
        or plan.profiles_root.name != "profiles"
    ):
        return False

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        home_fd = os.open(plan.hermes_home, directory_flags)
    except OSError:
        return False
    try:
        root_before = os.stat("profiles", dir_fd=home_fd, follow_symlinks=False)
        if _stat_identity(root_before) != (
            plan.root_device,
            plan.root_inode,
            plan.root_type,
        ):
            return False
        root_fd = os.open("profiles", directory_flags, dir_fd=home_fd)
        try:
            if _stat_identity(os.fstat(root_fd)) != _stat_identity(root_before):
                return False
            for target in plan.targets:
                try:
                    HermesProfileName(target.current_name)
                except (TypeError, ValueError):
                    return False
                if target.path != plan.profiles_root / target.current_name:
                    return False
                profile_before = os.stat(
                    target.current_name, dir_fd=root_fd, follow_symlinks=False
                )
                if _stat_identity(profile_before) != (
                    target.profile_device,
                    target.profile_inode,
                    target.profile_type,
                ):
                    return False
                profile_fd = os.open(target.current_name, directory_flags, dir_fd=root_fd)
                try:
                    if _stat_identity(os.fstat(profile_fd)) != _stat_identity(profile_before):
                        return False
                    marker_before = os.stat(
                        MARKER_NAME, dir_fd=profile_fd, follow_symlinks=False
                    )
                    if _stat_identity(marker_before) != (
                        target.marker_device,
                        target.marker_inode,
                        target.marker_type,
                    ):
                        return False
                    marker_fd = os.open(
                        MARKER_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=profile_fd
                    )
                    try:
                        marker_opened = os.fstat(marker_fd)
                        if _stat_identity(marker_opened) != _stat_identity(marker_before):
                            return False
                        payload = _read_bounded_marker(marker_fd)
                        if (
                            payload is None
                            or hashlib.sha256(payload).hexdigest() != target.marker_sha256
                        ):
                            return False
                        marker = MarkerV1.model_validate_json(payload)
                        if (
                            marker.product_id != target.product_id
                            or marker.component_id != target.component_id
                            or marker.installation_id != target.installation_id
                        ):
                            return False
                        marker_after = os.stat(
                            MARKER_NAME, dir_fd=profile_fd, follow_symlinks=False
                        )
                        if _stat_identity(marker_after) != _stat_identity(marker_opened):
                            return False
                    finally:
                        os.close(marker_fd)
                    profile_after = os.stat(
                        target.current_name, dir_fd=root_fd, follow_symlinks=False
                    )
                    if _stat_identity(profile_after) != _stat_identity(profile_before):
                        return False
                finally:
                    os.close(profile_fd)
            root_after = os.stat("profiles", dir_fd=home_fd, follow_symlinks=False)
            return _stat_identity(root_after) == _stat_identity(root_before)
        finally:
            os.close(root_fd)
    except (OSError, ValueError):
        return False
    finally:
        os.close(home_fd)


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
