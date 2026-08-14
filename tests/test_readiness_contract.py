from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from agentporter.readiness import (
    ReadinessEvidence,
    RuntimeBinding,
    aggregate_readiness,
)


def binding(**changes: object) -> RuntimeBinding:
    values: dict[str, object] = {
        "portable_id": "codex_worker",
        "component_id": "component-codex",
        "current_profile_name": "codex",
        "expected_model": "gpt-5-codex",
        "expected_provider": "openai",
        "provider_source_kind": "profile-config",
        "binding_fingerprint": "binding-fingerprint",
        "config_digest": "config-digest",
    }
    values.update(changes)
    return RuntimeBinding(**values)  # type: ignore[arg-type]


def evidence(**changes: object) -> ReadinessEvidence:
    started = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "status": "runtime-ready",
        "safe_reason_code": "runtime-ready",
        "binding": binding(),
        "hermes_version": "0.20.0",
        "probe_started_at": started,
        "probe_finished_at": started + timedelta(seconds=1),
        "actual_model": "gpt-5-codex",
        "actual_provider": "openai",
        "api_calls": 1,
        "response_contract_passed": True,
        "tool_calls_observed": 0,
        "fresh_until": started + timedelta(minutes=5),
    }
    values.update(changes)
    return ReadinessEvidence(**values)  # type: ignore[arg-type]


def test_runtime_binding_is_frozen_and_has_no_secret_or_endpoint_fields() -> None:
    item = binding()
    with pytest.raises(FrozenInstanceError):
        item.expected_model = "other"  # type: ignore[misc]
    names = {field.name for field in fields(item)}
    assert {"endpoint", "api_key", "credential_path"}.isdisjoint(names)
    assert {"binding_fingerprint", "config_digest"}.issubset(names)


def test_evidence_rejects_fallback_unexpected_route_and_bad_calls() -> None:
    with pytest.raises(ValueError, match="fallback"):
        evidence(fallback_used=True)
    with pytest.raises(ValueError, match="unexpected-runtime-route"):
        evidence(actual_model="other")
    with pytest.raises(ValueError, match="unexpected-runtime-route"):
        evidence(actual_provider="other")
    with pytest.raises(ValueError, match="response-contract-failed"):
        evidence(api_calls=2)
    with pytest.raises(ValueError, match="response-contract-failed"):
        evidence(tool_calls_observed=1)


@pytest.mark.parametrize(
    "status",
    [
        "configuration-required",
        "credential-required",
        "probe-unsupported",
        "authentication-failed",
        "model-unsupported",
        "endpoint-unavailable",
        "rate-limited",
        "probe-timeout",
        "response-contract-failed",
        "unexpected-runtime-route",
    ],
)
def test_evidence_supports_full_safe_finding_family(status: str) -> None:
    item = evidence(
        status=status,
        safe_reason_code=status,
        actual_model=None,
        actual_provider=None,
        api_calls=0,
        response_contract_passed=False,
    )
    assert item.status == status


def test_failure_evidence_cannot_persist_raw_provider_error() -> None:
    assert "error" not in {field.name for field in fields(ReadinessEvidence)}


def test_freshness_requires_time_version_config_and_binding_identity() -> None:
    item = evidence()
    now = datetime(2026, 8, 12, 12, 4, 59, tzinfo=UTC)
    assert item.is_fresh(
        now,
        hermes_version="0.20.0",
        config_digest="config-digest",
        binding_fingerprint="binding-fingerprint",
    )
    assert not item.is_fresh(
        now + timedelta(seconds=1),
        hermes_version="0.20.0",
        config_digest="config-digest",
        binding_fingerprint="binding-fingerprint",
    )
    assert not item.is_fresh(
        now,
        hermes_version="0.21.0",
        config_digest="config-digest",
        binding_fingerprint="binding-fingerprint",
    )
    assert not item.is_fresh(
        now,
        hermes_version="0.20.0",
        config_digest="changed",
        binding_fingerprint="binding-fingerprint",
    )
    assert not item.is_fresh(
        now,
        hermes_version="0.20.0",
        config_digest="config-digest",
        binding_fingerprint="changed",
    )


def test_two_workers_aggregate_by_component_not_identical_binding() -> None:
    now = datetime(2026, 8, 12, 12, 1, tzinfo=UTC)
    luna_binding = binding(
        portable_id="agentporter-bounded-worker",
        component_id="component-luna",
        current_profile_name="luna",
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        binding_fingerprint="luna-fingerprint",
        config_digest="luna-config",
    )
    luna = evidence(
        binding=luna_binding,
        actual_model="gpt-5.6-luna",
        actual_provider="custom",
    )
    assert (
        aggregate_readiness(
            [evidence(), luna],
            now=now,
            required_components={"component-codex", "component-luna"},
        )
        == "inference-ready"
    )


def test_aggregation_rejects_missing_duplicate_failed_and_stale_components() -> None:
    now = datetime(2026, 8, 12, 12, 1, tzinfo=UTC)
    required = {"component-codex", "component-luna"}
    assert (
        aggregate_readiness([], now=now, required_components=required) == "configuration-required"
    )
    assert (
        aggregate_readiness([evidence()], now=now, required_components=required)
        == "canary-required"
    )
    with pytest.raises(ValueError, match="duplicate component"):
        aggregate_readiness([evidence(), evidence()], now=now)

    failed = replace(
        evidence(),
        status="authentication-failed",
        safe_reason_code="authentication-failed",
        actual_model=None,
        actual_provider=None,
        api_calls=0,
        response_contract_passed=False,
    )
    assert aggregate_readiness([failed], now=now) == "blocked"
    assert aggregate_readiness([evidence()], now=now + timedelta(minutes=10)) == "canary-required"


def test_fresh_install_force_config_and_static_model_change_invalidate_evidence() -> None:
    item = evidence()
    assert not item.valid_after_lifecycle("fresh-install")
    assert item.valid_after_lifecycle("update")
    assert not item.valid_after_lifecycle("update", force_config=True)
    assert not item.valid_after_lifecycle("update", expected_model="changed")


def test_live_call_with_missing_route_telemetry_is_restricted_not_operational() -> None:
    item = evidence(
        status="route-proof-incomplete",
        safe_reason_code="route-proof-incomplete",
        tool_calls_observed=None,
        fallback_used=None,
    )
    now = datetime(2026, 8, 12, 12, 1, tzinfo=UTC)
    assert item.live_call_passed is True
    assert item.dispatch_eligibility == "restricted"
    assert aggregate_readiness([item], now=now) == "restricted"


def test_runtime_ready_requires_explicit_tool_and_fallback_telemetry() -> None:
    with pytest.raises(ValueError, match="route-proof"):
        evidence(tool_calls_observed=None)
    with pytest.raises(ValueError, match="route-proof"):
        evidence(fallback_used=None)


@pytest.mark.parametrize(
    ("event", "kwargs"),
    [
        ("fresh-install", {}),
        ("reinstall", {}),
        ("uninstall", {}),
        ("profile-rename", {}),
        ("update", {"force_config": True}),
        ("update", {"hermes_version": "0.21.0"}),
        ("update", {"config_digest": "changed"}),
        ("update", {"binding_fingerprint": "changed"}),
    ],
)
def test_complete_evidence_invalidation_matrix(event: str, kwargs: dict[str, object]) -> None:
    assert not evidence().valid_after_lifecycle(event, **kwargs)  # type: ignore[arg-type]
