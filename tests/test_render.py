from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import yaml

from agentporter.identity import INSTALL_COMPONENT_IDS, PRODUCT_ID
from agentporter.manifest import load_manifest
from agentporter.models import MarkerV1
from agentporter.render import render_staging


def test_render_staging_produces_three_profiles_with_isolated_orchestrator_control(
    tmp_path: Path,
) -> None:
    manifest = load_manifest(Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml")
    installation_id = UUID("12345678-1234-4abc-8def-1234567890ab")

    rendered = render_staging(manifest, tmp_path, installation_id)

    assert [item.profile_name for item in rendered] == [
        "luna_worker",
        "codex-5-3-small-worker",
        "agentporter-orchestrator",
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
        assert distribution["version"] == "0.1.7"
        assert distribution["distribution_owned"] == [
            "SOUL.md",
            "config.yaml",
            "agentporter-profile.json",
        ]
        assert distribution["license"] == "MIT"
        assert {"model", "agent"} <= set(config)
        assert "provider" not in config["model"]
        soul = (item.directory / "SOUL.md").read_text()
        assert "Do not change the delegated objective" in soul
        assert "Do not broaden the delegated scope" in soul
        assert "report the exact blocker" in soul
        assert "Never invent results" in soul

    orchestrator = rendered[2].directory
    orchestrator_config = yaml.safe_load((orchestrator / "config.yaml").read_text())
    assert set(orchestrator_config) == {"model", "agent", "kanban", "platform_toolsets"}
    assert orchestrator_config["kanban"] == {
        "auto_decompose": False,
        "max_in_progress_per_profile": 1,
        "dispatch_interval_seconds": 10,
        "orchestrator_profile": "agentporter-orchestrator",
        "auto_subscribe_on_create": True,
    }
    assert "default_assignee" not in orchestrator_config["kanban"]
    assert orchestrator_config["platform_toolsets"] == {"cli": ["kanban"]}
    for worker in rendered[:2]:
        worker_config = yaml.safe_load((worker.directory / "config.yaml").read_text())
        assert "kanban" not in worker_config
        assert "platform_toolsets" not in worker_config
    assert "does not execute" in (orchestrator / "SOUL.md").read_text(encoding="utf-8").lower()

    assert {marker.installation_id for marker in markers} == {str(installation_id)}
    assert {marker.product_id for marker in markers} == {PRODUCT_ID}
    assert {marker.component_id for marker in markers} == set(INSTALL_COMPONENT_IDS.values())
    for marker in markers:
        payload = json.loads(marker.model_dump_json())
        assert len(payload) == 5
        assert not any("name" in key for key in payload)


def test_render_includes_optional_provider_and_mechanical_boundary(tmp_path: Path) -> None:
    manifest = load_manifest(Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml")
    worker = manifest.workers["codex_5_3_small_worker"]
    worker.provider = "public-provider"

    rendered = render_staging(manifest, tmp_path, UUID("12345678-1234-4abc-8def-1234567890ab"))
    mechanical = rendered[1].directory

    config = yaml.safe_load((mechanical / "config.yaml").read_text())
    assert config["model"]["provider"] == "public-provider"
    assert "simpler and more mechanical" in (mechanical / "SOUL.md").read_text()
