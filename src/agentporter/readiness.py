"""Pure, secret-free runtime readiness contracts."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ReadinessStatus = Literal[
    "runtime-ready",
    "route-proof-incomplete",
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
]
ReasonCode = ReadinessStatus
ProviderSourceKind = Literal["profile-config", "task-override", "unresolved"]
LifecycleEvent = Literal["fresh-install", "reinstall", "update", "profile-rename", "uninstall"]
AggregateStatus = Literal[
    "inference-ready", "restricted", "canary-required", "blocked", "configuration-required"
]

_BLOCKING = frozenset(
    {
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
    binding_fingerprint: str
    config_digest: str
    endpoint_digest: str | None = None
    fallback_policy: Literal["forbidden"] = "forbidden"

    def __post_init__(self) -> None:
        for name in (
            "portable_id",
            "component_id",
            "current_profile_name",
            "expected_model",
            "binding_fingerprint",
            "config_digest",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.expected_provider is not None and not self.expected_provider.strip():
            raise ValueError("expected_provider must be non-empty when supplied")
        if self.endpoint_digest is not None and not self.endpoint_digest.strip():
            raise ValueError("endpoint_digest must be non-empty when supplied")
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
    tool_calls_observed: int | None
    fresh_until: datetime
    fallback_used: bool | None = False

    def __post_init__(self) -> None:
        if self.status != self.safe_reason_code:
            raise ValueError("status and safe_reason_code must match")
        if self.status not in {"runtime-ready", "route-proof-incomplete", *_BLOCKING}:
            raise ValueError("invalid readiness status")
        if self.fallback_used is True:
            raise ValueError("fallback is forbidden")
        if self.probe_finished_at < self.probe_started_at:
            raise ValueError("probe timestamps are out of order")
        if self.fresh_until <= self.probe_finished_at:
            raise ValueError("fresh_until must be after probe completion")
        if self.api_calls < 0 or (
            self.tool_calls_observed is not None and self.tool_calls_observed < 0
        ):
            raise ValueError("call counts cannot be negative")
        if self.status == "runtime-ready":
            if self.tool_calls_observed is None or self.fallback_used is None:
                raise ValueError("route-proof telemetry is required")
            if (
                self.actual_model != self.binding.expected_model
                or self.actual_provider != self.binding.expected_provider
            ):
                raise ValueError("unexpected-runtime-route")
            if (
                self.api_calls != 1
                or self.tool_calls_observed != 0
                or not self.response_contract_passed
            ):
                raise ValueError("response-contract-failed")
        elif self.status == "route-proof-incomplete":
            if (
                self.actual_model != self.binding.expected_model
                or self.actual_provider != self.binding.expected_provider
                or self.api_calls != 1
                or not self.response_contract_passed
                or self.tool_calls_observed is not None
                or self.fallback_used is not None
            ):
                raise ValueError("route-proof-incomplete violates live-call contract")
        elif self.actual_model is not None or self.actual_provider is not None:
            raise ValueError("failure evidence must omit runtime route")

    @property
    def live_call_passed(self) -> bool:
        return self.status in {"runtime-ready", "route-proof-incomplete"}

    @property
    def dispatch_eligibility(self) -> Literal["blocked", "restricted", "eligible"]:
        if self.status == "runtime-ready":
            return "eligible"
        if self.status == "route-proof-incomplete":
            return "restricted"
        return "blocked"

    def is_fresh(
        self,
        now: datetime,
        *,
        hermes_version: str | None = None,
        config_digest: str | None = None,
        binding_fingerprint: str | None = None,
    ) -> bool:
        return (
            now < self.fresh_until
            and (hermes_version is None or hermes_version == self.hermes_version)
            and (config_digest is None or config_digest == self.binding.config_digest)
            and (
                binding_fingerprint is None
                or binding_fingerprint == self.binding.binding_fingerprint
            )
        )

    def valid_after_lifecycle(
        self,
        event: LifecycleEvent,
        *,
        force_config: bool = False,
        expected_model: str | None = None,
        expected_provider: str | None = None,
        endpoint_digest: str | None = None,
        hermes_version: str | None = None,
        config_digest: str | None = None,
        binding_fingerprint: str | None = None,
    ) -> bool:
        """Express lifecycle invalidation; Phase B owns integration wiring."""
        return (
            event == "update"
            and not force_config
            and (expected_model is None or expected_model == self.binding.expected_model)
            and (expected_provider is None or expected_provider == self.binding.expected_provider)
            and (endpoint_digest is None or endpoint_digest == self.binding.endpoint_digest)
            and (hermes_version is None or hermes_version == self.hermes_version)
            and (config_digest is None or config_digest == self.binding.config_digest)
            and (
                binding_fingerprint is None
                or binding_fingerprint == self.binding.binding_fingerprint
            )
        )


def aggregate_readiness(
    evidence: list[ReadinessEvidence],
    *,
    now: datetime,
    required_components: Collection[str] | None = None,
) -> AggregateStatus:
    if not evidence:
        return "configuration-required"
    component_ids = [item.binding.component_id for item in evidence]
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("duplicate component evidence")
    if required_components is not None:
        required = set(required_components)
        unknown = set(component_ids) - required
        if unknown:
            raise ValueError("unexpected component evidence")
        if required - set(component_ids):
            return "canary-required"
    if any(item.status in _BLOCKING for item in evidence):
        return "blocked"
    if any(not item.is_fresh(now) for item in evidence):
        return "canary-required"
    if any(item.status == "route-proof-incomplete" for item in evidence):
        return "restricted"
    return "inference-ready"
