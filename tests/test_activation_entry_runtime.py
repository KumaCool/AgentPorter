from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_activation_application import (
    _inputs as inputs_fixture,  # pyright: ignore[reportPrivateUsage]
)
from test_activation_application import (  # pyright: ignore[reportPrivateUsage]
    _installation as installation_fixture,  # pyright: ignore[reportPrivateUsage]
)

from agentporter.activation_application import (
    ActivationStatus,
    apply_activation,
    build_activation_plan,
)
from agentporter.runtime_probe import ProbeObservation


def test_runtime_skips_unsupported_custom_provider_auth_and_discloses_live_side_effects(
    tmp_path: Path,
) -> None:
    found, discovery = installation_fixture(tmp_path)
    plan = build_activation_plan(discovery, found, inputs_fixture())
    prompts: list[str] = []
    output: list[str] = []
    answers = iter((plan.confirmation_phrase, "RUN 2 WORKER CALLS"))

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    class Writer:
        def write(self, value: str) -> int:
            output.append(value)
            return len(value)

    result = apply_activation(
        plan,
        input_fn=answer,
        output=Writer(),  # type: ignore[arg-type]
        auth_status_runner=lambda _binding: pytest.fail("custom Provider auth status unsupported"),
        auth_add_runner=lambda _binding: pytest.fail("custom Provider auth add unsupported"),
        probe_runner=lambda binding, nonce, _directory: ProbeObservation(
            output=f"AGENTPORTER_READY:{nonce}",
            actual_model=binding.expected_model,
            actual_provider=binding.provider_id,
            api_calls=1,
            tool_calls=None,
            fallback_used=None,
        ),
        require_runtime_confirmations=True,
    )
    assert result.status is ActivationStatus.RESTRICTED

    assert all(
        json.loads((item.profile_path / "local/agentporter/runtime-binding.json").read_text())[
            "canary_reason_code"
        ]
        == "route-proof-incomplete"
        for item in plan.bindings
    )
    rendered = "".join(output).lower()
    assert "possible fees" in rendered
    assert "session" in rendered and "usage" in rendered and "memory" in rendered
    assert "state.db" in rendered and "will not" in rendered
    for item in plan.bindings:
        receipt = json.loads(
            (item.profile_path / "local/agentporter/runtime-binding.json").read_text()
        )
        assert receipt["credential_status"] == "logged-in"
        assert receipt["credential_verification"] == "verified"


def test_rejecting_live_confirmation_makes_zero_probe_calls_but_keeps_binding(
    tmp_path: Path,
) -> None:
    found, discovery = installation_fixture(tmp_path)
    plan = build_activation_plan(discovery, found, inputs_fixture())
    probes: list[str] = []
    answers = iter((plan.confirmation_phrase, "NO"))
    result = apply_activation(
        plan,
        input_fn=lambda _prompt: next(answers),
        auth_status_runner=lambda _binding: pytest.fail("auth status must not run"),
        auth_add_runner=lambda _binding: pytest.fail("auth add must not run"),
        probe_runner=lambda binding, _nonce, _directory: (
            probes.append(binding.component_id) or ProbeObservation()
        ),
        require_runtime_confirmations=True,
    )
    assert result.status is ActivationStatus.CANARY_REQUIRED
    assert probes == []
    assert all(
        (item.profile_path / "local/agentporter/runtime-binding.json").is_file()
        for item in plan.bindings
    )


def test_unsupported_grant_returns_before_auth_or_probe(tmp_path: Path) -> None:
    found, discovery = installation_fixture(tmp_path)
    inputs = inputs_fixture()
    first = next(iter(inputs))
    inputs[first] = type(inputs[first])(
        "selected-test-model",
        "custom-provider",
        "https://activation-endpoint.invalid/v1",
        "profile-env",
        "operator-authorized",
    )
    plan = build_activation_plan(discovery, found, inputs)
    calls: list[str] = []
    result = apply_activation(
        plan,
        input_fn=lambda _prompt: plan.confirmation_phrase,
        auth_status_runner=lambda binding: (
            calls.append("status:" + binding.component_id) or "unknown"
        ),
        auth_add_runner=lambda binding: calls.append("add:" + binding.component_id),
        probe_runner=lambda binding, _nonce, _directory: (
            calls.append("probe:" + binding.component_id) or ProbeObservation()
        ),
        require_runtime_confirmations=True,
    )
    assert result.status is ActivationStatus.CREDENTIAL_SOURCE_UNSUPPORTED
    assert calls == []


def test_custom_provider_config_never_calls_hermes_auth(tmp_path: Path) -> None:
    found, discovery = installation_fixture(tmp_path)
    plan = build_activation_plan(discovery, found, inputs_fixture())
    calls: list[str] = []
    answers = iter((plan.confirmation_phrase, "NO"))
    result = apply_activation(
        plan,
        input_fn=lambda _prompt: next(answers),
        auth_status_runner=lambda binding: (
            calls.append("status:" + binding.component_id) or "unknown"
        ),
        auth_add_runner=lambda binding: calls.append("add:" + binding.component_id),
        probe_runner=lambda _binding, _nonce, _directory: ProbeObservation(),
        require_runtime_confirmations=True,
    )
    assert result.status is ActivationStatus.CANARY_REQUIRED
    assert calls == []
