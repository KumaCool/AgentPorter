"""Replayable, secret-safe AgentPorter activation transaction."""

from __future__ import annotations

import hashlib
import json
import os
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


@dataclass(frozen=True, slots=True)
class ActivationTargetPlan:
    binding: RuntimeBindingPlan
    profile_path: Path = field(repr=False)
    original_config: ConfigSnapshot = field(repr=False)
    profile_device: int = field(repr=False)
    profile_inode: int = field(repr=False)

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
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
        os.close(descriptor)
        raise ValueError("profile changed while opening")
    return descriptor


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
        return ConfigSnapshot(default, provider, base_url, _digest(payload), payload)
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


def _atomic_write(path: Path, payload: bytes) -> None:
    profile_fd = _safe_profile_fd(path)
    temporary = ".agentporter-config.tmp"
    temp_fd: int | None = None
    try:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=profile_fd)
        temp_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=profile_fd,
        )
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        os.replace(temporary, "config.yaml", src_dir_fd=profile_fd, dst_dir_fd=profile_fd)
        os.chmod("config.yaml", 0o600, dir_fd=profile_fd, follow_symlinks=False)
        os.fsync(profile_fd)
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=profile_fd)
        os.close(profile_fd)


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
                binding, target.path, snapshot, target.profile_device, target.profile_inode
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
    return (
        stat.S_ISDIR(current.st_mode)
        and not stat.S_ISLNK(current.st_mode)
        and current.st_dev == target.profile_device
        and current.st_ino == target.profile_inode
    )


def _restore(attempted: list[ActivationTargetPlan]) -> int:
    residue = 0
    for target in reversed(attempted):
        try:
            current = _read_config(target.profile_path)
            config = _decoded_mapping(current)
            model_value = config["model"]
            assert isinstance(model_value, dict)
            model = cast(dict[str, object], model_value)
            binding = target.binding
            for key, written, original in (
                ("provider", binding.provider_id, target.original_config.provider),
                ("base_url", binding.endpoint_value, target.original_config.base_url),
            ):
                if model.get(key) == written:
                    if original is None:
                        model.pop(key, None)
                    else:
                        model[key] = original
                else:
                    residue += 1
            _atomic_write(target.profile_path, yaml.safe_dump(config, sort_keys=False).encode())
        except (OSError, ValueError, yaml.YAMLError):
            residue += 1
    return residue


def _write_receipt(target: ActivationTargetPlan, readback: ConfigSnapshot) -> None:
    local = target.profile_path / "local"
    agentporter = local / "agentporter"
    for directory in (local, agentporter):
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("receipt directory is unsafe")
        directory.chmod(0o700)
    payload = {
        **target.binding.safe_receipt().as_dict(),
        "config_digest": readback.digest,
        "config_readback_passed": True,
        "canary_status": "required",
    }
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    directory_fd = os.open(agentporter, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".runtime-binding.tmp"
    descriptor: int | None = None
    try:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory_fd)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        os.write(descriptor, data)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary,
            "runtime-binding.json",
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.chmod("runtime-binding.json", 0o600, dir_fd=directory_fd, follow_symlinks=False)
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory_fd)
        os.close(directory_fd)


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
            if not _target_is_bound(target) or (
                _read_config(target.profile_path).digest != target.original_config.digest
            ):
                return ActivationResult(ActivationStatus.STALE)
    except ValueError:
        return ActivationResult(ActivationStatus.STALE)

    attempted: list[ActivationTargetPlan] = []
    readbacks: list[ConfigSnapshot] = []
    try:
        for index, target in enumerate(plan.bindings):
            if not _target_is_bound(target) or (
                _read_config(target.profile_path).digest != target.original_config.digest
            ):
                raise ValueError("activation target changed before write")
            _atomic_write(target.profile_path, _updated_payload(target))
            attempted.append(target)
            if after_write is not None:
                after_write(target, index)
            readback = _read_config(target.profile_path)
            if (
                readback.model != target.expected_model
                or readback.provider != target.binding.provider_id
                or readback.base_url != target.binding.endpoint_value
            ):
                raise ValueError("activation readback mismatch")
            readbacks.append(readback)
        for target, readback in zip(plan.bindings, readbacks, strict=True):
            _write_receipt(target, readback)
    except BaseException:
        residue = _restore(attempted)
        status = ActivationStatus.COMPENSATION_INCOMPLETE if residue else ActivationStatus.FAILED
        return ActivationResult(status, residue_count=residue)

    items = tuple(
        ActivationItemResult(target.component_id, target.profile_name, True)
        for target in plan.bindings
    )
    if any(target.binding.credential_state != "operator-authorized" for target in plan.bindings):
        return ActivationResult(ActivationStatus.CREDENTIAL_REQUIRED, items)
    # Phase B stops at a verified binding receipt. Phase C owns all real probes.
    del probe_runner
    return ActivationResult(ActivationStatus.ACTIVATED, items)
