from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import yaml

from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.manifest import load_manifest
from agentporter.models import MarkerV1
from agentporter.render import render_staging


def test_render_staging_produces_minimal_valid_artifacts_for_both_workers(tmp_path: Path) -> None:
    manifest = load_manifest(Path(__file__).parents[1] / "workers.yaml")
    installation_id = UUID("12345678-1234-4abc-8def-1234567890ab")

    rendered = render_staging(manifest, tmp_path, installation_id)

    assert [item.profile_name for item in rendered] == [
        "luna_worker",
        "codex-5-3-small-worker",
    ]
    markers: list[MarkerV1] = []
    for item in rendered:
        assert {path.name for path in item.directory.iterdir()} == {
            "distribution.yaml",
            "config.yaml",
            "SOUL.md",
            "agentporter-profile.json",
        }
        distribution = yaml.safe_load((item.directory / "distribution.yaml").read_text())
        config = yaml.safe_load((item.directory / "config.yaml").read_text())
        markers.append(
            MarkerV1.model_validate_json((item.directory / "agentporter-profile.json").read_text())
        )
        assert distribution["name"] == item.profile_name
        assert distribution["version"] == "0.1.0"
        assert distribution["distribution_owned"] == [
            "SOUL.md",
            "config.yaml",
            "agentporter-profile.json",
        ]
        assert distribution["license"] == "MIT"
        assert set(config) == {"model", "agent"}
        assert "provider" not in config["model"]
        soul = (item.directory / "SOUL.md").read_text()
        assert "Do not change the delegated objective" in soul
        assert "Do not broaden the delegated scope" in soul
        assert "report the exact blocker" in soul
        assert "Never invent results" in soul

    assert {marker.installation_id for marker in markers} == {str(installation_id)}
    assert {marker.product_id for marker in markers} == {PRODUCT_ID}
    assert {marker.component_id for marker in markers} == set(COMPONENT_IDS.values())
    for marker in markers:
        payload = json.loads(marker.model_dump_json())
        assert len(payload) == 5
        assert not any("name" in key for key in payload)


def test_render_includes_optional_provider_and_mechanical_boundary(tmp_path: Path) -> None:
    manifest = load_manifest(Path(__file__).parents[1] / "workers.yaml")
    worker = manifest.workers["codex_5_3_small_worker"]
    worker.provider = "public-provider"

    rendered = render_staging(manifest, tmp_path, UUID("12345678-1234-4abc-8def-1234567890ab"))
    mechanical = rendered[1].directory

    config = yaml.safe_load((mechanical / "config.yaml").read_text())
    assert config["model"]["provider"] == "public-provider"
    assert "simpler and more mechanical" in (mechanical / "SOUL.md").read_text()
