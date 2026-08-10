from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from agentporter.manifest import load_manifest
from agentporter.render import render_staging
from agentporter.security import StagingViolation, scan_staging


def _valid_staging(tmp_path: Path) -> Path:
    manifest = load_manifest(Path(__file__).parents[1] / "workers.yaml")
    render_staging(manifest, tmp_path, UUID("12345678-1234-4abc-8def-1234567890ab"))
    return tmp_path


def test_scan_accepts_explicitly_allowlisted_staging(tmp_path: Path) -> None:
    assert scan_staging(_valid_staging(tmp_path)) == ()


def test_scan_rejects_unexpected_artifact(tmp_path: Path) -> None:
    root = _valid_staging(tmp_path)
    (root / "luna_worker" / "auth.json").write_text("{}")

    with pytest.raises(StagingViolation, match="unexpected-path"):
        scan_staging(root)


def test_scan_rejects_symlink_even_when_it_points_inside_staging(tmp_path: Path) -> None:
    root = _valid_staging(tmp_path)
    profile = root / "luna_worker"
    (profile / "SOUL.md").unlink()
    (profile / "SOUL.md").symlink_to(profile / "config.yaml")

    with pytest.raises(StagingViolation, match="symlink"):
        scan_staging(root)


@pytest.mark.parametrize(
    ("filename", "payload", "category"),
    [
        ("config.yaml", "model:\n  api_key: sk-live-example\n", "secret"),
        ("config.yaml", "model:\n  base_url: https://service.example.com\n", "private-endpoint"),
        ("SOUL.md", "Read /home/alice/private/data\n", "private-path"),
        ("SOUL.md", "Read C:\\Users\\Alice\\private\\data\n", "private-path"),
    ],
)
def test_scan_rejects_sensitive_content(
    tmp_path: Path, filename: str, payload: str, category: str
) -> None:
    root = _valid_staging(tmp_path)
    (root / "luna_worker" / filename).write_text(payload)

    with pytest.raises(StagingViolation, match=category) as error:
        scan_staging(root)
    assert payload.strip() not in str(error.value)


def test_scan_revalidates_artifact_schema(tmp_path: Path) -> None:
    root = _valid_staging(tmp_path)
    marker_path = root / "luna_worker" / "agentporter-profile.json"
    marker = json.loads(marker_path.read_text())
    marker["profile_name"] = "luna_worker"
    marker_path.write_text(json.dumps(marker))

    with pytest.raises(StagingViolation, match="invalid-schema"):
        scan_staging(root)


def test_scan_rejects_marker_component_that_does_not_match_profile(tmp_path: Path) -> None:
    root = _valid_staging(tmp_path)
    first = root / "luna_worker" / "agentporter-profile.json"
    second = root / "codex-5-3-small-worker" / "agentporter-profile.json"
    first_payload = json.loads(first.read_text())
    second_payload = json.loads(second.read_text())
    first_payload["component_id"] = second_payload["component_id"]
    first.write_text(json.dumps(first_payload))

    with pytest.raises(StagingViolation, match="invalid-schema"):
        scan_staging(root)


def test_scan_rejects_markers_with_different_installation_ids(tmp_path: Path) -> None:
    root = _valid_staging(tmp_path)
    marker_path = root / "luna_worker" / "agentporter-profile.json"
    marker = json.loads(marker_path.read_text())
    marker["installation_id"] = "87654321-4321-4abc-8def-ba0987654321"
    marker_path.write_text(json.dumps(marker))

    with pytest.raises(StagingViolation, match="invalid-schema"):
        scan_staging(root)


def test_scan_rejects_empty_soul(tmp_path: Path) -> None:
    root = _valid_staging(tmp_path)
    (root / "luna_worker" / "SOUL.md").write_text("")

    with pytest.raises(StagingViolation, match="invalid-schema"):
        scan_staging(root)
