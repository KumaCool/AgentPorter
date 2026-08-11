from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from pydantic import ValidationError

from .identity import COMPONENT_IDS, PRODUCT_ID
from .models import MarkerV1

MARKER_NAME: Final = "agentporter-profile.json"
MAX_MARKER_BYTES: Final = 64 * 1024


class DiscoveryStatus(StrEnum):
    ALREADY_ABSENT = "already-absent"
    READY = "ready"
    AMBIGUOUS = "ambiguous"


class FindingCode(StrEnum):
    UNSAFE_PATH = "unsafe-path"
    INVALID_MARKER = "invalid-marker"
    UNKNOWN_COMPONENT = "unknown-component"
    DUPLICATE_COMPONENT = "duplicate-component"
    MULTIPLE_INSTALLATIONS = "multiple-installations"
    INSTALLATION_CONFLICT = "installation-conflict"
    INCOMPLETE = "incomplete"


_PRIORITY: Final = {
    FindingCode.UNSAFE_PATH: 0,
    FindingCode.INVALID_MARKER: 0,
    FindingCode.UNKNOWN_COMPONENT: 1,
    FindingCode.DUPLICATE_COMPONENT: 2,
    FindingCode.MULTIPLE_INSTALLATIONS: 3,
    FindingCode.INSTALLATION_CONFLICT: 3,
    FindingCode.INCOMPLETE: 4,
}


@dataclass(frozen=True)
class Finding:
    code: FindingCode
    path: Path
    detail: str


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    mode_type: int


@dataclass(frozen=True)
class Target:
    current_name: str
    path: Path
    marker_path: Path
    marker: MarkerV1
    profile_identity: FileIdentity
    marker_identity: FileIdentity
    marker_hash: str


@dataclass(frozen=True)
class DiscoveryResult:
    status: DiscoveryStatus
    targets: tuple[Target, ...]
    findings: tuple[Finding, ...]

    @property
    def primary_finding(self) -> Finding | None:
        return self.findings[0] if self.findings else None


def _descriptor_scan_supported() -> bool:
    return (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )


def _identity(value: os.stat_result) -> FileIdentity:
    return FileIdentity(value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


def _same(left: os.stat_result, right: os.stat_result) -> bool:
    return _identity(left) == _identity(right)


def _finding(code: FindingCode, path: Path, detail: str) -> Finding:
    return Finding(code, path, detail)


def _ambiguous(findings: list[Finding]) -> DiscoveryResult:
    ordered = tuple(
        sorted(findings, key=lambda item: (_PRIORITY[item.code], str(item.path), item.code))
    )
    return DiscoveryResult(DiscoveryStatus.AMBIGUOUS, (), ordered)


def _open_directory(name: str | Path, *, parent_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if parent_fd is None:
        return os.open(name, flags)
    return os.open(name, flags, dir_fd=parent_fd)


def _stat_at(name: str, parent_fd: int) -> os.stat_result:
    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)


def _read_marker(profile_fd: int, marker_before: os.stat_result) -> tuple[bytes, os.stat_result]:
    marker_fd = os.open(MARKER_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=profile_fd)
    try:
        opened = os.fstat(marker_fd)
        if not stat.S_ISREG(opened.st_mode) or not _same(marker_before, opened):
            raise OSError("marker identity changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(marker_fd, min(65536, MAX_MARKER_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MARKER_BYTES:
                raise ValueError("marker exceeds size limit")
        after = _stat_at(MARKER_NAME, profile_fd)
        if not _same(opened, after):
            raise OSError("marker identity changed")
        return b"".join(chunks), opened
    finally:
        os.close(marker_fd)


def _parse_marker(payload: bytes) -> tuple[MarkerV1 | None, FindingCode | None, str]:
    try:
        decoded = payload.decode("utf-8")
        raw = json.loads(decoded)
    except (UnicodeError, json.JSONDecodeError):
        return None, FindingCode.INVALID_MARKER, "marker is not valid UTF-8 JSON"
    if not isinstance(raw, dict):
        return None, FindingCode.INVALID_MARKER, "marker schema is invalid"
    data = cast(dict[object, object], raw)
    product_id = data.get("product_id")
    schema_version = data.get("schema_version")
    if product_id == PRODUCT_ID and schema_version != 1:
        return None, FindingCode.UNKNOWN_COMPONENT, "unsupported marker schema version"
    try:
        marker = MarkerV1.model_validate(raw)
    except ValidationError:
        return None, FindingCode.INVALID_MARKER, "marker schema is invalid"
    return marker, None, ""


def discover_installation(profiles_root: Path) -> DiscoveryResult:
    try:
        root_before = profiles_root.lstat()
    except FileNotFoundError:
        return DiscoveryResult(DiscoveryStatus.ALREADY_ABSENT, (), ())
    except OSError:
        return _ambiguous([_finding(FindingCode.UNSAFE_PATH, profiles_root, "root unreadable")])

    if not _descriptor_scan_supported():
        return _ambiguous(
            [_finding(FindingCode.UNSAFE_PATH, profiles_root, "descriptor-safe scan unsupported")]
        )
    if (
        not profiles_root.is_absolute()
        or not stat.S_ISDIR(root_before.st_mode)
        or stat.S_ISLNK(root_before.st_mode)
    ):
        return _ambiguous(
            [_finding(FindingCode.UNSAFE_PATH, profiles_root, "root is not canonical")]
        )
    try:
        if profiles_root.resolve(strict=True) != profiles_root:
            return _ambiguous(
                [_finding(FindingCode.UNSAFE_PATH, profiles_root, "root is not canonical")]
            )
        root_fd = _open_directory(profiles_root)
    except OSError:
        return _ambiguous([_finding(FindingCode.UNSAFE_PATH, profiles_root, "root is unsafe")])

    findings: list[Finding] = []
    candidates = 0
    matching: list[Target] = []
    try:
        if not _same(root_before, os.fstat(root_fd)):
            raise OSError("root identity changed")
        names = sorted(os.listdir(root_fd))
        for name in names:
            profile_path = profiles_root / name
            marker_path = profile_path / MARKER_NAME
            try:
                profile_before = _stat_at(name, root_fd)
            except OSError:
                findings.append(
                    _finding(FindingCode.UNSAFE_PATH, profile_path, "profile unreadable")
                )
                continue
            if stat.S_ISLNK(profile_before.st_mode):
                candidates += 1
                findings.append(
                    _finding(FindingCode.UNSAFE_PATH, profile_path, "profile is a symlink")
                )
                continue
            if not stat.S_ISDIR(profile_before.st_mode):
                continue
            try:
                profile_fd = _open_directory(name, parent_fd=root_fd)
            except OSError:
                findings.append(_finding(FindingCode.UNSAFE_PATH, profile_path, "profile changed"))
                continue
            try:
                if not _same(profile_before, os.fstat(profile_fd)):
                    raise OSError("profile identity changed")
                try:
                    marker_before = _stat_at(MARKER_NAME, profile_fd)
                except FileNotFoundError:
                    continue
                except OSError:
                    candidates += 1
                    findings.append(
                        _finding(FindingCode.UNSAFE_PATH, marker_path, "marker unreadable")
                    )
                    continue
                candidates += 1
                if stat.S_ISLNK(marker_before.st_mode):
                    findings.append(
                        _finding(FindingCode.UNSAFE_PATH, marker_path, "marker is a symlink")
                    )
                    continue
                if (
                    not stat.S_ISREG(marker_before.st_mode)
                    or marker_before.st_size > MAX_MARKER_BYTES
                ):
                    findings.append(
                        _finding(
                            FindingCode.INVALID_MARKER, marker_path, "marker is not a bounded file"
                        )
                    )
                    continue
                try:
                    payload, marker_stat = _read_marker(profile_fd, marker_before)
                    marker_after_read = _stat_at(MARKER_NAME, profile_fd)
                    if not _same(marker_stat, marker_after_read):
                        raise OSError("marker identity changed")
                    profile_after = _stat_at(name, root_fd)
                    if not _same(profile_before, profile_after):
                        raise OSError("profile identity changed")
                except ValueError:
                    findings.append(
                        _finding(
                            FindingCode.INVALID_MARKER, marker_path, "marker exceeds size limit"
                        )
                    )
                    continue
                except OSError:
                    findings.append(
                        _finding(FindingCode.UNSAFE_PATH, marker_path, "candidate identity changed")
                    )
                    continue
                marker, error_code, detail = _parse_marker(payload)
                if error_code is not None:
                    findings.append(_finding(error_code, marker_path, detail))
                    continue
                assert marker is not None
                if marker.product_id != PRODUCT_ID:
                    continue
                if marker.component_id not in COMPONENT_IDS.values():
                    findings.append(
                        _finding(FindingCode.UNKNOWN_COMPONENT, marker_path, "unknown component")
                    )
                    continue
                matching.append(
                    Target(
                        name,
                        profile_path,
                        marker_path,
                        marker,
                        _identity(profile_before),
                        _identity(marker_stat),
                        hashlib.sha256(payload).hexdigest(),
                    )
                )
            finally:
                os.close(profile_fd)
        if not _same(root_before, os.fstat(root_fd)):
            raise OSError("root identity changed")
    except OSError:
        findings.append(_finding(FindingCode.UNSAFE_PATH, profiles_root, "root identity changed"))
    finally:
        os.close(root_fd)

    if candidates == 0 and not findings:
        return DiscoveryResult(DiscoveryStatus.ALREADY_ABSENT, (), ())

    if not matching and not findings:
        return DiscoveryResult(DiscoveryStatus.ALREADY_ABSENT, (), ())

    expected = set(COMPONENT_IDS.values())
    by_installation: dict[str, list[Target]] = defaultdict(list)
    for target in matching:
        by_installation[target.marker.installation_id].append(target)
    for installation_id in sorted(by_installation):
        targets = by_installation[installation_id]
        counts = Counter(target.marker.component_id for target in targets)
        for component_id in sorted(component for component, count in counts.items() if count > 1):
            findings.append(
                _finding(
                    FindingCode.DUPLICATE_COMPONENT,
                    profiles_root,
                    f"duplicate component {component_id} in installation {installation_id}",
                )
            )
        missing = expected - set(counts)
        if missing:
            findings.append(
                _finding(
                    FindingCode.INCOMPLETE,
                    profiles_root,
                    f"installation {installation_id} is incomplete",
                )
            )
    complete = [
        installation_id
        for installation_id, targets in by_installation.items()
        if len(targets) == len(expected)
        and {target.marker.component_id for target in targets} == expected
    ]
    if len(complete) > 1:
        findings.append(
            _finding(
                FindingCode.MULTIPLE_INSTALLATIONS, profiles_root, "multiple complete installations"
            )
        )
    elif len(by_installation) > 1:
        findings.append(
            _finding(
                FindingCode.INSTALLATION_CONFLICT, profiles_root, "components span installations"
            )
        )

    if findings or len(complete) != 1 or len(by_installation) != 1:
        if matching and not findings:
            findings.append(
                _finding(FindingCode.INCOMPLETE, profiles_root, "installation incomplete")
            )
        return _ambiguous(findings)
    ready_targets = tuple(
        sorted(by_installation[complete[0]], key=lambda target: target.current_name)
    )
    return DiscoveryResult(DiscoveryStatus.READY, ready_targets, ())
