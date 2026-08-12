from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

import yaml
from pydantic import ValidationError

from .hermes import DetectionError, HermesDetection, ProfileEntryKind
from .identity import COMPONENT_IDS, INITIAL_PROFILE_NAMES, INSTALL_COMPONENT_IDS
from .manifest import load_manifest
from .models import WorkersManifest
from .render import DISTRIBUTION_OWNED, render_staging
from .security import StagingViolation, scan_staging
from .uninstall_discovery import DiscoveryResult, DiscoveryStatus

PlanStatus = Literal["ready", "configuration-required", "unsupported", "conflict", "invalid"]
RuntimeConfiguration = Literal[
    "configured-but-runtime-unvalidated",
    "selected-but-runtime-unvalidated",
    "configuration-required",
]
CleanupStatus = Literal["cleaned", "already-absent", "refused", "failed"]


class Detector(Protocol):
    def __call__(self) -> HermesDetection: ...


@dataclass(frozen=True)
class HermesPlanTarget:
    executable: Path
    version: str
    home: Path
    profiles_root: Path


@dataclass(frozen=True)
class WorkerInstallPlan:
    portable_id: str
    component_id: str
    profile_name: str
    display_name: str
    model: str
    provider: str | None
    reasoning_effort: str
    description: str
    installable: bool
    runtime_configuration: RuntimeConfiguration
    status: PlanStatus
    reason: str


@dataclass(frozen=True)
class StagingIdentity:
    canonical_parent: Path
    basename: str
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True)
class ArtifactSeal:
    relative_path: str
    sha256: str
    size: int
    device: int
    inode: int
    file_type: int


@dataclass(frozen=True)
class CleanupOutcome:
    status: CleanupStatus
    reason: str
    residual_path: Path | None = field(default=None, repr=False)


@dataclass(frozen=True)
class InstallPlan:
    hermes: HermesPlanTarget | None
    installation_id: str | None
    workers: tuple[WorkerInstallPlan, ...]
    staging_dir: Path | None = field(repr=False)
    staging_identity: StagingIdentity | None = field(repr=False)
    artifacts: tuple[ArtifactSeal, ...]
    distribution_owned: tuple[str, ...]
    installable: bool
    status: PlanStatus
    reason: str
    cleanup_outcome: CleanupOutcome | None
    copied_data: tuple[()]
    modified_data: tuple[()]
    model_calls: Literal[False]
    runtime_validated: Literal[False]
    compensation_boundary: Literal["no-install-attempted"]
    fingerprint: str
    confirmation_token: str


def _apply_provider_selection(
    manifest: WorkersManifest, selection: Mapping[str, str] | None
) -> tuple[WorkersManifest, frozenset[str]]:
    if selection is None:
        return manifest, frozenset()
    if not set(selection) <= set(manifest.workers):
        raise ValueError("provider selection is not closed")
    normalized: dict[str, str] = {}
    for portable_id, provider in selection.items():
        if not (trimmed := provider.strip()):
            raise ValueError("provider selection is empty")
        normalized[portable_id] = trimmed
    workers = {
        portable_id: worker.model_copy(
            update={"provider": normalized[portable_id]} if portable_id in normalized else {}
        )
        for portable_id, worker in manifest.workers.items()
    }
    return manifest.model_copy(update={"workers": workers}), frozenset(normalized)


def _worker_plans(
    manifest: WorkersManifest, selected: frozenset[str] = frozenset()
) -> tuple[WorkerInstallPlan, ...]:
    plans: list[WorkerInstallPlan] = []
    for portable_id, worker in manifest.workers.items():
        if worker.provider is None:
            status: PlanStatus = "configuration-required"
            runtime: RuntimeConfiguration = "configuration-required"
            reason = "explicit provider configuration is required"
        elif portable_id in selected:
            status = "ready"
            runtime = "selected-but-runtime-unvalidated"
            reason = "selected provider is static-only and runtime-unvalidated"
        else:
            status = "ready"
            runtime = "configured-but-runtime-unvalidated"
            reason = "static provider and model fields are complete; runtime not validated"
        plans.append(
            WorkerInstallPlan(
                portable_id=portable_id,
                component_id=INSTALL_COMPONENT_IDS[portable_id],
                profile_name=INITIAL_PROFILE_NAMES[portable_id],
                display_name=worker.display_name,
                model=worker.model,
                provider=worker.provider,
                reasoning_effort=worker.reasoning_effort,
                description=worker.description,
                installable=True,
                runtime_configuration=runtime,
                status=status,
                reason=reason,
            )
        )
    return tuple(plans)


def _fingerprint(plan: InstallPlan) -> str:
    payload = asdict(plan)
    payload.pop("fingerprint")
    payload.pop("confirmation_token")
    canonical = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _seal(plan: InstallPlan) -> InstallPlan:
    fingerprint = _fingerprint(plan)
    return replace(plan, fingerprint=fingerprint, confirmation_token=fingerprint)


def _base_plan(
    detection: HermesDetection | None,
    *,
    workers: tuple[WorkerInstallPlan, ...] = (),
    installation_id: str | None = None,
    staging_dir: Path | None = None,
    staging_identity: StagingIdentity | None = None,
    artifacts: tuple[ArtifactSeal, ...] = (),
    installable: bool = False,
    cleanup_outcome: CleanupOutcome | None = None,
    status: PlanStatus,
    reason: str,
) -> InstallPlan:
    hermes = None
    if detection is not None:
        hermes = HermesPlanTarget(
            executable=detection.executable,
            version=detection.version,
            home=detection.hermes_home,
            profiles_root=detection.profiles_root,
        )
    return _seal(
        InstallPlan(
            hermes=hermes,
            installation_id=installation_id,
            workers=workers,
            staging_dir=staging_dir,
            staging_identity=staging_identity,
            artifacts=artifacts,
            distribution_owned=tuple(DISTRIBUTION_OWNED),
            installable=installable,
            status=status,
            reason=reason,
            cleanup_outcome=cleanup_outcome,
            copied_data=(),
            modified_data=(),
            model_calls=False,
            runtime_validated=False,
            compensation_boundary="no-install-attempted",
            fingerprint="",
            confirmation_token="",
        )
    )


def _capture_identity(path: Path) -> StagingIdentity:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("staging root is not a directory")
    return StagingIdentity(
        canonical_parent=path.parent.resolve(strict=True),
        basename=path.name,
        device=info.st_dev,
        inode=info.st_ino,
        file_type=stat.S_IFMT(info.st_mode),
    )


def _identity_matches(path: Path, identity: StagingIdentity) -> bool:
    try:
        info = path.lstat()
        parent = path.parent.resolve(strict=True)
    except OSError:
        return False
    return (
        parent == identity.canonical_parent
        and path.name == identity.basename
        and info.st_dev == identity.device
        and info.st_ino == identity.inode
        and stat.S_IFMT(info.st_mode) == identity.file_type
        and stat.S_ISDIR(info.st_mode)
    )


def _read_artifact(root_fd: int, relative_path: str) -> tuple[bytes, os.stat_result]:
    parts = Path(relative_path).parts
    if (
        not parts
        or Path(relative_path).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or "/".join(parts) != relative_path
    ):
        raise OSError("artifact relative path is not closed")
    current_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=current_fd,
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("artifact is not regular")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65536):
                chunks.append(chunk)
            return b"".join(chunks), info
        finally:
            os.close(descriptor)
    finally:
        os.close(current_fd)


def _capture_artifacts(
    path: Path, workers: tuple[WorkerInstallPlan, ...]
) -> tuple[ArtifactSeal, ...]:
    expected = sorted(
        f"{worker.profile_name}/{name}"
        for worker in workers
        for name in ("SOUL.md", "agentporter-profile.json", "config.yaml", "distribution.yaml")
    )
    root_fd = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        seals: list[ArtifactSeal] = []
        for relative in expected:
            content, info = _read_artifact(root_fd, relative)
            seals.append(
                ArtifactSeal(
                    relative,
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                    info.st_dev,
                    info.st_ino,
                    stat.S_IFMT(info.st_mode),
                )
            )
        return tuple(seals)
    finally:
        os.close(root_fd)


def _cleanup_bound(path: Path, identity: StagingIdentity) -> CleanupOutcome:
    parent_fd: int | None = None
    staging_fd: int | None = None
    quarantine_name: str | None = None
    try:
        parent_fd = os.open(
            identity.canonical_parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        initial = os.stat(identity.basename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            initial.st_dev == identity.device
            and initial.st_ino == identity.inode
            and stat.S_IFMT(initial.st_mode) == identity.file_type
            and stat.S_ISDIR(initial.st_mode)
        ):
            staging_fd = os.open(
                identity.basename,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
            opened = os.fstat(staging_fd)
            if opened.st_dev != identity.device or opened.st_ino != identity.inode:
                return CleanupOutcome("refused", "staging identity changed", path)

            quarantine_name = f".agentporter-cleanup-{uuid4().hex}"
            os.rename(
                identity.basename,
                quarantine_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            isolated = os.stat(quarantine_name, dir_fd=parent_fd, follow_symlinks=False)
            if isolated.st_dev != opened.st_dev or isolated.st_ino != opened.st_ino:
                try:
                    os.stat(identity.basename, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    with suppress(OSError):
                        os.rename(
                            quarantine_name,
                            identity.basename,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                        )
                residual = identity.canonical_parent / quarantine_name
                if not residual.exists() and not residual.is_symlink():
                    residual = path if path.exists() or path.is_symlink() else None
                return CleanupOutcome(
                    "refused", "staging identity changed during cleanup", residual
                )

            shutil.rmtree(quarantine_name, dir_fd=parent_fd)
            return CleanupOutcome("cleaned", "staging removed")
    except FileNotFoundError:
        pass
    except OSError:
        residual = (
            identity.canonical_parent / quarantine_name if quarantine_name is not None else path
        )
        if not residual.exists() and not residual.is_symlink():
            residual = None
        return CleanupOutcome("failed", "staging cleanup failed", residual)
    finally:
        if staging_fd is not None:
            os.close(staging_fd)
        if parent_fd is not None:
            os.close(parent_fd)

    try:
        entries = tuple(identity.canonical_parent.iterdir())
    except OSError:
        entries = ()
    for entry in entries:
        try:
            info = entry.lstat()
        except OSError:
            continue
        if info.st_dev == identity.device and info.st_ino == identity.inode:
            return CleanupOutcome("refused", "staging identity moved or changed", entry)
    if path.exists() or path.is_symlink():
        return CleanupOutcome("refused", "staging identity changed", path)
    return CleanupOutcome("already-absent", "staging already absent")


def plan_installation(
    detection: HermesDetection,
    manifest_path: Path,
    *,
    staging_parent: Path,
    installation_id_factory: Callable[[], UUID] = uuid4,
    staging_scanner: Callable[[Path], object] = scan_staging,
    provider_selection: Mapping[str, str] | None = None,
    existing_installation: DiscoveryResult | None = None,
) -> InstallPlan:
    try:
        manifest = load_manifest(manifest_path)
        manifest, selected = _apply_provider_selection(manifest, provider_selection)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError):
        return _base_plan(detection, status="invalid", reason="manifest is invalid")
    workers = _worker_plans(manifest, selected)
    installation_id_override: str | None = None
    if existing_installation is not None:
        legacy_components = set(tuple(COMPONENT_IDS.values())[:2])
        if (
            existing_installation.status is not DiscoveryStatus.READY
            or existing_installation.findings
            or {target.component_id for target in existing_installation.targets}
            != legacy_components
            or len({target.installation_id for target in existing_installation.targets}) != 1
        ):
            return _base_plan(
                detection,
                status="conflict",
                reason="legacy installation is not upgradable",
            )
        installation_id_override = existing_installation.targets[0].installation_id
        workers = tuple(
            worker for worker in workers if worker.portable_id == "agentporter_orchestrator"
        )
        manifest = manifest.model_copy(
            update={
                "workers": {
                    key: value
                    for key, value in manifest.workers.items()
                    if key == "agentporter_orchestrator"
                }
            }
        )
    if not detection.capabilities.supports_required_profile_commands:
        return _base_plan(
            detection,
            workers=workers,
            status="unsupported",
            reason="required Hermes profile commands are unavailable",
        )
    target_names = {worker.profile_name for worker in workers}
    if any(
        entry.name in target_names
        and entry.kind
        in {ProfileEntryKind.PROFILE, ProfileEntryKind.SYMLINK, ProfileEntryKind.NON_DIRECTORY}
        for entry in detection.profile_entries
    ):
        return _base_plan(
            detection,
            workers=workers,
            status="conflict",
            reason="a target initial profile name already exists",
        )
    try:
        staging_parent.resolve().relative_to(detection.hermes_home.resolve())
    except ValueError:
        pass
    else:
        return _base_plan(
            detection,
            workers=workers,
            status="invalid",
            reason="staging boundary is invalid",
        )

    staging_dir: Path | None = None
    staging_identity: StagingIdentity | None = None
    installation_id = installation_id_override or str(installation_id_factory())
    try:
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="agentporter-", dir=staging_parent))
        staging_identity = _capture_identity(staging_dir)
        render_staging(manifest, staging_dir, UUID(installation_id))
        staging_scanner(staging_dir)
        artifacts = _capture_artifacts(staging_dir, workers)
    except (OSError, UnicodeError, yaml.YAMLError, StagingViolation, ValidationError, ValueError):
        cleanup = (
            _cleanup_bound(staging_dir, staging_identity)
            if staging_dir is not None and staging_identity is not None
            else None
        )
        return _base_plan(
            detection,
            workers=workers,
            installation_id=installation_id,
            cleanup_outcome=cleanup,
            status="invalid",
            reason="staging validation failed",
        )
    except BaseException as error:
        if staging_dir is not None and staging_identity is not None:
            cleanup = _cleanup_bound(staging_dir, staging_identity)
            if cleanup.status == "failed":
                error.add_note("staging cleanup failed; a residual staging path remains")
        raise
    aggregate_status: PlanStatus = (
        "configuration-required"
        if any(worker.runtime_configuration == "configuration-required" for worker in workers)
        else "ready"
    )
    reason = (
        "one or more workers require explicit provider configuration"
        if aggregate_status == "configuration-required"
        else "static collection preflight completed"
    )
    return _base_plan(
        detection,
        workers=workers,
        installation_id=installation_id,
        staging_dir=staging_dir,
        staging_identity=staging_identity,
        artifacts=artifacts,
        installable=True,
        status=aggregate_status,
        reason=reason,
    )


def preflight_installation(
    detector: Detector,
    manifest_path: Path,
    *,
    staging_parent: Path,
    **kwargs: object,
) -> InstallPlan:
    try:
        detection = detector()
    except DetectionError:
        return _base_plan(None, status="invalid", reason="Hermes detection failed")
    return plan_installation(detection, manifest_path, staging_parent=staging_parent, **kwargs)  # type: ignore[arg-type]


def _same_detection(plan: InstallPlan, detection: HermesDetection) -> bool:
    if plan.hermes is None:
        return False
    if (
        plan.hermes.home.resolve() != detection.hermes_home.resolve()
        or plan.hermes.profiles_root.resolve() != detection.profiles_root.resolve()
        or plan.hermes.executable.resolve() != detection.executable.resolve()
        or plan.hermes.version != detection.version
        or not detection.capabilities.supports_required_profile_commands
    ):
        return False
    targets = {worker.profile_name for worker in plan.workers}
    return not any(entry.name in targets for entry in detection.profile_entries)


def revalidate_install_plan(
    plan: InstallPlan, current_detection: HermesDetection | None = None
) -> bool:
    if plan.fingerprint != _fingerprint(plan) or not plan.installable:
        return False
    if plan.staging_dir is None or plan.staging_identity is None:
        return False
    if not _identity_matches(plan.staging_dir, plan.staging_identity):
        return False
    try:
        scan_staging(plan.staging_dir)
        artifacts = _capture_artifacts(plan.staging_dir, plan.workers)
    except (OSError, UnicodeError, StagingViolation, ValidationError, ValueError):
        return False
    if artifacts != plan.artifacts:
        return False
    return current_detection is None or _same_detection(plan, current_detection)


def confirm_install_plan(plan: InstallPlan, token: str) -> bool:
    return token == plan.confirmation_token and revalidate_install_plan(plan)


def cleanup_staging(plan: InstallPlan) -> CleanupOutcome:
    if plan.staging_dir is None or plan.staging_identity is None:
        return CleanupOutcome("already-absent", "no staging was created")
    if plan.fingerprint != _fingerprint(plan):
        residual = plan.staging_dir if plan.staging_dir.exists() else None
        return CleanupOutcome("refused", "plan integrity verification failed", residual)
    return _cleanup_bound(plan.staging_dir, plan.staging_identity)
