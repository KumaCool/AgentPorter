from agentporter.runtime_binding import RuntimeBindingPlan


def test_runtime_binding_plan_requires_complete_nonsecret_route() -> None:
    plan = RuntimeBindingPlan.from_values(
        portable_id="luna_worker",
        component_id="component-luna",
        current_profile_name="luna_worker",
        expected_model="gpt-5.6-luna",
        provider_id="custom",
        endpoint_value="https://inference.invalid/v1",
        credential_grant_kind="profile-auth",
        credential_state="operator-authorized",
        hermes_version="0.20.0",
    )

    assert plan.provider_id == "custom"
    assert plan.endpoint_digest
    assert "inference.invalid" not in repr(plan)
    assert "inference.invalid" not in str(plan.safe_receipt())
