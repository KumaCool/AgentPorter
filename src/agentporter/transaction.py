from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .compensation import (
    CompensationResult,
    CompensationStatus,
    DetectionProvider,
    compensate_profiles,
)
from .execution import CommandExecutor
from .install_workflow import (
    CollectionValidator,
    DescriptionReader,
    DescriptionSetter,
    DistributionInfoReader,
    InstallWorkflowResult,
    InstallWorkflowStatus,
    ProfileEnumerator,
    install_confirmed_plan,
)
from .installation import AttemptClassification
from .planning import InstallPlan


class InstallTransactionStatus(StrEnum):
    INSTALLED = "installed"
    INSTALLATION_FAILED_COMPENSATED = "installation-failed-compensated"
    COMPENSATION_INCOMPLETE = "compensation-incomplete"


@dataclass(frozen=True)
class InstallTransactionResult:
    status: InstallTransactionStatus
    install: InstallWorkflowResult
    compensation: CompensationResult | None
    remaining_uncertain: tuple[str, ...]


def execute_install_transaction(
    plan: InstallPlan,
    *,
    executor: CommandExecutor,
    env: Mapping[str, str],
    enumerate_profiles: ProfileEnumerator,
    set_description: DescriptionSetter,
    read_distribution_info: DistributionInfoReader,
    read_description: DescriptionReader,
    current_detection: DetectionProvider,
    validate_collection: CollectionValidator | None = None,
) -> InstallTransactionResult:
    """Run the install portion of a previously confirmed, live plan."""

    def compensate(install: InstallWorkflowResult) -> CompensationResult:
        return compensate_profiles(
            install.verified_compensable,
            current_detection=current_detection,
            executor=executor,
            env=env,
            enumerate_profiles=enumerate_profiles,
        )

    try:
        if validate_collection is None:
            install = install_confirmed_plan(
                plan,
                executor=executor,
                env=env,
                enumerate_profiles=enumerate_profiles,
                set_description=set_description,
                read_distribution_info=read_distribution_info,
                read_description=read_description,
            )
        else:
            install = install_confirmed_plan(
                plan,
                executor=executor,
                env=env,
                enumerate_profiles=enumerate_profiles,
                set_description=set_description,
                read_distribution_info=read_distribution_info,
                read_description=read_description,
                validate_collection=validate_collection,
            )
    except BaseException as error:
        state = getattr(error, "install_workflow_result", None)
        if not isinstance(state, InstallWorkflowResult):
            error.add_note("AgentPorter compensation was not attempted; install state unavailable")
            raise
        try:
            outcome = compensate(state)
        except BaseException:
            error.add_note("AgentPorter compensation interrupted; outcome is not verified")
        else:
            if outcome.status is CompensationStatus.COMPENSATED:
                error.add_note("AgentPorter compensation completed and was verified")
            else:
                error.add_note("AgentPorter compensation incomplete; manual review required")
        raise
    if install.status is InstallWorkflowStatus.SUCCEEDED:
        return InstallTransactionResult(
            InstallTransactionStatus.INSTALLED,
            install,
            None,
            (),
        )
    compensation = compensate(install)
    verified_names = {item.worker.profile_name for item in install.verified_compensable}
    uncertain: list[str] = []
    for attempt in install.confirmed_created:
        if attempt.profile_name not in verified_names and attempt.profile_name not in uncertain:
            uncertain.append(attempt.profile_name)
    for attempt in install.attempts:
        if (
            attempt.classification is AttemptClassification.UNCERTAIN_REMNANT
            and attempt.profile_name not in uncertain
        ):
            uncertain.append(attempt.profile_name)
    status = (
        InstallTransactionStatus.INSTALLATION_FAILED_COMPENSATED
        if compensation.status is CompensationStatus.COMPENSATED
        else InstallTransactionStatus.COMPENSATION_INCOMPLETE
    )
    return InstallTransactionResult(status, install, compensation, tuple(uncertain))
