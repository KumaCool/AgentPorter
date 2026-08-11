from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO

import pytest

from agentporter.interaction import (
    ConfirmationDecision,
    ConfirmationRequest,
    confirm_once,
    confirm_then,
)

FINGERPRINT = "0123456789abcdef" * 4
PLAN_TEXT = "Install both workers\n- luna_worker\n- codex_5_3_small_worker"


def request() -> ConfirmationRequest:
    return ConfirmationRequest(plan_text=PLAN_TEXT, fingerprint=FINGERPRINT)


def test_confirmation_request_is_immutable_and_derives_exact_phrase() -> None:
    confirmation = request()

    assert confirmation.phrase == "INSTALL AGENTPORTER 01234567"
    with pytest.raises(FrozenInstanceError):
        confirmation.fingerprint = "f" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "fingerprint",
    [
        "A" * 64,
        "g" * 64,
        "0" * 63,
        "0" * 65,
        "  " + "0" * 64,
        "0" * 64 + "\n",
    ],
)
def test_confirmation_request_rejects_noncanonical_sha256(fingerprint: str) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        ConfirmationRequest(plan_text=PLAN_TEXT, fingerprint=fingerprint)


def test_exact_confirmation_prints_complete_bound_plan_once_and_confirms() -> None:
    output = StringIO()
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return request().phrase

    decision = confirm_once(request(), input_fn=read, output=output)

    rendered = output.getvalue()
    assert decision is ConfirmationDecision.CONFIRMED
    assert rendered.count(PLAN_TEXT) == 1
    assert rendered.count(FINGERPRINT) == 1
    assert prompts == ["Type INSTALL AGENTPORTER 01234567 to confirm: "]


@pytest.mark.parametrize(
    "answer",
    ["", "yes", "INSTALL AGENTPORTER 01234567 ", "install agentporter 01234567"],
)
def test_empty_or_inexact_confirmation_cancels_without_retry(answer: str) -> None:
    output = StringIO()
    calls = 0

    def read(_: str) -> str:
        nonlocal calls
        calls += 1
        return answer

    decision = confirm_once(request(), input_fn=read, output=output)

    assert decision is ConfirmationDecision.CANCELLED
    assert calls == 1
    assert output.getvalue().count(PLAN_TEXT) == 1


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
def test_input_termination_cancels_without_retry(error: BaseException) -> None:
    calls = 0

    def read(_: str) -> str:
        nonlocal calls
        calls += 1
        raise error

    decision = confirm_once(request(), input_fn=read, output=StringIO())
    assert decision is ConfirmationDecision.CANCELLED
    assert calls == 1


def test_cancelled_confirmation_never_calls_continuation() -> None:
    def forbidden_continuation() -> None:
        raise AssertionError("write/model continuation must not be called")

    outcome = confirm_then(
        request(),
        forbidden_continuation,
        input_fn=lambda _: "wrong",
        output=StringIO(),
    )

    assert outcome.decision is ConfirmationDecision.CANCELLED
    assert outcome.continuation_result is None


def test_confirmed_confirmation_calls_continuation_exactly_once() -> None:
    calls = 0

    def continuation() -> str:
        nonlocal calls
        calls += 1
        return "continued"

    outcome = confirm_then(
        request(),
        continuation,
        input_fn=lambda _: request().phrase,
        output=StringIO(),
    )

    assert outcome.decision is ConfirmationDecision.CONFIRMED
    assert outcome.continuation_result == "continued"
    assert calls == 1
