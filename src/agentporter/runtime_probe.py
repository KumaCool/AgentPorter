"""Tool-free runtime canary execution and safe failure classification."""

from __future__ import annotations

import secrets
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ProbeStatus = Literal[
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
) -> ProbeResult:
    """Run one injected canary in a 0700 temporary directory, always cleaning it."""
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="agentporter-probe-") as raw_directory:
        observation = runner(nonce, Path(raw_directory))

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
