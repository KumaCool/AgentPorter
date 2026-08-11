from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .execution import CommandExecutor, CommandStatus
from .hermes import HermesDetection, ProfileEntry
from .identity import PRODUCT_ID
from .models import HermesProfileName, MarkerV1
from .readback import InstalledProfileReadback


class CompensationItemStatus(StrEnum):
    DELETED = "deleted"
    DELETE_FAILED = "delete-failed"
    VERIFICATION_FAILED = "verification-failed"
    SNAPSHOT_CHANGED = "snapshot-changed"


class CompensationStatus(StrEnum):
    COMPENSATED = "compensated"
    INCOMPLETE = "compensation-incomplete"


@dataclass(frozen=True)
class CompensationItem:
    basename: str
    status: CompensationItemStatus
    reason: str


@dataclass(frozen=True)
class CompensationResult:
    status: CompensationStatus
    items: tuple[CompensationItem, ...]


class ProfileEnumerator(Protocol):
    def __call__(self) -> Sequence[ProfileEntry]: ...


DetectionProvider = Callable[[], HermesDetection]


def _same_identity(actual: os.stat_result, device: int, inode: int, kind: int) -> bool:
    return (
        actual.st_dev == device and actual.st_ino == inode and stat.S_IFMT(actual.st_mode) == kind
    )


def _read_marker(profile_fd: int) -> tuple[bytes, os.stat_result]:
    marker_fd: int | None = None
    try:
        marker_fd = os.open(
            "agentporter-profile.json",
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=profile_fd,
        )
        info = os.fstat(marker_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("marker is not regular")
        chunks: list[bytes] = []
        while chunk := os.read(marker_fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks), info
    finally:
        if marker_fd is not None:
            os.close(marker_fd)


def _revalidate(snapshot: object, detection: HermesDetection) -> bool:
    from .readback import CompensationSnapshot

    if not isinstance(snapshot, CompensationSnapshot):
        return False
    root_fd: int | None = None
    profile_fd: int | None = None
    try:
        home = detection.hermes_home.resolve(strict=True)
        root = detection.profiles_root.resolve(strict=True)
        if (
            detection.hermes_home != home
            or detection.profiles_root != root
            or home != snapshot.hermes_home
            or root != snapshot.profiles_root
            or root.parent != home
            or root.name != "profiles"
            or snapshot.path != root / snapshot.basename
            or snapshot.path.parent != root
            or snapshot.path.name != snapshot.basename
        ):
            return False
        try:
            HermesProfileName(snapshot.basename)
        except ValueError:
            return False
        root_fd = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        profile_fd = os.open(
            snapshot.basename,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fd,
        )
        profile_info = os.fstat(profile_fd)
        named_profile = os.stat(snapshot.basename, dir_fd=root_fd, follow_symlinks=False)
        if not _same_identity(
            profile_info,
            snapshot.profile_device,
            snapshot.profile_inode,
            snapshot.profile_type,
        ) or not _same_identity(
            named_profile,
            snapshot.profile_device,
            snapshot.profile_inode,
            snapshot.profile_type,
        ):
            return False
        marker_bytes, marker_info = _read_marker(profile_fd)
        named_marker = os.stat("agentporter-profile.json", dir_fd=profile_fd, follow_symlinks=False)
        if not _same_identity(
            marker_info,
            snapshot.marker_device,
            snapshot.marker_inode,
            snapshot.marker_type,
        ) or not _same_identity(
            named_marker,
            snapshot.marker_device,
            snapshot.marker_inode,
            snapshot.marker_type,
        ):
            return False
        if hashlib.sha256(marker_bytes).hexdigest() != snapshot.marker_sha256:
            return False
        marker = MarkerV1.model_validate_json(marker_bytes)
        return (
            marker.product_id == snapshot.product_id == PRODUCT_ID
            and marker.component_id == snapshot.component_id
            and marker.installation_id == snapshot.installation_id
        )
    except (OSError, ValueError, ValidationError):
        return False
    finally:
        if profile_fd is not None:
            os.close(profile_fd)
        if root_fd is not None:
            os.close(root_fd)


def _post_delete_state(
    snapshot_path: Path,
    basename: str,
    enumerate_profiles: ProfileEnumerator,
) -> tuple[bool, str]:
    problems: list[str] = []
    try:
        entries = tuple(enumerate_profiles())
        name_absent = not any(entry.name == basename for entry in entries)
    except BaseException as error:
        name_absent = False
        problems.append(f"enumeration raised {type(error).__name__}; detail suppressed")
    try:
        os.lstat(snapshot_path)
        path_absent = False
    except FileNotFoundError:
        path_absent = True
    except OSError as error:
        path_absent = False
        problems.append(f"path readback raised {type(error).__name__}; detail suppressed")
    if name_absent and path_absent:
        return True, "native enumeration and original path confirm absence"
    if problems:
        return False, "; ".join(problems)
    return False, "native enumeration or original path does not confirm absence"


def compensate_profiles(
    readbacks: Sequence[InstalledProfileReadback],
    *,
    current_detection: DetectionProvider,
    executor: CommandExecutor,
    env: Mapping[str, str],
    enumerate_profiles: ProfileEnumerator,
) -> CompensationResult:
    """Delete verified snapshots in reverse order after identity-bound immediate revalidation."""
    items: list[CompensationItem] = []
    for readback in reversed(tuple(readbacks)):
        snapshot = readback.snapshot
        try:
            detection = current_detection()
        except BaseException:
            items.append(
                CompensationItem(
                    snapshot.basename,
                    CompensationItemStatus.SNAPSHOT_CHANGED,
                    "current Hermes detection is unavailable",
                )
            )
            break
        if readback.status != "verified-compensable" or not _revalidate(snapshot, detection):
            items.append(
                CompensationItem(
                    snapshot.basename,
                    CompensationItemStatus.SNAPSHOT_CHANGED,
                    "descriptor-bound snapshot identity changed",
                )
            )
            break
        argv = (
            str(detection.executable),
            "profile",
            "delete",
            snapshot.basename,
            "--yes",
        )
        pending: BaseException | None = None
        command = None
        try:
            command = executor.run(argv, env=env)
        except BaseException as error:
            pending = error
        verified, reason = _post_delete_state(snapshot.path, snapshot.basename, enumerate_profiles)
        if pending is not None:
            state = "confirmed absent" if verified else "uncertain"
            pending.add_note(f"post-delete double readback: {state}; {reason}")
            raise pending
        assert command is not None
        if command.status is not CommandStatus.SUCCEEDED:
            items.append(
                CompensationItem(
                    snapshot.basename,
                    CompensationItemStatus.DELETE_FAILED,
                    "native delete command did not succeed",
                )
            )
            break
        if not verified:
            items.append(
                CompensationItem(
                    snapshot.basename,
                    CompensationItemStatus.VERIFICATION_FAILED,
                    reason,
                )
            )
            break
        items.append(
            CompensationItem(
                snapshot.basename,
                CompensationItemStatus.DELETED,
                "native deletion confirmed by enumeration and original path",
            )
        )
    status = (
        CompensationStatus.COMPENSATED
        if len(items) == len(readbacks)
        and all(item.status is CompensationItemStatus.DELETED for item in items)
        else CompensationStatus.INCOMPLETE
    )
    return CompensationResult(status, tuple(items))
