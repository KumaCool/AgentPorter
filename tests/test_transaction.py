from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from agentporter.compensation import CompensationResult, CompensationStatus
from agentporter.install_workflow import InstallWorkflowResult, InstallWorkflowStatus
from agentporter.installation import AttemptClassification
from agentporter.transaction import InstallTransactionStatus, execute_install_transaction


@dataclass(frozen=True)
class _Attempt:
    profile_name: str
    classification: AttemptClassification


@dataclass(frozen=True)
class _Readback:
    worker: object


def _install_result(
    status: InstallWorkflowStatus,
    *,
    confirmed: tuple[str, ...] = (),
    verified: tuple[str, ...] = (),
    attempts: tuple[str, ...] = (),
) -> InstallWorkflowResult:
    return InstallWorkflowResult(
        status=status,
        attempts=tuple(
            _Attempt(
                name,
                AttemptClassification.UNCERTAIN_REMNANT
                if "uncertain" in name
                else AttemptClassification.ATTEMPT_FAILED_NO_REMNANT,
            )
            for name in attempts
        ),  # type: ignore[arg-type]
        confirmed_created=tuple(
            _Attempt(name, AttemptClassification.CONFIRMED_CREATED) for name in confirmed
        ),  # type: ignore[arg-type]
        verified_compensable=tuple(
            _Readback(SimpleNamespace(profile_name=name)) for name in verified
        ),  # type: ignore[arg-type]
        reason="safe reason",
    )


def _kwargs() -> dict[str, Any]:
    return {
        "executor": object(),
        "env": {},
        "enumerate_profiles": lambda: (),
        "set_description": object(),
        "read_distribution_info": object(),
        "read_description": object(),
        "current_detection": object(),
    }


def test_success_returns_installed_without_compensation(monkeypatch: pytest.MonkeyPatch) -> None:
    install = _install_result(
        InstallWorkflowStatus.SUCCEEDED,
        confirmed=("one", "two"),
        verified=("one", "two"),
    )
    events: list[str] = []

    def fake_install(plan: object, **kwargs: object) -> InstallWorkflowResult:
        events.append("install")
        return install

    def forbidden_compensation(*args: object, **kwargs: object) -> CompensationResult:
        raise AssertionError("successful installation must not be compensated")

    monkeypatch.setattr("agentporter.transaction.install_confirmed_plan", fake_install)
    monkeypatch.setattr("agentporter.transaction.compensate_profiles", forbidden_compensation)

    result = execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert result.status is InstallTransactionStatus.INSTALLED
    assert result.install is install
    assert result.compensation is None
    assert result.remaining_uncertain == ()
    assert events == ["install"]


@pytest.mark.parametrize(
    "install_status",
    [
        InstallWorkflowStatus.ATTEMPT_NO_REMNANT,
        InstallWorkflowStatus.UNCERTAIN_REMNANT,
        InstallWorkflowStatus.READBACK_FAILED,
        InstallWorkflowStatus.DESCRIPTION_FAILED,
        InstallWorkflowStatus.COLLECTION_FAILED,
    ],
)
@pytest.mark.parametrize(
    ("compensation_status", "expected_status"),
    [
        (
            CompensationStatus.COMPENSATED,
            InstallTransactionStatus.INSTALLATION_FAILED_COMPENSATED,
        ),
        (
            CompensationStatus.INCOMPLETE,
            InstallTransactionStatus.COMPENSATION_INCOMPLETE,
        ),
    ],
)
def test_ordinary_failure_compensates_only_verified_and_maps_status(
    monkeypatch: pytest.MonkeyPatch,
    install_status: InstallWorkflowStatus,
    compensation_status: CompensationStatus,
    expected_status: InstallTransactionStatus,
) -> None:
    install = _install_result(
        install_status,
        confirmed=("first", "uncertain-confirmed"),
        verified=("first",),
        attempts=("first", "uncertain-attempt"),
    )
    compensation = CompensationResult(compensation_status, ())
    calls: list[tuple[str, object]] = []

    def fake_install(plan: object, **kwargs: object) -> InstallWorkflowResult:
        calls.append(("install", plan))
        return install

    def fake_compensate(readbacks: object, **kwargs: object) -> CompensationResult:
        calls.append(("compensate", readbacks))
        return compensation

    monkeypatch.setattr("agentporter.transaction.install_confirmed_plan", fake_install)
    monkeypatch.setattr("agentporter.transaction.compensate_profiles", fake_compensate)
    plan = object()

    result = execute_install_transaction(plan, **_kwargs())  # type: ignore[arg-type]

    assert result.status is expected_status
    assert result.install is install
    assert result.compensation is compensation
    assert result.remaining_uncertain == ("uncertain-confirmed", "uncertain-attempt")
    assert calls == [("install", plan), ("compensate", install.verified_compensable)]


def test_description_failure_never_compensates_confirmed_unverified_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = _install_result(
        InstallWorkflowStatus.DESCRIPTION_FAILED,
        confirmed=("confirmed-but-unverified",),
        attempts=("confirmed-but-unverified",),
    )
    observed: list[object] = []

    monkeypatch.setattr(
        "agentporter.transaction.install_confirmed_plan", lambda plan, **kwargs: install
    )

    def compensate(readbacks: object, **kwargs: object) -> CompensationResult:
        observed.append(readbacks)
        return CompensationResult(CompensationStatus.COMPENSATED, ())

    monkeypatch.setattr("agentporter.transaction.compensate_profiles", compensate)

    result = execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert observed == [()]
    assert result.remaining_uncertain == ("confirmed-but-unverified",)


def test_second_no_remnant_failure_compensates_first_verified_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = _install_result(
        InstallWorkflowStatus.ATTEMPT_NO_REMNANT,
        confirmed=("first",),
        verified=("first",),
        attempts=("first", "second"),
    )
    observed: list[object] = []
    monkeypatch.setattr(
        "agentporter.transaction.install_confirmed_plan", lambda plan, **kwargs: install
    )

    def compensate(readbacks: object, **kwargs: object) -> CompensationResult:
        observed.append(readbacks)
        return CompensationResult(CompensationStatus.COMPENSATED, ())

    monkeypatch.setattr("agentporter.transaction.compensate_profiles", compensate)

    result = execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert observed == [install.verified_compensable]
    assert result.remaining_uncertain == ()


@pytest.mark.parametrize("error", [KeyboardInterrupt("private"), SystemExit(19)])
def test_install_baseexception_compensates_attached_verified_then_propagates_original(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    install = _install_result(
        InstallWorkflowStatus.READBACK_FAILED,
        confirmed=("first", "unverified"),
        verified=("first",),
    )
    error.install_workflow_result = install  # type: ignore[attr-defined]
    events: list[str] = []

    def fail_install(plan: object, **kwargs: object) -> InstallWorkflowResult:
        events.append("install")
        raise error

    def compensate(readbacks: object, **kwargs: object) -> CompensationResult:
        events.append("compensate")
        assert readbacks == install.verified_compensable
        return CompensationResult(CompensationStatus.COMPENSATED, ())

    monkeypatch.setattr("agentporter.transaction.install_confirmed_plan", fail_install)
    monkeypatch.setattr("agentporter.transaction.compensate_profiles", compensate)

    with pytest.raises(type(error)) as raised:
        execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert raised.value is error
    assert events == ["install", "compensate"]
    assert any("compensation completed" in note for note in error.__notes__)
    assert all("first" not in note and "unverified" not in note for note in error.__notes__)


def test_compensation_baseexception_does_not_mask_install_baseexception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = KeyboardInterrupt("install private")
    compensation_error = SystemExit("compensation private")
    install = _install_result(InstallWorkflowStatus.COLLECTION_FAILED, verified=("first",))
    original.install_workflow_result = install  # type: ignore[attr-defined]

    def fail_install(plan: object, **kwargs: object) -> InstallWorkflowResult:
        raise original

    def fail_compensation(readbacks: object, **kwargs: object) -> CompensationResult:
        raise compensation_error

    monkeypatch.setattr("agentporter.transaction.install_confirmed_plan", fail_install)
    monkeypatch.setattr("agentporter.transaction.compensate_profiles", fail_compensation)

    with pytest.raises(KeyboardInterrupt) as raised:
        execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert raised.value is original
    assert any("compensation interrupted" in note for note in original.__notes__)
    assert all("private" not in note for note in original.__notes__)


def test_transaction_does_not_clean_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    install = _install_result(InstallWorkflowStatus.SUCCEEDED)
    monkeypatch.setattr(
        "agentporter.transaction.install_confirmed_plan", lambda plan, **kwargs: install
    )
    import agentporter.planning as planning

    def forbidden_cleanup(plan: object) -> object:
        raise AssertionError("transaction owns no cleanup")

    monkeypatch.setattr(planning, "cleanup_staging", forbidden_cleanup)
    result = execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert result.status is InstallTransactionStatus.INSTALLED


def test_install_baseexception_without_attached_state_propagates_with_safe_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = KeyboardInterrupt("private")

    def fail_install(plan: object, **kwargs: object) -> InstallWorkflowResult:
        raise original

    monkeypatch.setattr("agentporter.transaction.install_confirmed_plan", fail_install)
    monkeypatch.setattr(
        "agentporter.transaction.compensate_profiles",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no safe state")),
    )

    with pytest.raises(KeyboardInterrupt) as raised:
        execute_install_transaction(object(), **_kwargs())  # type: ignore[arg-type]

    assert raised.value is original
    assert any("state unavailable" in note for note in original.__notes__)
    assert all("private" not in note for note in original.__notes__)
