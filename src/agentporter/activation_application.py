"""Replayable, secret-safe AgentPorter activation transaction."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TextIO, cast

import yaml

from .hermes import HermesDetection
from .identity import COMPONENT_IDS
from .runtime_binding import CredentialGrantKind, CredentialState, RuntimeBindingPlan
from .uninstall_discovery import DiscoveryResult, DiscoveryStatus, Target


class ActivationStatus(StrEnum):
    ACTIVATED = "activated"
    CREDENTIAL_REQUIRED = "credential-required"
    CANCELLED = "cancelled"
    STALE = "stale"
    FAILED = "failed"
    COMPENSATION_INCOMPLETE = "compensation-incomplete"


@dataclass(frozen=True, slots=True)
class ActivationBindingInput:
    provider_id: str
    endpoint_value: str = field(repr=False)
    credential_grant_kind: CredentialGrantKind
    credential_state: CredentialState


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    model: str
    provider: str | None
    base_url: str | None = field(repr=False)
    digest: str
    content: bytes = field(repr=False)
    device: int = field(repr=False)
    inode: int = field(repr=False)
    uid: int = field(repr=False)
    gid: int = field(repr=False)


@dataclass(frozen=True, slots=True)
class ActivationTargetPlan:
    binding: RuntimeBindingPlan
    profile_path: Path = field(repr=False)
    original_config: ConfigSnapshot = field(repr=False)
    profile_device: int = field(repr=False)
    profile_inode: int = field(repr=False)
    marker_digest: str = field(repr=False)
    marker_device: int = field(repr=False)
    marker_inode: int = field(repr=False)

    @property
    def component_id(self) -> str:
        return self.binding.component_id

    @property
    def profile_name(self) -> str:
        return self.binding.current_profile_name

    @property
    def expected_model(self) -> str:
        return self.binding.expected_model


@dataclass(frozen=True, slots=True)
class ActivationPlan:
    installation_id: str
    hermes_home: Path = field(repr=False)
    bindings: tuple[ActivationTargetPlan, ...]
    confirmation_phrase: str


@dataclass(frozen=True, slots=True)
class ActivationItemResult:
    component_id: str
    profile_name: str
    readback_passed: bool


@dataclass(frozen=True, slots=True)
class ActivationResult:
    status: ActivationStatus
    items: tuple[ActivationItemResult, ...] = ()
    residue_count: int = 0


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_profile_fd(path: Path) -> int:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise ValueError("profile must be a safe directory")
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino):
            return descriptor
    except BaseException:
        os.close(descriptor)
        raise
    os.close(descriptor)
    raise ValueError("profile changed while opening")


def _read_config(path: Path) -> ConfigSnapshot:
    profile_fd = _safe_profile_fd(path)
    config_fd: int | None = None
    try:
        before = os.stat("config.yaml", dir_fd=profile_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError("config.yaml must be a safe regular file")
        config_fd = os.open("config.yaml", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=profile_fd)
        opened = os.fstat(config_fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("config.yaml changed while opening")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(config_fd, 65536):
            total += len(chunk)
            if total > 1024 * 1024:
                raise ValueError("config.yaml exceeds size limit")
            chunks.append(chunk)
        after = os.stat("config.yaml", dir_fd=profile_fd, follow_symlinks=False)
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("config.yaml changed during read")
        payload = b"".join(chunks)
        loaded = yaml.safe_load(payload)
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml must be a mapping")
        root = cast(dict[object, object], loaded)
        model_value = root.get("model")
        if not isinstance(model_value, dict):
            raise ValueError("config.yaml model must be a mapping")
        model = cast(dict[object, object], model_value)
        default = model.get("default")
        provider = model.get("provider")
        base_url = model.get("base_url")
        if not isinstance(default, str) or not default.strip():
            raise ValueError("config.yaml model.default must be a string")
        if provider is not None and not isinstance(provider, str):
            raise ValueError("config.yaml model.provider must be a string")
        if base_url is not None and not isinstance(base_url, str):
            raise ValueError("config.yaml model.base_url must be a string")
        return ConfigSnapshot(
            default,
            provider,
            base_url,
            _digest(payload),
            payload,
            opened.st_dev,
            opened.st_ino,
            opened.st_uid,
            opened.st_gid,
        )
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError("config.yaml could not be safely read") from error
    finally:
        if config_fd is not None:
            os.close(config_fd)
        os.close(profile_fd)


def _decoded_mapping(snapshot: ConfigSnapshot) -> dict[str, object]:
    loaded = yaml.safe_load(snapshot.content)
    assert isinstance(loaded, dict)
    return cast(dict[str, object], loaded)


def _same_config(current: ConfigSnapshot, expected: ConfigSnapshot) -> bool:
    return (
        current.digest == expected.digest
        and current.device == expected.device
        and current.inode == expected.inode
    )


def _named_file_identity_digest(directory_fd: int, name: str) -> tuple[int, int, str]:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("publication target is not a regular file")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            if total > 1024 * 1024:
                raise ValueError("publication target exceeds size limit")
            chunks.append(chunk)
        rebound = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (rebound.st_dev, rebound.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("publication target changed during read")
        return opened.st_dev, opened.st_ino, _digest(b"".join(chunks))
    finally:
        os.close(descriptor)


def _exchange_names(directory_fd: int, left: str, right: str) -> None:
    """Atomically exchange two names, or fail closed when the OS has no CAS rename."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise ValueError("atomic name exchange is unavailable") from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(directory_fd, os.fsencode(left), directory_fd, os.fsencode(right), 2) != 0:
        code = ctypes.get_errno()
        if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise ValueError("atomic name exchange is unavailable")
        raise OSError(code, os.strerror(code))


def _atomic_write(path: Path, payload: bytes, expected: ConfigSnapshot) -> ConfigSnapshot:
    profile_fd = _safe_profile_fd(path)
    temporary = f".agentporter-config.{secrets.token_hex(16)}.tmp"
    temp_fd: int | None = None
    created: tuple[int, int, str] | None = None
    try:
        current = _read_config(path)
        if not _same_config(current, expected):
            raise ValueError("config changed before publication")
        temp_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=profile_fd,
        )
        temp_info = os.fstat(temp_fd)
        created = (temp_info.st_dev, temp_info.st_ino, _digest(payload))
        os.fchown(temp_fd, expected.uid, expected.gid)
        os.fchmod(temp_fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        expected_identity = (expected.device, expected.inode, expected.digest)
        # Bind the last comparison and publication to one directory descriptor. The
        # exchange makes any drift in the remaining window observable at `temporary`.
        if _named_file_identity_digest(profile_fd, "config.yaml") != expected_identity:
            raise ValueError("config changed before publication")
        _exchange_names(profile_fd, temporary, "config.yaml")
        displaced = _named_file_identity_digest(profile_fd, temporary)
        if displaced != expected_identity:
            published = _named_file_identity_digest(profile_fd, "config.yaml")
            if published == created:
                _exchange_names(profile_fd, temporary, "config.yaml")
            raise ValueError("config changed at publication")
        os.unlink(temporary, dir_fd=profile_fd)
        created = None
        os.chmod("config.yaml", 0o600, dir_fd=profile_fd, follow_symlinks=False)
        os.fsync(profile_fd)
        return _read_config(path)
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if created is not None:
            with suppress(FileNotFoundError):
                if _named_file_identity_digest(profile_fd, temporary) == created:
                    os.unlink(temporary, dir_fd=profile_fd)
        os.close(profile_fd)


def _atomic_write_target(
    target: ActivationTargetPlan, payload: bytes, expected: ConfigSnapshot
) -> ConfigSnapshot:
    """Publish only while the complete planned installation identity remains bound."""
    if not _target_is_bound(target):
        raise ValueError("activation target changed before publication")
    result = _atomic_write(target.profile_path, payload, expected)
    if not _target_is_bound(target):
        raise ValueError("activation target changed during publication")
    return result


def _updated_payload(target: ActivationTargetPlan) -> bytes:
    config = _decoded_mapping(target.original_config)
    model_value = config["model"]
    assert isinstance(model_value, dict)
    model = cast(dict[str, object], model_value)
    model["provider"] = target.binding.provider_id
    model["base_url"] = target.binding.endpoint_value
    return yaml.safe_dump(config, sort_keys=False).encode("utf-8")


def _target_for_component(discovery: DiscoveryResult) -> Mapping[str, Target]:
    return MappingProxyType({target.component_id: target for target in discovery.targets})


def _marker_identity(path: Path) -> tuple[str, int, int]:
    profile_fd = _safe_profile_fd(path)
    descriptor: int | None = None
    try:
        before = os.stat("agentporter-profile.json", dir_fd=profile_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError("marker must be a safe regular file")
        descriptor = os.open(
            "agentporter-profile.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=profile_fd
        )
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
            if sum(map(len, chunks)) > 1024 * 1024:
                raise ValueError("marker exceeds size limit")
        rebound = os.stat("agentporter-profile.json", dir_fd=profile_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or (
            rebound.st_dev,
            rebound.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise ValueError("marker changed during read")
        return _digest(b"".join(chunks)), opened.st_dev, opened.st_ino
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(profile_fd)


def build_activation_plan(
    discovery: DiscoveryResult,
    detection: HermesDetection,
    inputs: Mapping[str, ActivationBindingInput],
) -> ActivationPlan:
    """Bind operator inputs only to one descriptor-discovered complete installation."""
    if discovery.status is not DiscoveryStatus.READY or not discovery.targets:
        raise ValueError("activation requires one complete installation")
    expected_components = set(COMPONENT_IDS.values())
    if set(inputs) != expected_components:
        raise ValueError("activation inputs must exactly match installed components")
    if (
        discovery.profiles_root != detection.profiles_root
        or discovery.hermes_home != detection.hermes_home
    ):
        raise ValueError("discovery does not match detected Hermes home")
    targets = _target_for_component(discovery)
    portable_by_component = {component: portable for portable, component in COMPONENT_IDS.items()}
    installation_ids = {target.installation_id for target in discovery.targets}
    if len(installation_ids) != 1:
        raise ValueError("activation requires one installation id")
    bindings: list[ActivationTargetPlan] = []
    for component_id in COMPONENT_IDS.values():
        target = targets[component_id]
        snapshot = _read_config(target.path)
        marker_digest, marker_device, marker_inode = _marker_identity(target.path)
        supplied = inputs[component_id]
        binding = RuntimeBindingPlan.from_values(
            portable_id=portable_by_component[component_id],
            component_id=component_id,
            current_profile_name=target.current_name,
            expected_model=snapshot.model,
            provider_id=supplied.provider_id,
            endpoint_value=supplied.endpoint_value,
            credential_grant_kind=supplied.credential_grant_kind,
            credential_state=supplied.credential_state,
            hermes_version=detection.version,
            config_digest=snapshot.digest,
        )
        bindings.append(
            ActivationTargetPlan(
                binding,
                target.path,
                snapshot,
                target.profile_device,
                target.profile_inode,
                marker_digest,
                marker_device,
                marker_inode,
            )
        )
    installation_id = installation_ids.pop()
    return ActivationPlan(
        installation_id,
        detection.hermes_home,
        tuple(bindings),
        f"ACTIVATE AGENTPORTER {installation_id[:8]}",
    )


def _safe_summary(plan: ActivationPlan, output: TextIO) -> None:
    print(f"AgentPorter activation targets: {len(plan.bindings)}", file=output)
    for target in plan.bindings:
        print(
            f"- {target.profile_name}: {target.expected_model} / "
            f"{target.binding.provider_id} / endpoint sha256:{target.binding.endpoint_digest[:12]}",
            file=output,
        )
    print(
        "Activation writes two non-secret keys per target; model canary is a later phase.",
        file=output,
    )


def _target_is_bound(target: ActivationTargetPlan) -> bool:
    try:
        current = target.profile_path.lstat()
    except OSError:
        return False
    if not (
        stat.S_ISDIR(current.st_mode)
        and not stat.S_ISLNK(current.st_mode)
        and current.st_dev == target.profile_device
        and current.st_ino == target.profile_inode
    ):
        return False
    try:
        marker = _marker_identity(target.profile_path)
    except (OSError, ValueError):
        return False
    return marker == (target.marker_digest, target.marker_device, target.marker_inode)


def _restore(attempted: list[ActivationTargetPlan]) -> int:
    residue = 0
    for target in reversed(attempted):
        try:
            current = _read_config(target.profile_path)
            if current.content != _updated_payload(target) or not _target_is_bound(target):
                residue += 1
                continue
            _atomic_write_target(target, target.original_config.content, current)
        except (OSError, ValueError, yaml.YAMLError):
            residue += 1
    return residue


@dataclass(frozen=True, slots=True)
class _ReceiptSnapshot:
    exists: bool
    content: bytes = field(default=b"", repr=False)
    device: int = field(default=0, repr=False)
    inode: int = field(default=0, repr=False)
    uid: int = 0
    gid: int = 0
    mode: int = 0


def _receipt_directory_fd(target: ActivationTargetPlan) -> int:
    profile_fd = _safe_profile_fd(target.profile_path)
    local_fd: int | None = None
    directory_fd: int | None = None
    try:
        profile_info = os.fstat(profile_fd)
        if (profile_info.st_dev, profile_info.st_ino) != (
            target.profile_device,
            target.profile_inode,
        ):
            raise ValueError("receipt profile changed")
        with suppress(FileExistsError):
            os.mkdir("local", 0o700, dir_fd=profile_fd)
        local_fd = os.open("local", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=profile_fd)
        local_info = os.fstat(local_fd)
        bound_local = os.stat("local", dir_fd=profile_fd, follow_symlinks=False)
        if (local_info.st_dev, local_info.st_ino) != (bound_local.st_dev, bound_local.st_ino):
            raise ValueError("receipt parent changed")
        with suppress(FileExistsError):
            os.mkdir("agentporter", 0o700, dir_fd=local_fd)
        directory_fd = os.open(
            "agentporter", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=local_fd
        )
        directory_info = os.fstat(directory_fd)
        bound_directory = os.stat("agentporter", dir_fd=local_fd, follow_symlinks=False)
        if (directory_info.st_dev, directory_info.st_ino) != (
            bound_directory.st_dev,
            bound_directory.st_ino,
        ):
            raise ValueError("receipt directory changed")
        os.fchmod(local_fd, 0o700)
        os.fchmod(directory_fd, 0o700)
        result = directory_fd
        directory_fd = None
        return result
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        if local_fd is not None:
            os.close(local_fd)
        os.close(profile_fd)


def _receipt_snapshot(target: ActivationTargetPlan) -> _ReceiptSnapshot:
    directory_fd = _receipt_directory_fd(target)
    descriptor: int | None = None
    try:
        try:
            before = os.stat("runtime-binding.json", dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return _ReceiptSnapshot(False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError("receipt is unsafe")
        descriptor = os.open(
            "runtime-binding.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd
        )
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        rebound = os.stat("runtime-binding.json", dir_fd=directory_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or (
            rebound.st_dev,
            rebound.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise ValueError("receipt changed during snapshot")
        return _ReceiptSnapshot(
            True,
            b"".join(chunks),
            opened.st_dev,
            opened.st_ino,
            opened.st_uid,
            opened.st_gid,
            stat.S_IMODE(opened.st_mode),
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _publish_receipt(
    target: ActivationTargetPlan, data: bytes, *, uid: int, gid: int, mode: int
) -> _ReceiptSnapshot:
    directory_fd = _receipt_directory_fd(target)
    temporary = f".runtime-binding.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    created: tuple[int, int] | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        info = os.fstat(descriptor)
        created = (info.st_dev, info.st_ino)
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary, "runtime-binding.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd
        )
        created = None
        os.fsync(directory_fd)
        return _receipt_snapshot(target)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created is not None:
            with suppress(FileNotFoundError):
                leftover = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
                if (leftover.st_dev, leftover.st_ino) == created:
                    os.unlink(temporary, dir_fd=directory_fd)
        os.close(directory_fd)


def _write_receipt(target: ActivationTargetPlan, readback: ConfigSnapshot) -> _ReceiptSnapshot:
    payload = {
        **target.binding.safe_receipt().as_dict(),
        "config_digest": readback.digest,
        "config_readback_passed": True,
        "canary_status": "required",
    }
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    existing = _receipt_snapshot(target)
    return _publish_receipt(
        target,
        data,
        uid=existing.uid if existing.exists else os.geteuid(),
        gid=existing.gid if existing.exists else os.getegid(),
        mode=0o600,
    )


def _same_receipt(current: _ReceiptSnapshot, expected: _ReceiptSnapshot) -> bool:
    return (
        current.exists
        and expected.exists
        and current.content == expected.content
        and current.device == expected.device
        and current.inode == expected.inode
    )


def _restore_receipts(
    snapshots: list[tuple[ActivationTargetPlan, _ReceiptSnapshot, _ReceiptSnapshot | None]],
) -> int:
    residue = 0
    for target, snapshot, published in reversed(snapshots):
        if published is None:
            continue
        try:
            current = _receipt_snapshot(target)
            if not _same_receipt(current, published):
                residue += 1
                continue
            if snapshot.exists:
                _publish_receipt(
                    target, snapshot.content, uid=snapshot.uid, gid=snapshot.gid, mode=snapshot.mode
                )
            else:
                directory_fd = _receipt_directory_fd(target)
                try:
                    os.unlink("runtime-binding.json", dir_fd=directory_fd)
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except (OSError, ValueError):
            residue += 1
    return residue


def apply_activation(
    plan: ActivationPlan,
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    command_observer: Callable[[object], None] | None = None,
    after_write: Callable[[ActivationTargetPlan, int], None] | None = None,
    probe_runner: Callable[[RuntimeBindingPlan], object] | None = None,
) -> ActivationResult:
    """Confirm once, compare/write/read back, and safely compensate on failure."""
    del command_observer  # The secure direct-file seam intentionally executes no command.
    _safe_summary(plan, output)
    if input_fn("Type the activation phrase exactly: ") != plan.confirmation_phrase:
        return ActivationResult(ActivationStatus.CANCELLED)
    try:
        for target in plan.bindings:
            if not _target_is_bound(target) or not _same_config(
                _read_config(target.profile_path), target.original_config
            ):
                return ActivationResult(ActivationStatus.STALE)
    except ValueError:
        return ActivationResult(ActivationStatus.STALE)

    attempted: list[ActivationTargetPlan] = []
    readbacks: list[ConfigSnapshot] = []
    receipt_snapshots: list[
        tuple[ActivationTargetPlan, _ReceiptSnapshot, _ReceiptSnapshot | None]
    ] = []
    try:
        receipt_snapshots = [(target, _receipt_snapshot(target), None) for target in plan.bindings]
        for index, target in enumerate(plan.bindings):
            current = _read_config(target.profile_path)
            if not _target_is_bound(target) or not _same_config(current, target.original_config):
                raise ValueError("activation target changed before write")
            # Register before publication so a post-replace identity failure is compensable.
            attempted.append(target)
            readback = _atomic_write_target(target, _updated_payload(target), current)
            if after_write is not None:
                after_write(target, index)
            if (
                readback.model != target.expected_model
                or readback.provider != target.binding.provider_id
                or readback.base_url != target.binding.endpoint_value
            ):
                raise ValueError("activation readback mismatch")
            readbacks.append(readback)
        for index, (target, readback) in enumerate(zip(plan.bindings, readbacks, strict=True)):
            published = _write_receipt(target, readback)
            original = receipt_snapshots[index][1]
            receipt_snapshots[index] = (target, original, published)
    except Exception:
        residue = _restore(attempted) + _restore_receipts(receipt_snapshots)
        status = ActivationStatus.COMPENSATION_INCOMPLETE if residue else ActivationStatus.FAILED
        return ActivationResult(status, residue_count=residue)
    except BaseException as original:
        try:
            residue = _restore(attempted) + _restore_receipts(receipt_snapshots)
        except BaseException:
            residue = max(1, len(attempted))
        original.add_note(
            "AgentPorter activation compensation was incomplete; manual review required."
            if residue
            else "AgentPorter activation was compensated."
        )
        raise

    items = tuple(
        ActivationItemResult(target.component_id, target.profile_name, True)
        for target in plan.bindings
    )
    if any(target.binding.credential_state != "operator-authorized" for target in plan.bindings):
        return ActivationResult(ActivationStatus.CREDENTIAL_REQUIRED, items)
    # Phase B stops at a verified binding receipt. Phase C owns all real probes.
    del probe_runner
    return ActivationResult(ActivationStatus.ACTIVATED, items)
