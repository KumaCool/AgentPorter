from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agentporter.plan06_role_bindings import (
    BindingSelection,
    CredentialGrantSelection,
    Responsibility,
    RoleBindingSet,
    authorize_responsibility_route,
    classify_credential_grant,
)
from agentporter.readiness import ReadinessEvidence, RuntimeBinding
from agentporter.runtime_binding import RuntimeBindingPlan, binding_fingerprint

COMPONENTS = {
    "bounded_worker": "5c7f978c-a9a6-4cec-98fa-e65bbf8101cd",
    "mechanical_worker": "7dab98fb-9ac0-44fa-90fb-4a4f30e1470c",
    "agentporter_orchestrator": "ee21f7f8-5a9d-4cf2-9e57-2508034cadc7",
}


def selection(role: str, *, model: str | None = None) -> BindingSelection:
    return BindingSelection.create(
        portable_id=role,
        component_id=COMPONENTS[role],
        profile_name=f"custom-{role.replace('_', '-')}",
        model=model or f"operator/{role}",
        provider=f"provider-{role}",
        endpoint=f"https://{role.replace('_', '-')}.example.test/v1",
        credential_grant=CredentialGrantSelection.PROFILE_AUTH,
    )


def test_three_profile_sealed_binding_set_is_closed_explicit_and_secret_safe() -> None:
    bindings = RoleBindingSet.create(
        expected_components=COMPONENTS,
        selections={role: selection(role) for role in COMPONENTS},
    )

    assert tuple(item.portable_id for item in bindings.items) == tuple(COMPONENTS)
    assert len({item.model for item in bindings.items}) == 3
    assert all(item.model and item.provider for item in bindings.items)
    safe = bindings.safe_summary()
    assert all(item.endpoint not in repr(bindings) + repr(safe) for item in bindings.items)
    assert all(row["endpoint"].startswith("sha256:") for row in safe)

    with pytest.raises(ValueError, match="closed"):
        RoleBindingSet.create(
            expected_components=COMPONENTS,
            selections={role: selection(role) for role in tuple(COMPONENTS)[:-1]},
        )
    with pytest.raises(ValueError, match="model"):
        replace(selection("bounded_worker"), model=" ")


def test_binding_set_fingerprint_covers_public_route_fields_without_endpoint_disclosure() -> (
    None
):
    original = RoleBindingSet.create(
        expected_components=COMPONENTS,
        selections={role: selection(role) for role in COMPONENTS},
    )
    changed = RoleBindingSet.create(
        expected_components=COMPONENTS,
        selections={
            **{role: selection(role) for role in COMPONENTS},
            "bounded_worker": selection("bounded_worker", model="operator/other-model"),
        },
    )
    assert original.fingerprint != changed.fingerprint
    assert all(item.endpoint not in original.fingerprint for item in original.items)


def test_provider_definition_grant_classification_is_explicit_and_never_cross_worker() -> None:
    assert (
        classify_credential_grant(
            portable_id="bounded_worker",
            existing_profile_definition=True,
            requested=CredentialGrantSelection.EXISTING_PROFILE_DEFINITION,
        )
        == "existing-profile-definition"
    )
    assert (
        classify_credential_grant(
            portable_id="agentporter_orchestrator",
            existing_profile_definition=False,
            requested=CredentialGrantSelection.EXPLICIT_SOURCE_INHERITANCE,
            source_profile_kind="main-default",
        )
        == "explicit-source-inheritance"
    )
    assert (
        classify_credential_grant(
            portable_id="mechanical_worker",
            existing_profile_definition=False,
            requested=None,
        )
        == "configuration-required"
    )
    with pytest.raises(ValueError, match="orchestrator"):
        classify_credential_grant(
            portable_id="agentporter_orchestrator",
            existing_profile_definition=False,
            requested=CredentialGrantSelection.EXPLICIT_SOURCE_INHERITANCE,
            source_profile_kind="worker",
        )
    with pytest.raises(ValueError, match="own definition"):
        classify_credential_grant(
            portable_id="mechanical_worker",
            existing_profile_definition=False,
            requested=CredentialGrantSelection.EXISTING_PROFILE_DEFINITION,
        )


@pytest.mark.parametrize("model", ["tiny-local", "frontier-remote"])
def test_model_choice_never_changes_responsibility_authority(model: str) -> None:
    assert authorize_responsibility_route(
        responsibility=Responsibility.BOUNDED,
        requested_work=Responsibility.BOUNDED,
        model=model,
    )
    assert authorize_responsibility_route(
        responsibility=Responsibility.MECHANICAL,
        requested_work=Responsibility.MECHANICAL,
        model=model,
    )
    with pytest.raises(ValueError, match="responsibility"):
        authorize_responsibility_route(
            responsibility=Responsibility.MECHANICAL,
            requested_work=Responsibility.BOUNDED,
            model=model,
        )
    with pytest.raises(ValueError, match="implementation"):
        authorize_responsibility_route(
            responsibility=Responsibility.ORCHESTRATOR,
            requested_work=Responsibility.BOUNDED,
            model=model,
        )


def test_runtime_fingerprint_and_readiness_invalidate_on_model_provider_or_endpoint_change() -> (
    None
):
    plan = RuntimeBindingPlan.from_values(
        portable_id="bounded_worker",
        component_id=COMPONENTS["bounded_worker"],
        current_profile_name="renamed-bounded",
        expected_model="operator/model-a",
        provider_id="provider-a",
        endpoint_value="https://one.example.test/v1",
        credential_grant_kind="profile-auth",
        credential_state="operator-authorized",
        hermes_version="0.20.0",
        config_digest="config-a",
    )
    binding = RuntimeBinding(
        portable_id=plan.portable_id,
        component_id=plan.component_id,
        current_profile_name=plan.current_profile_name,
        expected_model=plan.expected_model,
        expected_provider=plan.provider_id,
        provider_source_kind="profile-config",
        binding_fingerprint=binding_fingerprint(plan),
        config_digest=plan.config_digest,
        endpoint_digest=plan.endpoint_digest,
    )
    started = datetime(2026, 8, 14, tzinfo=UTC)
    evidence = ReadinessEvidence(
        status="runtime-ready",
        safe_reason_code="runtime-ready",
        binding=binding,
        hermes_version=plan.hermes_version,
        probe_started_at=started,
        probe_finished_at=started + timedelta(seconds=1),
        actual_model=plan.expected_model,
        actual_provider=plan.provider_id,
        api_calls=1,
        response_contract_passed=True,
        tool_calls_observed=0,
        fresh_until=started + timedelta(minutes=5),
    )

    assert evidence.valid_after_lifecycle(
        "update", expected_provider="provider-a", endpoint_digest=plan.endpoint_digest
    )
    assert not evidence.valid_after_lifecycle("update", expected_model="operator/model-b")
    assert not evidence.valid_after_lifecycle("update", expected_provider="provider-b")
    assert not evidence.valid_after_lifecycle("update", endpoint_digest="changed")
