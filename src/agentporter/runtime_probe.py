"""Tool-free runtime canary execution and safe failure classification."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import secrets
import signal
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from .readiness import ReadinessEvidence, RuntimeBinding
from .runtime_binding import RuntimeBindingPlan, binding_fingerprint

ProbeStatus = Literal[
    "probe-unsupported",
    "route-proof-incomplete",
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
    tool_calls: int | None = 0
    fallback_used: bool | None = False
    http_status: int | None = None
    timed_out: bool = False
    failure_reason: ProbeFailureReason | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    actual_model: str | None = None
    actual_provider: str | None = None
    api_calls: int = 0
    tool_calls: int | None = 0
    fallback_used: bool | None = False
    response_contract_passed: bool = False
    probe_started_at: datetime | None = None
    probe_finished_at: datetime | None = None
    fresh_until: datetime | None = None
    nonce_contract_passed: bool = False
    nonce_digest: str | None = None

    def __post_init__(self) -> None:
        if self.api_calls < 0 or (self.tool_calls is not None and self.tool_calls < 0):
            raise ValueError("call counts cannot be negative")
        if self.status == "runtime-ready" and (
            not self.actual_model
            or not self.actual_provider
            or self.api_calls != 1
            or self.tool_calls != 0
            or self.fallback_used
            or not self.response_contract_passed
        ):
            raise ValueError("runtime-ready result violates the closed probe contract")
        if (
            self.status not in {"runtime-ready", "route-proof-incomplete"}
            and self.response_contract_passed
        ):
            raise ValueError("failure result cannot pass response contract")
        if self.status == "runtime-ready" and (
            self.probe_started_at is None
            or self.probe_finished_at is None
            or self.fresh_until is None
            or self.probe_started_at > self.probe_finished_at
            or self.fresh_until <= self.probe_finished_at
            or not self.nonce_contract_passed
            or not self.nonce_digest
        ):
            raise ValueError("runtime-ready result lacks sealed probe provenance")

    @property
    def live_call_passed(self) -> bool:
        return self.status in {"runtime-ready", "route-proof-incomplete"}


@dataclass(frozen=True, slots=True)
class ProbeCapability:
    supported: bool
    status: Literal["supported", "route-proof-incomplete", "probe-unsupported"]
    oneshot_supported: bool = False
    usage_file_supported: bool = False
    usage_model_provider_supported: bool = False
    usage_api_calls_supported: bool = False
    tool_call_telemetry_supported: bool = False
    fallback_telemetry_supported: bool = False
    profile_scoped_auth_supported: bool = False


def negotiate_hermes_probe(
    *, version: str, help_text: str, command_runner: Callable[[tuple[str, ...]], object]
) -> ProbeCapability:
    del version, command_runner
    oneshot = "--oneshot" in help_text or "-z" in help_text
    usage = "--usage-file" in help_text
    auth = "auth" in help_text and "status" in help_text and "add" in help_text
    supported = oneshot and usage and auth
    return ProbeCapability(
        supported,
        "route-proof-incomplete" if supported else "probe-unsupported",
        oneshot_supported=oneshot,
        usage_file_supported=usage,
        usage_model_provider_supported=usage,
        usage_api_calls_supported=usage,
        profile_scoped_auth_supported=auth,
    )


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


def _isolated_observation(
    runner: Callable[[str, Path], ProbeObservation], nonce: str, directory: Path, timeout: float
) -> ProbeObservation | None:
    context = multiprocessing.get_context("fork")
    receiving, sending = context.Pipe(duplex=False)

    def invoke() -> None:
        try:
            os.setsid()
            sending.send(runner(nonce, directory))
        except Exception as error:
            reason = getattr(error, "reason", None)
            with suppress(BaseException):
                sending.send(
                    reason if isinstance(reason, str) else ProbeObservation(http_status=500)
                )
        except BaseException:
            with suppress(BaseException):
                sending.send(ProbeObservation(http_status=500))
        finally:
            sending.close()

    process = context.Process(target=invoke)
    process.start()
    sending.close()
    process.join(timeout)
    if process.is_alive():
        process_id = process.pid
        if process_id is not None:
            with suppress(ProcessLookupError):
                os.killpg(process_id, signal.SIGKILL)
        process.join()
        receiving.close()
        return None
    try:
        value = receiving.recv() if receiving.poll() else None
    except (EOFError, OSError):
        value = None
    receiving.close()
    if isinstance(value, str) and value in {
        "authentication-failed",
        "model-unsupported",
        "endpoint-unavailable",
        "rate-limited",
        "probe-timeout",
        "response-contract-failed",
    }:
        return ProbeObservation(failure_reason=value)  # type: ignore[arg-type]
    return value if isinstance(value, ProbeObservation) else None


def run_runtime_probe(
    *,
    expected_model: str,
    expected_provider: str,
    runner: Callable[[str, Path], ProbeObservation],
    supported: bool = True,
    timeout_seconds: float = 30.0,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    freshness: timedelta = timedelta(minutes=5),
) -> ProbeResult:
    if not supported:
        return ProbeResult("probe-unsupported")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if freshness <= timedelta(0):
        raise ValueError("freshness must be positive")
    started = now()
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="agentporter-probe-") as raw_directory:
        directory = Path(raw_directory)
        directory.chmod(0o700)
        observation = _isolated_observation(runner, nonce, directory, timeout_seconds)
    finished = now()
    provenance: dict[str, object] = {
        "probe_started_at": started,
        "probe_finished_at": finished,
        "fresh_until": finished + freshness,
        "nonce_contract_passed": False,
        "nonce_digest": hashlib.sha256(nonce.encode()).hexdigest(),
    }
    if observation is None:
        return ProbeResult("probe-timeout", **provenance)  # type: ignore[arg-type]
    if observation.failure_reason is not None:
        return ProbeResult(observation.failure_reason, **provenance)  # type: ignore[arg-type]
    if observation.timed_out or observation.http_status is not None:
        return ProbeResult(
            classify_probe_failure(ProbeFailure(observation.http_status, observation.timed_out)),
            **provenance,  # type: ignore[arg-type]
        )
    if (
        observation.fallback_used is True
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
            **provenance,  # type: ignore[arg-type]
        )
    if observation.output != f"AGENTPORTER_READY:{nonce}" or observation.api_calls != 1:
        return ProbeResult(
            "response-contract-failed",
            api_calls=observation.api_calls,
            tool_calls=observation.tool_calls,
            **provenance,  # type: ignore[arg-type]
        )
    provenance["nonce_contract_passed"] = True
    if observation.tool_calls is None or observation.fallback_used is None:
        return ProbeResult(
            "route-proof-incomplete",
            observation.actual_model,
            observation.actual_provider,
            observation.api_calls,
            observation.tool_calls,
            observation.fallback_used,
            True,
            **provenance,  # type: ignore[arg-type]
        )
    if observation.tool_calls != 0:
        return ProbeResult(
            "response-contract-failed",
            api_calls=observation.api_calls,
            tool_calls=observation.tool_calls,
            **provenance,  # type: ignore[arg-type]
        )
    return ProbeResult(
        "runtime-ready",
        observation.actual_model,
        observation.actual_provider,
        observation.api_calls,
        observation.tool_calls,
        observation.fallback_used,
        True,
        **provenance,  # type: ignore[arg-type]
    )


def probe_readiness_evidence(
    *,
    binding: RuntimeBindingPlan,
    runner: Callable[[str, Path], ProbeObservation],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    freshness: timedelta = timedelta(minutes=5),
    supported: bool = True,
) -> ReadinessEvidence:
    if freshness <= timedelta(0):
        raise ValueError("freshness must be positive")
    result = run_runtime_probe(
        expected_model=binding.expected_model,
        expected_provider=binding.provider_id,
        runner=runner,
        supported=supported,
        now=now,
        freshness=freshness,
    )
    ready = result.live_call_passed
    safe_binding = RuntimeBinding(
        binding.portable_id,
        binding.component_id,
        binding.current_profile_name,
        binding.expected_model,
        binding.provider_id,
        "profile-config",
        binding_fingerprint(binding),
        binding.config_digest,
    )
    return ReadinessEvidence(
        status=result.status,
        safe_reason_code=result.status,
        binding=safe_binding,
        hermes_version=binding.hermes_version,
        probe_started_at=result.probe_started_at or now(),
        probe_finished_at=result.probe_finished_at or now(),
        actual_model=result.actual_model if ready else None,
        actual_provider=result.actual_provider if ready else None,
        api_calls=result.api_calls if ready else 0,
        response_contract_passed=ready,
        tool_calls_observed=result.tool_calls if ready else 0,
        fresh_until=result.fresh_until or now() + freshness,
        fallback_used=result.fallback_used,
    )
