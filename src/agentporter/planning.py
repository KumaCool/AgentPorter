from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from .hermes import DetectionError, HermesDetection, ProfileEntryKind
from .identity import COMPONENT_IDS, INITIAL_PROFILE_NAMES
from .manifest import load_manifest
from .models import WorkersManifest
from .render import DISTRIBUTION_OWNED, render_staging
from .security import scan_staging

PlanStatus = Literal["ready", "configuration-required", "unsupported", "conflict", "invalid"]


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
    status: PlanStatus
    reason: str


@dataclass(frozen=True)
class InstallPlan:
    hermes: HermesPlanTarget | None
    installation_id: str | None
    workers: tuple[WorkerInstallPlan, ...]
    staging_dir: Path | None
    distribution_owned: tuple[str, ...]
    status: PlanStatus
    reason: str
    copied_data: tuple[()]
    modified_data: tuple[()]
    model_calls: Literal[False]
    runtime_validated: Literal[False]
    compensation_boundary: Literal["no-install-attempted"]
    fingerprint: str
    confirmation_token: str


def _worker_plans(manifest: WorkersManifest) -> tuple[WorkerInstallPlan, ...]:
    plans: list[WorkerInstallPlan] = []
    for portable_id, worker in manifest.workers.items():
        if worker.provider is None:
            status: PlanStatus = "configuration-required"
            reason = "explicit provider configuration is required"
        else:
            status = "ready"
            reason = "static provider and model fields are complete; runtime not validated"
        plans.append(
            WorkerInstallPlan(
                portable_id=portable_id,
                component_id=COMPONENT_IDS[portable_id],
                profile_name=INITIAL_PROFILE_NAMES[portable_id],
                display_name=worker.display_name,
                model=worker.model,
                provider=worker.provider,
                reasoning_effort=worker.reasoning_effort,
                description=worker.description,
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
            distribution_owned=tuple(DISTRIBUTION_OWNED),
            status=status,
            reason=reason,
            copied_data=(),
            modified_data=(),
            model_calls=False,
            runtime_validated=False,
            compensation_boundary="no-install-attempted",
            fingerprint="",
            confirmation_token="",
        )
    )


def plan_installation(
    detection: HermesDetection,
    manifest_path: Path,
    *,
    staging_parent: Path,
    installation_id_factory: Callable[[], UUID] = uuid4,
    credential_reader: Callable[..., object] | None = None,
    model_caller: Callable[..., object] | None = None,
    installer: Callable[..., object] | None = None,
    staging_scanner: Callable[[Path], object] = scan_staging,
) -> InstallPlan:
    del credential_reader, model_caller, installer
    try:
        manifest = load_manifest(manifest_path)
    except Exception:
        return _base_plan(detection, status="invalid", reason="manifest is invalid")
    workers = _worker_plans(manifest)
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
    if any(worker.status != "ready" for worker in workers):
        return _base_plan(
            detection,
            workers=workers,
            status="configuration-required",
            reason="one or more workers require explicit provider configuration",
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
    installation_id = str(installation_id_factory())
    try:
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="agentporter-", dir=staging_parent))
        render_staging(manifest, staging_dir, UUID(installation_id))
        staging_scanner(staging_dir)
    except Exception:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        return _base_plan(
            detection,
            workers=workers,
            installation_id=installation_id,
            status="invalid",
            reason="staging validation failed",
        )
    return _base_plan(
        detection,
        workers=workers,
        installation_id=installation_id,
        staging_dir=staging_dir,
        status="ready",
        reason="static collection preflight completed",
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


def confirm_install_plan(plan: InstallPlan, token: str) -> bool:
    return (
        plan.status == "ready"
        and token == plan.confirmation_token
        and plan.fingerprint == _fingerprint(plan)
    )


def cleanup_staging(plan: InstallPlan) -> bool:
    if plan.staging_dir is None:
        return True
    if plan.fingerprint != _fingerprint(plan):
        return False
    try:
        shutil.rmtree(plan.staging_dir)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return not plan.staging_dir.exists()
