"""Tool-free runtime canary execution and safe failure classification."""

from __future__ import annotations

import secrets
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from .readiness import ReadinessEvidence, RuntimeBinding
from .runtime_binding import RuntimeBindingPlan, binding_fingerprint

ProbeStatus = Literal[
    "probe-unsupported",
    "runtime-ready",
    "authentication-failed",
    "model-unsupported",
    "endpoint-unavailable",
    "rate-limited",
    "probe-timeout",
    "response-contract-failed",
    "unexpected-runtime-route",
]
ProbeFailureReason = Literal[
    "authentication-failed",
    "model-unsupported",
    "endpoint-unavailable",
    "rate-limited",
    "probe-timeout",
    "response-contract-failed",
]


@dataclass(frozen=True, slots=True)
class ProbeFailure:
    http_status: int | None = None
    timed_out: bool = False

    def __post_init__(self) -> None:
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError("http_status is out of range")
        if self.timed_out and self.http_status is not None:
            raise ValueError("timeout and HTTP status are mutually exclusive")


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    output: str = ""
    actual_model: str | None = None
    actual_provider: str | None = None
    api_calls: int = 0
    tool_calls: int = 0
    fallback_used: bool = False
    http_status: int | None = None
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    actual_model: str | None = None
    actual_provider: str | None = None
    api_calls: int = 0
    tool_calls: int = 0
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class ProbeCapability:
    supported: bool
    status: Literal["supported", "probe-unsupported"]


def negotiate_hermes_probe(
    *,
    version: str,
    help_text: str,
    command_runner: Callable[[tuple[str, ...]], object],
) -> ProbeCapability:
    """Fail closed unless a public seam proves every canary invariant.

    Hermes 0.20 ``-z --usage-file`` proves model, provider, and API-call count,
    but neither disables all tools nor reports tool-call/fallback counts. A
    normal prompt is therefore not a safe substitute and no command is run.
    """
    del version, help_text, command_runner
    return ProbeCapability(False, "probe-unsupported")


def classify_probe_failure(failure: ProbeFailure) -> ProbeFailureReason:
    if failure.timed_out:
        return "probe-timeout"
    if failure.http_status in {401, 403}:
        return "authentication-failed"
    if failure.http_status == 404:
        return "model-unsupported"
    if failure.http_status == 429:
        return "rate-limited"
    if failure.http_status in {502, 503}:
        return "endpoint-unavailable"
    return "response-contract-failed"


def run_runtime_probe(
    *,
    expected_model: str,
    expected_provider: str,
    runner: Callable[[str, Path], ProbeObservation],
    supported: bool = True,
) -> ProbeResult:
    """Run one injected canary in a 0700 temporary directory, always cleaning it."""
    if not supported:
        return ProbeResult("probe-unsupported")
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="agentporter-probe-") as raw_directory:
        directory = Path(raw_directory)
        directory.chmod(0o700)
        observation = runner(nonce, directory)

    if observation.timed_out or observation.http_status is not None:
        status = classify_probe_failure(
            ProbeFailure(http_status=observation.http_status, timed_out=observation.timed_out)
        )
        return ProbeResult(status)
    if (
        observation.fallback_used
        or observation.actual_model != expected_model
        or observation.actual_provider != expected_provider
    ):
        return ProbeResult(
            "unexpected-runtime-route",
            observation.actual_model,
            observation.actual_provider,
            observation.api_calls,
            observation.tool_calls,
            observation.fallback_used,
        )
    if (
        observation.output != f"AGENTPORTER_READY:{nonce}"
        or observation.api_calls != 1
        or observation.tool_calls != 0
    ):
        return ProbeResult(
            "response-contract-failed",
            api_calls=observation.api_calls,
            tool_calls=observation.tool_calls,
        )
    return ProbeResult(
        "runtime-ready",
        observation.actual_model,
        observation.actual_provider,
        observation.api_calls,
        observation.tool_calls,
        observation.fallback_used,
    )


def probe_readiness_evidence(
    *,
    binding: RuntimeBindingPlan,
    runner: Callable[[str, Path], ProbeObservation],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    freshness: timedelta = timedelta(minutes=5),
    supported: bool = True,
) -> ReadinessEvidence:
    """Run a canary and convert only its bounded summary to readiness evidence."""
    if freshness <= timedelta(0):
        raise ValueError("freshness must be positive")
    started = now()
    result = run_runtime_probe(
        expected_model=binding.expected_model,
        expected_provider=binding.provider_id,
        runner=runner,
        supported=supported,
    )
    finished = now()
    ready = result.status == "runtime-ready"
    safe_binding = RuntimeBinding(
        portable_id=binding.portable_id,
        component_id=binding.component_id,
        current_profile_name=binding.current_profile_name,
        expected_model=binding.expected_model,
        expected_provider=binding.provider_id,
        provider_source_kind="profile-config",
        binding_fingerprint=binding_fingerprint(binding),
        config_digest=binding.config_digest,
    )
    return ReadinessEvidence(
        status=result.status,
        safe_reason_code=result.status,
        binding=safe_binding,
        hermes_version=binding.hermes_version,
        probe_started_at=started,
        probe_finished_at=finished,
        actual_model=result.actual_model if ready else None,
        actual_provider=result.actual_provider if ready else None,
        api_calls=result.api_calls if ready else 0,
        response_contract_passed=ready,
        tool_calls_observed=result.tool_calls if ready else 0,
        fresh_until=finished + freshness,
    )
