from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import yaml
from test_activation_application import _inputs, _installation

from agentporter.activation_application import apply_activation, build_activation_plan
from agentporter.identity import portable_id_for_component
from agentporter.runtime_authority import invalidate_runtime_readiness, load_profile_readiness
from agentporter.runtime_probe import ProbeObservation


def _activate(tmp_path: Path):
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    result = apply_activation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase,
        probe_runner=lambda binding, nonce, _directory: ProbeObservation(
            output=f"AGENTPORTER_READY:{nonce}",
            actual_model=binding.expected_model,
            actual_provider=binding.provider_id,
            api_calls=1,
            tool_calls=0,
        ),
    )
    assert result.status.value == "activated"
    return plan


def test_authority_is_rebuilt_from_current_marker_config_version_and_receipt(
    tmp_path: Path,
) -> None:
    plan = _activate(tmp_path)
    target = plan.bindings[0]

    token = load_profile_readiness(
        target.profile_path, hermes_version="0.20.0", now=datetime.now(UTC)
    )

    assert token.evidence[0].binding.component_id == target.component_id
    assert token.evidence[0].binding.portable_id == portable_id_for_component(target.component_id)
    assert token.evidence[0].dispatch_eligibility == "eligible"


def test_authority_recomputes_canonical_fingerprint_from_current_state(tmp_path: Path) -> None:
    plan = _activate(tmp_path)
    target = plan.bindings[0]
    receipt_path = target.profile_path / "local/agentporter/runtime-binding.json"
    original = json.loads(receipt_path.read_text())

    tampered_documents: list[dict[str, object]] = []
    for field, value in (
        ("binding_fingerprint", "0" * 64),
        ("endpoint_digest", "1" * 64),
        ("component_id", plan.bindings[1].component_id),
        ("profile_name", plan.bindings[1].profile_name),
        ("config_digest", "2" * 64),
    ):
        changed = deepcopy(original)
        changed[field] = value
        tampered_documents.append(changed)
    extended = deepcopy(original)
    extended["untrusted_extension"] = True
    tampered_documents.append(extended)

    for receipt in tampered_documents:
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        assert (
            load_profile_readiness(
                target.profile_path, hermes_version="0.20.0", now=datetime.now(UTC)
            ).evidence
            == ()
        )


def test_authority_rejects_current_config_or_marker_drift(tmp_path: Path) -> None:
    plan = _activate(tmp_path)
    target = plan.bindings[0]
    config = target.profile_path / "config.yaml"
    activated_config = config.read_bytes()
    loaded = yaml.safe_load(activated_config)
    loaded["model"]["provider"] = "forged"
    config.write_text(yaml.safe_dump(loaded), encoding="utf-8")
    assert (
        load_profile_readiness(
            target.profile_path, hermes_version="0.20.0", now=datetime.now(UTC)
        ).evidence
        == ()
    )

    config.write_bytes(activated_config)
    marker = target.profile_path / "agentporter-profile.json"
    payload = json.loads(marker.read_text())
    payload["component_id"] = "foreign"
    marker.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    assert (
        load_profile_readiness(
            target.profile_path, hermes_version="0.20.0", now=datetime.now(UTC)
        ).evidence
        == ()
    )


def test_formal_lifecycle_invalidation_api_is_idempotent(tmp_path: Path) -> None:
    plan = _activate(tmp_path)
    profile = plan.bindings[0].profile_path

    assert invalidate_runtime_readiness(profile) is True
    assert invalidate_runtime_readiness(profile) is False
    assert not (profile / "local/agentporter/runtime-binding.json").exists()
