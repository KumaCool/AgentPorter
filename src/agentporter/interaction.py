from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TextIO, TypeVar

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")


class ConfirmationDecision(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ConfirmationRequest:
    plan_text: str
    fingerprint: str
    phrase: str = field(init=False)

    def __post_init__(self) -> None:
        if _SHA256_HEX.fullmatch(self.fingerprint) is None:
            raise ValueError("fingerprint must be lowercase SHA-256 hex")
        object.__setattr__(self, "phrase", f"INSTALL AGENTPORTER {self.fingerprint[:8]}")


@dataclass(frozen=True)
class ConfirmationOutcome(Generic[_T]):
    decision: ConfirmationDecision
    continuation_result: _T | None = None


def confirm_once(
    request: ConfirmationRequest,
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
) -> ConfirmationDecision:
    print(request.plan_text, file=output)
    print(f"Plan fingerprint: {request.fingerprint}", file=output)
    try:
        answer = input_fn(f"Type {request.phrase} to confirm: ")
    except (EOFError, KeyboardInterrupt):
        return ConfirmationDecision.CANCELLED
    if answer == request.phrase:
        return ConfirmationDecision.CONFIRMED
    return ConfirmationDecision.CANCELLED


def confirm_then(
    request: ConfirmationRequest,
    continuation: Callable[[], _T],
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
) -> ConfirmationOutcome[_T]:
    decision = confirm_once(request, input_fn=input_fn, output=output)
    if decision is ConfirmationDecision.CANCELLED:
        return ConfirmationOutcome(decision=decision)
    return ConfirmationOutcome(decision=decision, continuation_result=continuation())
