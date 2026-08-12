import json
from dataclasses import fields

import pytest

from agentporter.runtime_binding import (
    RuntimeBindingPlan,
    binding_fingerprint,
    evaluate_binding_gate,
)

PRIVATE_ENDPOINT = "https://user:pass@10.23.4.5/private/v1"
PRIVATE_KEY = "sk-private-sentinel"
PRIVATE_PATH = "/home/private-user/.hermes/auth.json"


def plan(**changes: object) -> RuntimeBindingPlan:
    values: dict[str, object] = {
        "portable_id": "luna_worker",
        "component_id": "component-luna",
        "current_profile_name": "luna_worker",
        "expected_model": "gpt-5.6-luna",
        "provider_id": "custom",
        "endpoint_value": PRIVATE_ENDPOINT,
        "credential_grant_kind": "profile-auth",
        "credential_state": "operator-authorized",
        "hermes_version": "0.20.0",
        "config_digest": "config-digest",
    }
    values.update(changes)
    return RuntimeBindingPlan.from_values(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("provider", "endpoint", "credential", "expected"),
    [
        (None, PRIVATE_ENDPOINT, "operator-authorized", "configuration-required"),
        ("custom", None, "operator-authorized", "configuration-required"),
        ("custom", "not-a-url", "operator-authorized", "configuration-required"),
        ("custom", PRIVATE_ENDPOINT, "unresolved", "credential-required"),
        ("custom", PRIVATE_ENDPOINT, None, "credential-required"),
    ],
)
def test_incomplete_binding_stops_before_runner_and_creates_no_temporary_evidence(
    provider: str | None,
    endpoint: str | None,
    credential: str | None,
    expected: str,
) -> None:
    calls = 0

    def runner() -> None:
        nonlocal calls
        calls += 1

    result = evaluate_binding_gate(
        provider_id=provider,
        endpoint_value=endpoint,
        credential_state=credential,
        probe_supported=True,
        runner=runner,
    )

    assert result.status == expected
    assert result.temporary_evidence_created is False
    assert calls == 0


def test_unsupported_probe_stops_before_runner() -> None:
    called = False

    def runner() -> None:
        nonlocal called
        called = True

    result = evaluate_binding_gate(
        provider_id="custom",
        endpoint_value=PRIVATE_ENDPOINT,
        credential_state="operator-authorized",
        probe_supported=False,
        runner=runner,
    )
    assert result.status == "probe-unsupported"
    assert result.temporary_evidence_created is False
    assert called is False


def test_binding_plan_receipt_repr_error_and_fingerprint_are_secret_safe() -> None:
    item = plan()
    receipt_json = json.dumps(item.safe_receipt().as_dict(), sort_keys=True)
    fingerprint = binding_fingerprint(item)
    exposed = "\n".join((repr(item), repr(item.safe_receipt()), receipt_json, fingerprint))

    for sentinel in (PRIVATE_ENDPOINT, "10.23.4.5", "pass", PRIVATE_KEY, PRIVATE_PATH):
        assert sentinel not in exposed
    assert "endpoint_value" not in {field.name for field in fields(item.safe_receipt())}
    assert len(fingerprint) == 64

    with pytest.raises(ValueError) as caught:
        RuntimeBindingPlan.from_values(
            portable_id="luna_worker",
            component_id="component-luna",
            current_profile_name="luna_worker",
            expected_model="gpt-5.6-luna",
            provider_id="custom",
            endpoint_value=f"file://{PRIVATE_PATH}?key={PRIVATE_KEY}",
            credential_grant_kind="profile-auth",
            credential_state="operator-authorized",
            hermes_version="0.20.0",
            config_digest="wrong",
        )
    assert PRIVATE_ENDPOINT not in str(caught.value)
    assert PRIVATE_PATH not in str(caught.value)


def test_binding_fingerprint_changes_for_safe_runtime_identity_changes() -> None:
    original = plan()
    assert binding_fingerprint(plan(expected_model="other")) != binding_fingerprint(original)
    assert binding_fingerprint(plan(hermes_version="0.21.0")) != binding_fingerprint(original)
    assert binding_fingerprint(plan(config_digest="other-config")) != binding_fingerprint(original)


def test_lifecycle_contracts_never_invoke_model_runner() -> None:
    for operation in ("install", "update", "uninstall", "static-readback"):
        calls = 0

        def runner() -> None:
            nonlocal calls
            calls += 1

        result = evaluate_binding_gate(
            provider_id="custom",
            endpoint_value=PRIVATE_ENDPOINT,
            credential_state="operator-authorized",
            probe_supported=True,
            runner=runner,
            lifecycle_operation=operation,
        )
        assert result.status == "canary-required"
        assert calls == 0
