"""Safe classification primitives for runtime canary failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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


def classify_probe_failure(failure: ProbeFailure) -> ProbeFailureReason:
    if failure.timed_out:
        return "probe-timeout"
    if failure.http_status in {401, 403}:
        return "authentication-failed"
    if failure.http_status == 404:
        return "model-unsupported"
    if failure.http_status == 429:
        return "rate-limited"
    if failure.http_status is not None and failure.http_status >= 500:
        return "endpoint-unavailable"
    return "response-contract-failed"
