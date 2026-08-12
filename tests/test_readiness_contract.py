from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from agentporter.readiness import (
    ReadinessEvidence,
    RuntimeBinding,
    aggregate_readiness,
)


def binding() -> RuntimeBinding:
    return RuntimeBinding(
        portable_id="codex_worker",
        component_id="component-codex",
        current_profile_name="codex",
        expected_model="gpt-5-codex",
        expected_provider="openai",
        provider_source_kind="profile-config",
        fallback_policy="forbidden",
    )


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
    return ReadinessEvidence(**values)


def test_runtime_binding_is_frozen_and_has_no_secret_or_endpoint_fields() -> None:
    item = binding()
    with pytest.raises(FrozenInstanceError):
        item.expected_model = "other"  # type: ignore[misc]
    assert {field.name for field in fields(item)} == {
        "portable_id",
        "component_id",
        "current_profile_name",
        "expected_model",
        "expected_provider",
        "provider_source_kind",
        "fallback_policy",
    }
    with pytest.raises(TypeError):
        RuntimeBinding(
            portable_id=item.portable_id,
            component_id=item.component_id,
            current_profile_name=item.current_profile_name,
            expected_model=item.expected_model,
            expected_provider=item.expected_provider,
            provider_source_kind=item.provider_source_kind,
            fallback_policy=item.fallback_policy,
            api_key="secret",  # type: ignore[call-arg]
        )


def test_evidence_rejects_fallback_and_unexpected_runtime_route() -> None:
    with pytest.raises(ValueError, match="fallback"):
        evidence(fallback_used=True)
    with pytest.raises(ValueError, match="unexpected-runtime-route"):
        evidence(actual_model="other")
    with pytest.raises(ValueError, match="unexpected-runtime-route"):
        evidence(actual_provider="other")


def test_evidence_classifies_safe_failure_reasons() -> None:
    for status, reason in (
        ("authentication-failed", "authentication-failed"),
        ("model-unsupported", "model-unsupported"),
        ("endpoint-unavailable", "endpoint-unavailable"),
        ("rate-limited", "rate-limited"),
        ("probe-timeout", "probe-timeout"),
        ("response-contract-failed", "response-contract-failed"),
    ):
        item = evidence(
            status=status,
            safe_reason_code=reason,
            actual_model=None,
            actual_provider=None,
            response_contract_passed=False,
        )
        assert item.status == status
        assert item.safe_reason_code == reason


def test_freshness_is_strict_and_aggregation_takes_weakest_evidence() -> None:
    now = datetime(2026, 8, 12, 12, 4, 59, tzinfo=UTC)
    assert evidence().is_fresh(now)
    assert not evidence().is_fresh(now + timedelta(seconds=1))
    assert aggregate_readiness([evidence()], now=now) == "operational"
    stale = evidence()
    assert aggregate_readiness([stale], now=now + timedelta(minutes=10)) == "canary-required"
    failed = evidence(
        status="authentication-failed",
        safe_reason_code="authentication-failed",
        actual_model=None,
        actual_provider=None,
        response_contract_passed=False,
    )
    assert aggregate_readiness([evidence(), failed], now=now) == "blocked"


def test_aggregate_never_accepts_mismatched_binding_or_empty_evidence() -> None:
    assert aggregate_readiness([], now=datetime.now(UTC)) == "configuration-required"
    other_binding = RuntimeBinding(
        portable_id="codex_worker",
        component_id="component-codex",
        current_profile_name="codex",
        expected_model="different",
        expected_provider="openai",
        provider_source_kind="profile-config",
    )
    other = evidence(
        binding=other_binding,
        actual_model="different",
    )
    with pytest.raises(ValueError, match="binding"):
        aggregate_readiness([evidence(), other], now=datetime(2026, 8, 12, 12, 1, tzinfo=UTC))
