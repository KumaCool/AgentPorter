from __future__ import annotations

import json
from pathlib import Path

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


def test_runtime_phases_have_independent_confirmation_and_disclose_side_effects(
    tmp_path: Path,
) -> None:
    found, discovery = installation_fixture(tmp_path)
    plan = build_activation_plan(discovery, found, inputs_fixture())
    prompts: list[str] = []
    output: list[str] = []
    auth_calls: list[str] = []

    answers = iter(
        (plan.confirmation_phrase, "AUTH renamed-luna", "AUTH renamed-codex", "RUN 2 WORKER CALLS")
    )

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
        auth_status_runner=lambda binding: "logged-out",
        auth_add_runner=lambda binding: auth_calls.append(binding.component_id),
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
    assert len(auth_calls) == 2
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


def test_rejecting_live_confirmation_makes_zero_probe_calls_but_keeps_binding_and_auth(
    tmp_path: Path,
) -> None:
    found, discovery = installation_fixture(tmp_path)
    plan = build_activation_plan(discovery, found, inputs_fixture())
    probes: list[str] = []
    answers = iter((plan.confirmation_phrase, "AUTH renamed-luna", "AUTH renamed-codex", "NO"))
    result = apply_activation(
        plan,
        input_fn=lambda _prompt: next(answers),
        auth_status_runner=lambda _binding: "logged-out",
        auth_add_runner=lambda _binding: None,
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
        "p", "https://example.invalid", "profile-env", "operator-authorized"
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
