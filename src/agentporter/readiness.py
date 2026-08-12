"""Pure, secret-free runtime readiness contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ReadinessStatus = Literal[
    "runtime-ready",
    "authentication-failed",
    "model-unsupported",
    "endpoint-unavailable",
    "rate-limited",
    "probe-timeout",
    "response-contract-failed",
    "unexpected-runtime-route",
]
ReasonCode = ReadinessStatus
ProviderSourceKind = Literal["profile-config", "task-override", "unresolved"]

_FAILURES = frozenset(
    {
        "authentication-failed",
        "model-unsupported",
        "endpoint-unavailable",
        "rate-limited",
        "probe-timeout",
        "response-contract-failed",
        "unexpected-runtime-route",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    portable_id: str
    component_id: str
    current_profile_name: str
    expected_model: str
    expected_provider: str | None
    provider_source_kind: ProviderSourceKind
    fallback_policy: Literal["forbidden"] = "forbidden"

    def __post_init__(self) -> None:
        for name in (
            "portable_id",
            "component_id",
            "current_profile_name",
            "expected_model",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.expected_provider is not None and not self.expected_provider.strip():
            raise ValueError("expected_provider must be non-empty when supplied")
        if self.provider_source_kind not in {"profile-config", "task-override", "unresolved"}:
            raise ValueError("invalid provider_source_kind")
        if self.fallback_policy != "forbidden":
            raise ValueError("fallback policy must be forbidden")


@dataclass(frozen=True, slots=True)
class ReadinessEvidence:
    status: ReadinessStatus
    safe_reason_code: ReasonCode
    binding: RuntimeBinding
    hermes_version: str
    probe_started_at: datetime
    probe_finished_at: datetime
    actual_model: str | None
    actual_provider: str | None
    api_calls: int
    response_contract_passed: bool
    tool_calls_observed: int
    fresh_until: datetime
    fallback_used: bool = False

    def __post_init__(self) -> None:
        if self.status != self.safe_reason_code:
            raise ValueError("status and safe_reason_code must match")
        if self.status not in {"runtime-ready", *_FAILURES}:
            raise ValueError("invalid readiness status")
        if self.fallback_used:
            raise ValueError("fallback is forbidden")
        if self.probe_finished_at < self.probe_started_at:
            raise ValueError("probe timestamps are out of order")
        if self.fresh_until <= self.probe_finished_at:
            raise ValueError("fresh_until must be after probe completion")
        if self.api_calls < 0 or self.tool_calls_observed < 0:
            raise ValueError("call counts cannot be negative")
        if self.status == "runtime-ready":
            if self.actual_model != self.binding.expected_model:
                raise ValueError("unexpected-runtime-route")
            if self.actual_provider != self.binding.expected_provider:
                raise ValueError("unexpected-runtime-route")
            if self.api_calls != 1 or self.tool_calls_observed != 0:
                raise ValueError("response-contract-failed")
            if not self.response_contract_passed:
                raise ValueError("response-contract-failed")
        elif self.status in _FAILURES and self.status != "unexpected-runtime-route":
            if self.actual_model is not None or self.actual_provider is not None:
                raise ValueError("failure evidence must omit runtime route")

    def is_fresh(self, now: datetime) -> bool:
        """Freshness is strict: evidence expires at ``fresh_until``."""
        return now < self.fresh_until


def aggregate_readiness(
    evidence: list[ReadinessEvidence], *, now: datetime
) -> Literal["operational", "canary-required", "blocked", "configuration-required"]:
    if not evidence:
        return "configuration-required"
    first = evidence[0].binding
    if any(item.binding != first for item in evidence[1:]):
        raise ValueError("evidence binding mismatch")
    if any(item.status in _FAILURES for item in evidence):
        return "blocked"
    if any(not item.is_fresh(now) for item in evidence):
        return "canary-required"
    if all(item.status == "runtime-ready" for item in evidence):
        return "operational"
    return "canary-required"
