from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Never, cast

import yaml
from pydantic import ValidationError

from .hermes import HermesDetection
from .identity import PRODUCT_ID
from .models import MarkerV1
from .planning import ArtifactSeal, InstallPlan, WorkerInstallPlan
from .render import DISTRIBUTION_VERSION

ReadbackCode = Literal[
    "unsafe-path",
    "descriptor-unavailable",
    "missing-artifact",
    "invalid-artifact",
    "identity-mismatch",
    "source-mismatch",
    "content-mismatch",
    "description-mismatch",
    "collection-mismatch",
]

_OWNED_ARTIFACTS: Final = (
    "distribution.yaml",
    "config.yaml",
    "SOUL.md",
    "agentporter-profile.json",
)
_NATIVE_DISTRIBUTION_FIELDS: Final = frozenset(
    {
        "name",
        "version",
        "description",
        "hermes_requires",
        "author",
        "license",
        "env_requires",
        "distribution_owned",
        "source",
        "installed_at",
    }
)
_OPEN_SUPPORTS_DIR_FD: Final = os.open in os.supports_dir_fd
_STAT_SUPPORTS_DIR_FD: Final = os.stat in os.supports_dir_fd


class ReadbackError(RuntimeError):
    """Installed state could not be proven safe and transaction-related."""

    def __init__(self, code: ReadbackCode, detail: str = "readback verification failed") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class CompensationSnapshot:
    hermes_home: Path
    profiles_root: Path
    path: Path
    basename: str
    profile_device: int
    profile_inode: int
    profile_type: int
    marker_device: int
    marker_inode: int
    marker_type: int
    marker_sha256: str
    product_id: str
    component_id: str
    installation_id: str
    source: Path


@dataclass(frozen=True)
class InstalledProfileReadback:
    status: Literal["verified-compensable"]
    worker: WorkerInstallPlan
    snapshot: CompensationSnapshot


def _fail(code: ReadbackCode, detail: str) -> Never:
    raise ReadbackError(code, detail)


def _require_descriptor_capabilities() -> None:
    if (
        not _OPEN_SUPPORTS_DIR_FD
        or not _STAT_SUPPORTS_DIR_FD
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
    ):
        _fail("descriptor-unavailable", "required descriptor operations are unavailable")


def _read_regular(profile_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=profile_fd,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _fail("invalid-artifact", f"{name} is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks), info
    except FileNotFoundError:
        _fail("missing-artifact", name)
    except OSError as error:
        _fail("unsafe-path", f"could not safely read {name}: {type(error).__name__}")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _seal(plan: InstallPlan, worker: WorkerInstallPlan, name: str) -> ArtifactSeal:
    relative = f"{worker.profile_name}/{name}"
    try:
        return next(item for item in plan.artifacts if item.relative_path == relative)
    except StopIteration:
        _fail("invalid-artifact", f"missing plan seal for {name}")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail("invalid-artifact", f"{label} is not a string-keyed mapping")
    untyped = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in untyped):
        _fail("invalid-artifact", f"{label} is not a string-keyed mapping")
    return cast(dict[str, object], untyped)


def _canonical_source(plan: InstallPlan, worker: WorkerInstallPlan, value: object) -> Path:
    staging_dir = plan.staging_dir
    if staging_dir is None or not isinstance(value, str):
        _fail("source-mismatch", "distribution source is absent")
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        _fail("source-mismatch", "distribution source is not absolute")
    try:
        actual = raw.resolve(strict=True)
        expected = (staging_dir / worker.profile_name).resolve(strict=True)
    except OSError:
        _fail("source-mismatch", "distribution source cannot be canonicalized")
    if actual != expected or raw != actual:
        _fail("source-mismatch", "distribution source differs from sealed staging profile")
    return actual


def _validate_distribution(
    plan: InstallPlan,
    worker: WorkerInstallPlan,
    installed_bytes: bytes,
    native: Mapping[str, object],
) -> Path:
    try:
        loaded = cast(object, yaml.safe_load(installed_bytes))
    except (UnicodeDecodeError, yaml.YAMLError):
        _fail("invalid-artifact", "distribution is not valid UTF-8 YAML")
    filesystem = _mapping(loaded, "distribution")
    native_data = dict(native)
    if set(native_data) - _NATIVE_DISTRIBUTION_FIELDS:
        _fail("invalid-artifact", "distribution info contains fields outside Hermes schema")
    if filesystem != native_data:
        _fail("invalid-artifact", "filesystem and native distribution info differ")
    expected: dict[str, object] = {
        "name": worker.profile_name,
        "version": DISTRIBUTION_VERSION,
        "description": worker.description,
        "license": "MIT",
        "distribution_owned": list(plan.distribution_owned),
    }
    if any(native_data.get(key) != value for key, value in expected.items()):
        _fail("content-mismatch", "distribution manifest differs from the plan")
    return _canonical_source(plan, worker, native_data.get("source"))


def validate_installed_profile(
    plan: InstallPlan,
    worker: WorkerInstallPlan,
    detection: HermesDetection,
    *,
    observation_path: Path,
    observation_name: str,
    distribution_info: Mapping[str, object],
    description: str,
) -> InstalledProfileReadback:
    """Statically prove one confirmed-created profile; never executes Hermes commands."""
    _require_descriptor_capabilities()
    root_fd: int | None = None
    profile_fd: int | None = None
    try:
        hermes = plan.hermes
        if hermes is None or plan.installation_id is None:
            _fail("identity-mismatch", "plan lacks installation identity")
        home = detection.hermes_home.resolve(strict=True)
        root = detection.profiles_root.resolve(strict=True)
        if detection.hermes_home != home or detection.profiles_root != root:
            _fail("unsafe-path", "Hermes paths are not canonical")
        if hermes.home != home or hermes.profiles_root != root:
            _fail("unsafe-path", "Hermes root changed since planning")
        if root.parent != home or root.name != "profiles":
            _fail("unsafe-path", "profiles root is not the canonical Hermes child")
        if (
            observation_name != worker.profile_name
            or observation_name == "default"
            or observation_path.parent != root
            or observation_path.name != observation_name
        ):
            _fail("unsafe-path", "observed profile is not the planned direct child")

        root_fd = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        profile_fd = os.open(
            observation_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fd,
        )
        profile_info = os.fstat(profile_fd)
        if not stat.S_ISDIR(profile_info.st_mode):
            _fail("unsafe-path", "observed profile is not a directory")
        current = os.stat(observation_name, dir_fd=root_fd, follow_symlinks=False)
        if (
            current.st_dev != profile_info.st_dev
            or current.st_ino != profile_info.st_ino
            or not stat.S_ISDIR(current.st_mode)
        ):
            _fail("unsafe-path", "observed profile changed while opening")

        snapshots = {name: _read_regular(profile_fd, name) for name in _OWNED_ARTIFACTS}
        for name in ("config.yaml", "SOUL.md"):
            content = snapshots[name][0]
            seal = _seal(plan, worker, name)
            if len(content) != seal.size or hashlib.sha256(content).hexdigest() != seal.sha256:
                _fail("content-mismatch", f"{name} differs from sealed staging")

        source = _validate_distribution(
            plan, worker, snapshots["distribution.yaml"][0], distribution_info
        )
        marker_bytes, marker_info = snapshots["agentporter-profile.json"]
        try:
            marker = MarkerV1.model_validate_json(marker_bytes)
        except ValidationError:
            _fail("invalid-artifact", "marker schema is invalid")
        if (
            marker.product_id != PRODUCT_ID
            or marker.component_id != worker.component_id
            or marker.installation_id != plan.installation_id
        ):
            _fail("identity-mismatch", "marker identity differs from plan")
        marker_seal = _seal(plan, worker, "agentporter-profile.json")
        marker_hash = hashlib.sha256(marker_bytes).hexdigest()
        if len(marker_bytes) != marker_seal.size or marker_hash != marker_seal.sha256:
            _fail("content-mismatch", "marker differs from sealed staging")
        current_marker = os.stat(
            "agentporter-profile.json", dir_fd=profile_fd, follow_symlinks=False
        )
        current_profile = os.stat(observation_name, dir_fd=root_fd, follow_symlinks=False)
        if (
            current_marker.st_dev != marker_info.st_dev
            or current_marker.st_ino != marker_info.st_ino
            or stat.S_IFMT(current_marker.st_mode) != stat.S_IFMT(marker_info.st_mode)
            or current_profile.st_dev != profile_info.st_dev
            or current_profile.st_ino != profile_info.st_ino
            or stat.S_IFMT(current_profile.st_mode) != stat.S_IFMT(profile_info.st_mode)
        ):
            _fail("unsafe-path", "profile or marker changed during readback")
        if description != worker.description:
            _fail("description-mismatch", "native description differs from worker plan")

        snapshot = CompensationSnapshot(
            hermes_home=home,
            profiles_root=root,
            path=root / observation_name,
            basename=observation_name,
            profile_device=profile_info.st_dev,
            profile_inode=profile_info.st_ino,
            profile_type=stat.S_IFMT(profile_info.st_mode),
            marker_device=marker_info.st_dev,
            marker_inode=marker_info.st_ino,
            marker_type=stat.S_IFMT(marker_info.st_mode),
            marker_sha256=marker_hash,
            product_id=marker.product_id,
            component_id=marker.component_id,
            installation_id=marker.installation_id,
            source=source,
        )
        return InstalledProfileReadback("verified-compensable", worker, snapshot)
    except ReadbackError:
        raise
    except OSError as error:
        _fail("unsafe-path", f"filesystem verification failed: {type(error).__name__}")
    except Exception as error:
        _fail("invalid-artifact", f"readback failed: {type(error).__name__}")
    finally:
        if profile_fd is not None:
            os.close(profile_fd)
        if root_fd is not None:
            os.close(root_fd)


def validate_readback_collection(
    plan: InstallPlan, readbacks: tuple[InstalledProfileReadback, ...]
) -> tuple[InstalledProfileReadback, ...]:
    """Validate the transaction-wide component set without mutating the filesystem."""
    expected = {worker.component_id for worker in plan.workers}
    components = [item.snapshot.component_id for item in readbacks]
    if (
        plan.installation_id is None
        or len(readbacks) != len(plan.workers)
        or len(set(components)) != len(components)
        or set(components) != expected
        or any(item.snapshot.installation_id != plan.installation_id for item in readbacks)
    ):
        _fail("collection-mismatch", "readbacks do not form the planned installation set")
    return readbacks
