from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Never, Protocol, cast

from .execution import CommandOutcome, CommandStatus
from .hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from .installation import AttemptClassification, InstallAttempt, SafeCommandResult
from .planning import InstallPlan, WorkerInstallPlan, revalidate_install_plan
from .readback import (
    InstalledProfileReadback,
    validate_installed_profile,
    validate_readback_collection,
)


class InstallWorkflowStatus(StrEnum):
    ATTEMPT_NO_REMNANT = "attempt-no-remnant"
    UNCERTAIN_REMNANT = "uncertain-remnant"
    READBACK_FAILED = "readback-failed"
    DESCRIPTION_FAILED = "description-failed"
    COLLECTION_FAILED = "collection-failed"
    SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class InstallWorkflowResult:
    status: InstallWorkflowStatus
    attempts: tuple[InstallAttempt, ...]
    confirmed_created: tuple[InstallAttempt, ...]
    verified_compensable: tuple[InstalledProfileReadback, ...]
    reason: str


class _StateCarrier(Protocol):
    install_workflow_result: InstallWorkflowResult


class Executor(Protocol):
    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome: ...


class ProfileEnumerator(Protocol):
    def __call__(self) -> Sequence[ProfileEntry]: ...


class DescriptionSetter(Protocol):
    def __call__(self, worker: WorkerInstallPlan, *, env: Mapping[str, str]) -> CommandOutcome: ...


class DistributionInfoReader(Protocol):
    def __call__(
        self, worker: WorkerInstallPlan, *, env: Mapping[str, str]
    ) -> Mapping[str, object]: ...


class DescriptionReader(Protocol):
    def __call__(self, worker: WorkerInstallPlan, *, env: Mapping[str, str]) -> str: ...


CollectionValidator = Callable[
    [InstallPlan, tuple[InstalledProfileReadback, ...]],
    tuple[InstalledProfileReadback, ...],
]


def _target(entries: Sequence[ProfileEntry], name: str) -> tuple[ProfileEntry, ...]:
    return tuple(entry for entry in entries if entry.name == name)


def _detection(plan: InstallPlan, entries: tuple[ProfileEntry, ...]) -> HermesDetection:
    assert plan.hermes is not None
    required = frozenset({"install", "delete", "describe", "list", "info"})
    return HermesDetection(
        executable=plan.hermes.executable,
        version=plan.hermes.version,
        hermes_home=plan.hermes.home,
        profiles_root=plan.hermes.profiles_root,
        capabilities=HermesCapabilities(required, frozenset()),
        profile_entries=entries,
    )


def _classify(
    plan: InstallPlan,
    worker: WorkerInstallPlan,
    command: CommandOutcome,
    before: tuple[ProfileEntry, ...],
    after: tuple[ProfileEntry, ...] | None,
) -> tuple[AttemptClassification, str]:
    if after is None:
        return AttemptClassification.UNCERTAIN_REMNANT, "post-attempt enumeration failed"
    before_target = _target(before, worker.profile_name)
    after_target = _target(after, worker.profile_name)
    if before_target or len(after_target) > 1:
        return AttemptClassification.UNCERTAIN_REMNANT, "profile observations are contradictory"
    assert plan.hermes is not None
    created = (
        len(after_target) == 1
        and after_target[0].kind is ProfileEntryKind.PROFILE
        and after_target[0].path == plan.hermes.profiles_root / worker.profile_name
    )
    if command.status is CommandStatus.SUCCEEDED and created:
        return (
            AttemptClassification.CONFIRMED_CREATED,
            "command succeeded and target newly appeared",
        )
    if command.status is not CommandStatus.SUCCEEDED and not after_target:
        return (
            AttemptClassification.ATTEMPT_FAILED_NO_REMNANT,
            "command did not succeed and target remains absent",
        )
    return AttemptClassification.UNCERTAIN_REMNANT, "creation or identity readback is uncertain"


def _result(
    status: InstallWorkflowStatus,
    attempts: list[InstallAttempt],
    confirmed: list[InstallAttempt],
    verified: list[InstalledProfileReadback],
    reason: str,
) -> InstallWorkflowResult:
    return InstallWorkflowResult(status, tuple(attempts), tuple(confirmed), tuple(verified), reason)


def _propagate(
    error: BaseException,
    status: InstallWorkflowStatus,
    attempts: list[InstallAttempt],
    confirmed: list[InstallAttempt],
    verified: list[InstalledProfileReadback],
) -> Never:
    state = _result(
        status,
        attempts,
        confirmed,
        verified,
        "workflow interrupted",
    )
    try:
        cast(_StateCarrier, error).install_workflow_result = state
    except Exception:
        error.add_note("install workflow state could not be attached")
    raise error


def install_confirmed_plan(
    plan: InstallPlan,
    *,
    executor: Executor,
    env: Mapping[str, str],
    enumerate_profiles: ProfileEnumerator,
    set_description: DescriptionSetter,
    read_distribution_info: DistributionInfoReader,
    read_description: DescriptionReader,
    revalidate: Callable[[InstallPlan, object], bool] | None = None,
    validate_collection: CollectionValidator = validate_readback_collection,
) -> InstallWorkflowResult:
    """Install, describe, and verify each worker before attempting the next worker."""
    attempts: list[InstallAttempt] = []
    confirmed: list[InstallAttempt] = []
    verified: list[InstalledProfileReadback] = []
    if plan.hermes is None or plan.staging_dir is None:
        return _result(
            InstallWorkflowStatus.ATTEMPT_NO_REMNANT,
            attempts,
            confirmed,
            verified,
            "install plan is incomplete",
        )
    validate = revalidate_install_plan if revalidate is None else revalidate
    confirmed_names: set[str] = set()
    for worker in plan.workers:
        before: tuple[ProfileEntry, ...]
        try:
            before = tuple(enumerate_profiles())
        except Exception:
            return _result(
                InstallWorkflowStatus.ATTEMPT_NO_REMNANT,
                attempts,
                confirmed,
                verified,
                "pre-attempt enumeration failed",
            )
        except BaseException as error:
            _propagate(
                error, InstallWorkflowStatus.ATTEMPT_NO_REMNANT, attempts, confirmed, verified
            )
        current_entries = tuple(entry for entry in before if entry.name not in confirmed_names)
        if not validate(plan, _detection(plan, current_entries)) or _target(
            before, worker.profile_name
        ):
            return _result(
                InstallWorkflowStatus.ATTEMPT_NO_REMNANT,
                attempts,
                confirmed,
                verified,
                "pre-attempt revalidation failed",
            )
        argv = (
            str(plan.hermes.executable),
            "profile",
            "install",
            str(plan.staging_dir / worker.profile_name),
            "--yes",
        )
        pending: BaseException | None = None
        command: CommandOutcome | None = None
        try:
            command = executor.run(argv, env=env)
        except BaseException as error:
            pending = error
        try:
            after: tuple[ProfileEntry, ...] | None = tuple(enumerate_profiles())
        except BaseException as post_error:
            after = None
            if pending is None and not isinstance(post_error, Exception):
                pending = post_error
        if pending is not None:
            pending.add_note("post-attempt classification: uncertain-remnant")
            _propagate(
                pending, InstallWorkflowStatus.UNCERTAIN_REMNANT, attempts, confirmed, verified
            )
        assert command is not None
        classification, reason = _classify(plan, worker, command, before, after)
        attempt = InstallAttempt(
            worker.portable_id,
            worker.profile_name,
            classification,
            SafeCommandResult(command.status, command.returncode),
            reason,
            before,
            after,
        )
        attempts.append(attempt)
        if classification is not AttemptClassification.CONFIRMED_CREATED:
            status = (
                InstallWorkflowStatus.ATTEMPT_NO_REMNANT
                if classification is AttemptClassification.ATTEMPT_FAILED_NO_REMNANT
                else InstallWorkflowStatus.UNCERTAIN_REMNANT
            )
            return _result(status, attempts, confirmed, verified, reason)
        confirmed.append(attempt)
        confirmed_names.add(worker.profile_name)

        try:
            description_outcome = set_description(worker, env=env)
        except BaseException as error:
            if not isinstance(error, Exception):
                _propagate(
                    error,
                    InstallWorkflowStatus.DESCRIPTION_FAILED,
                    attempts,
                    confirmed,
                    verified,
                )
            return _result(
                InstallWorkflowStatus.DESCRIPTION_FAILED,
                attempts,
                confirmed,
                verified,
                "native description setter failed",
            )
        if description_outcome.status is not CommandStatus.SUCCEEDED:
            return _result(
                InstallWorkflowStatus.DESCRIPTION_FAILED,
                attempts,
                confirmed,
                verified,
                "native description setter did not succeed",
            )
        assert after is not None
        observation = _target(after, worker.profile_name)[0]
        try:
            distribution = read_distribution_info(worker, env=env)
            description = read_description(worker, env=env)
            readback = validate_installed_profile(
                plan,
                worker,
                _detection(plan, after),
                observation_path=observation.path,
                observation_name=observation.name,
                distribution_info=distribution,
                description=description,
            )
        except BaseException as error:
            if not isinstance(error, Exception):
                _propagate(
                    error,
                    InstallWorkflowStatus.READBACK_FAILED,
                    attempts,
                    confirmed,
                    verified,
                )
            return _result(
                InstallWorkflowStatus.READBACK_FAILED,
                attempts,
                confirmed,
                verified,
                "installed profile readback failed",
            )
        verified.append(readback)

    try:
        validate_collection(plan, tuple(verified))
    except BaseException as error:
        if not isinstance(error, Exception):
            _propagate(
                error, InstallWorkflowStatus.COLLECTION_FAILED, attempts, confirmed, verified
            )
        return _result(
            InstallWorkflowStatus.COLLECTION_FAILED,
            attempts,
            confirmed,
            verified,
            "installed profile collection failed",
        )
    return _result(
        InstallWorkflowStatus.SUCCEEDED,
        attempts,
        confirmed,
        verified,
        "all profiles installed and verified",
    )
