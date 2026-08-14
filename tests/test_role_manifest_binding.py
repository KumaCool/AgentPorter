from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from pydantic import ValidationError

from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import (
    COMPONENT_IDS,
    INITIAL_PROFILE_NAMES,
    INSTALL_COMPONENT_IDS,
    LEGACY_PORTABLE_IDS,
    LEGACY_V020_COMPONENT_IDS,
    portable_id_for_component,
)
from agentporter.manifest import load_manifest
from agentporter.models import WorkersManifest
from agentporter.planning import RuntimeBindingSelection, cleanup_staging, plan_installation
from agentporter.render import render_staging

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "src/agentporter/resources/workers.yaml"
INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")


def _detection(tmp_path: Path) -> HermesDetection:
    home = tmp_path / "hermes"
    return HermesDetection(
        executable=tmp_path / "bin/hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(
            frozenset({"install", "delete", "describe", "list", "info"}), frozenset()
        ),
        profile_entries=(),
    )


def _bindings() -> dict[str, RuntimeBindingSelection]:
    return {
        "bounded_worker": RuntimeBindingSelection("model-a", "provider-a", "https://a.invalid/v1"),
        "mechanical_worker": RuntimeBindingSelection(
            "model-b", "provider-b", "https://b.invalid/v1"
        ),
    }


def test_role_registry_uses_role_names_but_preserves_permanent_component_ids() -> None:
    assert tuple(COMPONENT_IDS) == ("bounded_worker", "mechanical_worker")
    assert tuple(INSTALL_COMPONENT_IDS) == (
        "bounded_worker",
        "mechanical_worker",
    )
    assert tuple(LEGACY_V020_COMPONENT_IDS) == (
        "bounded_worker",
        "mechanical_worker",
        "agentporter_orchestrator",
    )
    assert COMPONENT_IDS == {
        "bounded_worker": "5c7f978c-a9a6-4cec-98fa-e65bbf8101cd",
        "mechanical_worker": "7dab98fb-9ac0-44fa-90fb-4a4f30e1470c",
    }
    assert INITIAL_PROFILE_NAMES == {
        "bounded_worker": "agentporter-bounded-worker",
        "mechanical_worker": "agentporter-mechanical-worker",
    }
    assert LEGACY_PORTABLE_IDS == {
        "luna_worker": "bounded_worker",
        "codex_5_3_small_worker": "mechanical_worker",
    }
    assert portable_id_for_component(COMPONENT_IDS["bounded_worker"]) == "bounded_worker"
    assert portable_id_for_component(COMPONENT_IDS["mechanical_worker"]) == "mechanical_worker"
    with pytest.raises(ValueError, match="unknown component"):
        portable_id_for_component("00000000-0000-4000-8000-000000000000")


def test_authoritative_manifest_contains_only_role_semantics() -> None:
    manifest = load_manifest(MANIFEST)
    assert tuple(manifest.workers) == tuple(INSTALL_COMPONENT_IDS)
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    for portable_id, worker in manifest.workers.items():
        assert "model" not in raw["workers"][portable_id]
        assert "provider" not in raw["workers"][portable_id]
        assert all(term not in worker.display_name.lower() for term in ("luna", "codex", "gpt"))

    invalid = raw | {"workers": dict(raw["workers"])}
    invalid["workers"]["bounded_worker"] = dict(invalid["workers"]["bounded_worker"])
    invalid["workers"]["bounded_worker"]["model"] = "forbidden-default"
    with pytest.raises(ValidationError):
        WorkersManifest.model_validate(invalid)


def test_render_requires_closed_explicit_runtime_bindings(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST)
    with pytest.raises(ValueError, match="binding selection is required"):
        render_staging(manifest, tmp_path / "missing", INSTALLATION_ID)
    assert not (tmp_path / "missing").exists()

    missing = _bindings()
    missing.pop("mechanical_worker")
    with pytest.raises(ValueError, match="closed"):
        render_staging(manifest, tmp_path / "partial", INSTALLATION_ID, bindings=missing)
    assert not (tmp_path / "partial").exists()


def test_explicit_bindings_flow_through_plan_render_and_fingerprint(tmp_path: Path) -> None:
    selection = _bindings()
    plan = plan_installation(
        _detection(tmp_path),
        MANIFEST,
        staging_parent=tmp_path / "stage",
        installation_id_factory=lambda: INSTALLATION_ID,
        binding_selection=selection,
    )
    assert plan.status == "ready"
    assert [(w.portable_id, w.model, w.provider) for w in plan.workers] == [
        ("bounded_worker", "model-a", "provider-a"),
        ("mechanical_worker", "model-b", "provider-b"),
    ]
    assert plan.workers[0].endpoint_summary != selection["bounded_worker"].endpoint
    assert selection["bounded_worker"].endpoint not in plan.workers[0].endpoint_summary
    assert plan.staging_dir is not None
    first_config = yaml.safe_load(
        (plan.staging_dir / "agentporter-bounded-worker/config.yaml").read_text(encoding="utf-8")
    )
    assert first_config["model"] == {
        "default": "model-a",
        "provider": "provider-a",
        "base_url": "https://a.invalid/v1",
    }
    assert "providers" not in first_config
    assert selection["bounded_worker"].endpoint not in repr(plan)

    changed = dict(selection)
    changed["bounded_worker"] = replace(selection["bounded_worker"], model="model-c")
    other = plan_installation(
        _detection(tmp_path),
        MANIFEST,
        staging_parent=tmp_path / "other-stage",
        installation_id_factory=lambda: INSTALLATION_ID,
        binding_selection=changed,
        materialize=False,
    )
    assert other.fingerprint != plan.fingerprint
    assert cleanup_staging(plan).status == "cleaned"


def test_binding_selection_rejects_missing_unknown_and_blank_before_staging(tmp_path: Path) -> None:
    cases: list[dict[str, RuntimeBindingSelection]] = []
    missing = _bindings()
    missing.pop("bounded_worker")
    cases.append(missing)
    unknown = _bindings() | {"unknown": RuntimeBindingSelection("m", "p", "https://x.invalid")}
    cases.append(unknown)
    blank = _bindings()
    blank["bounded_worker"] = RuntimeBindingSelection(" ", "p", "https://x.invalid")
    cases.append(blank)

    for index, selection in enumerate(cases):
        stage = tmp_path / f"stage-{index}"
        plan = plan_installation(
            _detection(tmp_path), MANIFEST, staging_parent=stage, binding_selection=selection
        )
        assert plan.status == "invalid"
        assert plan.installable is False
        assert not stage.exists()
