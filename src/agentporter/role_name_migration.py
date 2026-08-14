"""Recoverable collection transaction for Hermes-native role-name migration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from .execution import CommandOutcome, CommandStatus
from .role_identity_compat import (
    CURRENT_INITIAL_NAMES,
    LEGACY_INITIAL_NAMES,
    project_discovery_roles,
)
from .uninstall_discovery import DiscoveryResult, DiscoveryStatus, Target

MAX_JOURNAL_BYTES: Final = 64 * 1024


class MigrationStatus(StrEnum):
    CURRENT = "role-identity-current"
    MIGRATION_REQUIRED = "legacy-name-migration-required"
    RECOVERY_REQUIRED = "migration-recovery-required"
    AMBIGUOUS = "migration-state-ambiguous"
    CONFLICT = "name-conflict"
    COMPLETE = "complete"
    COMPENSATED = "compensated"
    FAILED = "failed"
    COMPENSATION_INCOMPLETE = "compensation-incomplete"
    CANCELLED = "cancelled"


class MigrationAction(StrEnum):
    APPLY = "apply"
    CONTINUE = "continue"
    ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class MigrationItem:
    portable_id: str
    component_id: str
    current_name: str
    target_name: str
    installation_id: str
    profile_device: int
    profile_inode: int
    marker_device: int
    marker_inode: int
    marker_sha256: str


@dataclass(frozen=True, slots=True)
class RoleNameMigrationPlan:
    status: MigrationStatus
    profiles_root: Path
    journal_path: Path
    installation_id: str | None
    items: tuple[MigrationItem, ...]
    completed: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    status: MigrationStatus
    completed: tuple[str, ...] = ()
    residue: tuple[str, ...] = ()
    journal_residue: bool = False


Rename = Callable[[str, str], CommandOutcome]
Rediscover = Callable[[], DiscoveryResult]


def _item(role: str, target: Target, target_name: str) -> MigrationItem:
    return MigrationItem(
        role,
        target.component_id,
        target.current_name,
        target_name,
        target.installation_id,
        target.profile_device,
        target.profile_inode,
        target.marker_device,
        target.marker_inode,
        target.marker_sha256,
    )


def _payload(plan: RoleNameMigrationPlan, completed: tuple[str, ...]) -> dict[str, object]:
    return {
        "schema": 1,
        "installation_id": plan.installation_id,
        "profiles_root": str(plan.profiles_root),
        "items": [asdict(item) for item in plan.items],
        "completed": list(completed),
    }


def _encoded(payload: Mapping[str, object]) -> bytes:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    envelope = {
        "payload": payload,
        "payload_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    return (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.next")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_journal(path: Path) -> dict[str, object] | None:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > MAX_JOURNAL_BYTES
        ):
            return None
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65536):
                chunks.append(chunk)
                if sum(map(len, chunks)) > MAX_JOURNAL_BYTES:
                    return None
        finally:
            os.close(descriptor)
        after = path.lstat()
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (
            after.st_dev,
            after.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            return None
        document = cast(object, json.loads(b"".join(chunks)))
        if not isinstance(document, dict):
            return None
        untyped_document = cast(dict[object, object], document)
        if set(untyped_document) != {"payload", "payload_sha256"}:
            return None
        raw = cast(dict[str, object], untyped_document)
        payload = raw["payload"]
        if not isinstance(payload, dict):
            return None
        typed = cast(dict[str, object], payload)
        canonical = json.dumps(typed, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != raw["payload_sha256"]:
            return None
        return typed
    except (OSError, ValueError, TypeError):
        return None


def _fingerprint(
    status: MigrationStatus,
    root: Path,
    installation_id: str | None,
    items: tuple[MigrationItem, ...],
    completed: tuple[str, ...],
) -> str:
    value = {
        "status": status,
        "root": str(root),
        "installation_id": installation_id,
        "items": [asdict(item) for item in items],
        "completed": completed,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _plan(
    status: MigrationStatus,
    root: Path,
    journal: Path,
    installation_id: str | None,
    items: tuple[MigrationItem, ...] = (),
    completed: tuple[str, ...] = (),
) -> RoleNameMigrationPlan:
    return RoleNameMigrationPlan(
        status,
        root,
        journal,
        installation_id,
        items,
        completed,
        _fingerprint(status, root, installation_id, items, completed),
    )


def _target_map(discovery: DiscoveryResult) -> dict[str, Target]:
    return {target.component_id: target for target in discovery.targets}


def _journal_recovery(
    discovery: DiscoveryResult, journal_path: Path, payload: dict[str, object]
) -> RoleNameMigrationPlan | None:
    try:
        if (
            set(payload)
            != {
                "schema",
                "installation_id",
                "profiles_root",
                "items",
                "completed",
            }
            or payload["schema"] != 1
        ):
            return None
        if payload["profiles_root"] != str(discovery.profiles_root):
            return None
        installation_id = payload["installation_id"]
        if not isinstance(installation_id, str):
            return None
        raw_items = payload["items"]
        raw_completed = payload["completed"]
        if not isinstance(raw_items, list) or not isinstance(raw_completed, list):
            return None
        items_list: list[MigrationItem] = []
        for value in cast(list[object], raw_items):
            if not isinstance(value, dict):
                return None
            item = cast(dict[object, object], value)
            strings = (
                "portable_id",
                "component_id",
                "current_name",
                "target_name",
                "installation_id",
                "marker_sha256",
            )
            integers = (
                "profile_device",
                "profile_inode",
                "marker_device",
                "marker_inode",
            )
            if any(not isinstance(item.get(key), str) for key in strings) or any(
                not isinstance(item.get(key), int) for key in integers
            ):
                return None
            items_list.append(
                MigrationItem(
                    cast(str, item["portable_id"]),
                    cast(str, item["component_id"]),
                    cast(str, item["current_name"]),
                    cast(str, item["target_name"]),
                    cast(str, item["installation_id"]),
                    cast(int, item["profile_device"]),
                    cast(int, item["profile_inode"]),
                    cast(int, item["marker_device"]),
                    cast(int, item["marker_inode"]),
                    cast(str, item["marker_sha256"]),
                )
            )
        if any(not isinstance(value, str) for value in cast(list[object], raw_completed)):
            return None
        items = tuple(items_list)
        completed = tuple(cast(list[str], raw_completed))
    except (TypeError, ValueError):
        return None
    if not items or any(item.installation_id != installation_id for item in items):
        return None
    targets = _target_map(discovery)
    if {target.installation_id for target in discovery.targets} != {installation_id}:
        return None
    for item in items:
        target = targets.get(item.component_id)
        if target is None:
            return None
        expected_name = item.target_name if item.portable_id in completed else item.current_name
        if target.current_name != expected_name:
            return None
        if (
            target.profile_device != item.profile_device
            or target.profile_inode != item.profile_inode
            or target.marker_device != item.marker_device
            or target.marker_inode != item.marker_inode
            or target.marker_sha256 != item.marker_sha256
        ):
            return None
    return _plan(
        MigrationStatus.RECOVERY_REQUIRED,
        cast(Path, discovery.profiles_root),
        journal_path,
        installation_id,
        items,
        completed,
    )


def build_role_name_migration_plan(
    discovery: DiscoveryResult, journal_path: Path
) -> RoleNameMigrationPlan:
    root = discovery.profiles_root or journal_path.parent
    if discovery.status is not DiscoveryStatus.READY:
        return _plan(MigrationStatus.AMBIGUOUS, root, journal_path, None)
    try:
        projections = project_discovery_roles(discovery)
    except ValueError:
        return _plan(MigrationStatus.AMBIGUOUS, root, journal_path, None)
    installation_id = projections[0].installation_id
    journal = _read_journal(journal_path) if journal_path.exists() else None
    if journal is not None:
        recovery = _journal_recovery(discovery, journal_path, journal)
        if recovery is not None:
            return recovery
        return _plan(MigrationStatus.AMBIGUOUS, root, journal_path, installation_id)
    targets = _target_map(discovery)
    names = {projection.current_profile_name for projection in projections}
    has_old = False
    has_new = False
    items: list[MigrationItem] = []
    for projection in projections:
        role = projection.portable_id
        old_name = LEGACY_INITIAL_NAMES[role]
        new_name = CURRENT_INITIAL_NAMES[role]
        if old_name != new_name and projection.current_profile_name == old_name:
            has_old = True
            items.append(_item(role, targets[projection.component_id], new_name))
        elif old_name != new_name and projection.current_profile_name == new_name:
            has_new = True
    if has_old and has_new:
        return _plan(MigrationStatus.AMBIGUOUS, root, journal_path, installation_id)
    if not items:
        return _plan(MigrationStatus.CURRENT, root, journal_path, installation_id)
    for item in items:
        if (
            item.target_name in names
            or (root / item.target_name).exists()
            or (root / item.target_name).is_symlink()
        ):
            return _plan(MigrationStatus.CONFLICT, root, journal_path, installation_id)
    return _plan(
        MigrationStatus.MIGRATION_REQUIRED,
        root,
        journal_path,
        installation_id,
        tuple(items),
    )


def _matches(item: MigrationItem, target: Target, name: str) -> bool:
    return (
        target.current_name == name
        and target.installation_id == item.installation_id
        and target.component_id == item.component_id
        and target.profile_device == item.profile_device
        and target.profile_inode == item.profile_inode
        and target.marker_device == item.marker_device
        and target.marker_inode == item.marker_inode
        and target.marker_sha256 == item.marker_sha256
    )


def _bound(discovery: DiscoveryResult, item: MigrationItem, name: str) -> bool:
    if discovery.status is not DiscoveryStatus.READY:
        return False
    target = _target_map(discovery).get(item.component_id)
    return target is not None and _matches(item, target, name)


def _unlink_private(path: Path) -> bool:
    try:
        path.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    except OSError:
        return False


def _complete_old_collection(discovery: DiscoveryResult, plan: RoleNameMigrationPlan) -> bool:
    return all(_bound(discovery, item, item.current_name) for item in plan.items)


def execute_role_name_migration(
    plan: RoleNameMigrationPlan,
    *,
    rename: Rename,
    rediscover: Rediscover,
    action: MigrationAction = MigrationAction.APPLY,
    compensate_on_failure: bool = True,
) -> MigrationResult:
    if plan.status not in {MigrationStatus.MIGRATION_REQUIRED, MigrationStatus.RECOVERY_REQUIRED}:
        return MigrationResult(plan.status)
    if plan.status is MigrationStatus.MIGRATION_REQUIRED and action is not MigrationAction.APPLY:
        return MigrationResult(MigrationStatus.AMBIGUOUS)
    if plan.status is MigrationStatus.RECOVERY_REQUIRED and action is MigrationAction.APPLY:
        return MigrationResult(MigrationStatus.AMBIGUOUS)

    completed = list(plan.completed)
    if action is MigrationAction.ROLLBACK:
        for item in reversed(plan.items):
            if item.portable_id not in completed:
                continue
            if not _bound(rediscover(), item, item.target_name):
                return MigrationResult(
                    MigrationStatus.COMPENSATION_INCOMPLETE,
                    tuple(completed),
                    (item.portable_id,),
                    True,
                )
            outcome = rename(item.target_name, item.current_name)
            observed = rediscover()
            if not _bound(observed, item, item.current_name):
                return MigrationResult(
                    MigrationStatus.COMPENSATION_INCOMPLETE,
                    tuple(completed),
                    (item.portable_id,),
                    True,
                )
            completed.remove(item.portable_id)
            _write_private(plan.journal_path, _encoded(_payload(plan, tuple(completed))))
            if outcome.status is not CommandStatus.SUCCEEDED:
                continue
        if not _complete_old_collection(rediscover(), plan):
            return MigrationResult(
                MigrationStatus.COMPENSATION_INCOMPLETE,
                tuple(completed),
                tuple(item.portable_id for item in plan.items),
                True,
            )
        removed = _unlink_private(plan.journal_path)
        return MigrationResult(MigrationStatus.COMPENSATED, journal_residue=not removed)

    if plan.status is MigrationStatus.MIGRATION_REQUIRED:
        # Revalidate the sealed collection and absent targets immediately before authority.
        fresh = build_role_name_migration_plan(rediscover(), plan.journal_path)
        if fresh.fingerprint != plan.fingerprint:
            return MigrationResult(MigrationStatus.AMBIGUOUS)
        _write_private(plan.journal_path, _encoded(_payload(plan, ())))

    pending = [item for item in plan.items if item.portable_id not in completed]
    for item in pending:
        if not _bound(rediscover(), item, item.current_name):
            return MigrationResult(
                MigrationStatus.AMBIGUOUS, tuple(completed), journal_residue=True
            )
        outcome = rename(item.current_name, item.target_name)
        observed = rediscover()
        effect_completed = _bound(observed, item, item.target_name)
        if effect_completed and item.portable_id not in completed:
            completed.append(item.portable_id)
            _write_private(plan.journal_path, _encoded(_payload(plan, tuple(completed))))
        if outcome.status is not CommandStatus.SUCCEEDED or not effect_completed:
            if not compensate_on_failure:
                return MigrationResult(
                    MigrationStatus.FAILED, tuple(completed), journal_residue=True
                )
            residue: list[str] = []
            for restored in reversed(plan.items):
                if restored.portable_id not in completed:
                    continue
                if not _bound(rediscover(), restored, restored.target_name):
                    residue.append(restored.portable_id)
                    continue
                rename(restored.target_name, restored.current_name)
                rollback_observed = rediscover()
                if not _bound(rollback_observed, restored, restored.current_name):
                    residue.append(restored.portable_id)
                    continue
                completed.remove(restored.portable_id)
                _write_private(plan.journal_path, _encoded(_payload(plan, tuple(completed))))
            if residue:
                return MigrationResult(
                    MigrationStatus.COMPENSATION_INCOMPLETE,
                    tuple(completed),
                    tuple(residue),
                    True,
                )
            if not _complete_old_collection(rediscover(), plan):
                return MigrationResult(
                    MigrationStatus.COMPENSATION_INCOMPLETE,
                    tuple(completed),
                    tuple(item.portable_id for item in plan.items),
                    True,
                )
            removed = _unlink_private(plan.journal_path)
            return MigrationResult(MigrationStatus.COMPENSATED, journal_residue=not removed)

    current = rediscover()
    if any(not _bound(current, item, item.target_name) for item in plan.items):
        return MigrationResult(
            MigrationStatus.COMPENSATION_INCOMPLETE,
            tuple(completed),
            tuple(item.portable_id for item in plan.items),
            True,
        )
    receipt = plan.journal_path.with_name("role-name-migration-receipt.json")
    _write_private(
        receipt,
        _encoded(
            {
                "schema": 1,
                "installation_id": plan.installation_id,
                "roles": list(completed),
                "status": "complete",
            }
        ),
    )
    removed = _unlink_private(plan.journal_path)
    return MigrationResult(
        MigrationStatus.COMPLETE,
        tuple(completed),
        journal_residue=not removed,
    )
