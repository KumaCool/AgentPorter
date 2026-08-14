from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from pydantic import ValidationError

from agentporter.manifest import load_manifest
from agentporter.models import WorkersManifest
from agentporter.render import render_staging
from agentporter.security import scan_staging
from tests.plan06_support import runtime_bindings

REPOSITORY_ROOT = Path(__file__).parents[1]
EXPECTED_WORKERS = ("bounded_worker", "mechanical_worker")


def _manifest_data() -> dict[str, object]:
    manifest = REPOSITORY_ROOT / "src/agentporter/resources/workers.yaml"
    return yaml.safe_load(manifest.read_text(encoding="utf-8"))


def test_distribution_uses_only_phase_1_native_hermes_fields(tmp_path: Path) -> None:
    manifest = load_manifest(REPOSITORY_ROOT / "src/agentporter/resources/workers.yaml")

    rendered = render_staging(
        manifest,
        tmp_path,
        UUID("12345678-1234-4abc-8def-1234567890ab"),
        bindings=runtime_bindings(),
    )

    for profile in rendered:
        distribution = yaml.safe_load(
            (profile.directory / "distribution.yaml").read_text(encoding="utf-8")
        )
        assert tuple(distribution) == (
            "name",
            "version",
            "description",
            "license",
            "distribution_owned",
        )
        assert distribution["name"] == profile.profile_name
        assert distribution["version"] == "0.1.8"
        assert "hermes_requires" not in distribution
        assert "minimum_hermes_version" not in distribution
    assert scan_staging(tmp_path) == ()


@pytest.mark.parametrize(
    "workers",
    [
        ("bounded_worker",),
        ("bounded_worker", "mechanical_worker", "extra_worker"),
        ("mechanical_worker", "bounded_worker"),
    ],
)
def test_manifest_workers_must_exactly_match_registry_in_declaration_order(
    workers: tuple[str, ...],
) -> None:
    data = _manifest_data()
    definitions = data["workers"]
    assert isinstance(definitions, dict)
    template = definitions["bounded_worker"]
    data["workers"] = {worker: definitions.get(worker, template) for worker in workers}

    with pytest.raises(ValidationError, match="workers must exactly match"):
        WorkersManifest.model_validate(data)


def test_load_manifest_rejects_duplicate_worker_key(tmp_path: Path) -> None:
    manifest = REPOSITORY_ROOT / "src/agentporter/resources/workers.yaml"
    source = manifest.read_text(encoding="utf-8")
    duplicate = source.replace(
        "  mechanical_worker:\n",
        "  bounded_worker:\n"
        "    display_name: Duplicate\n"
        "    tier: bounded\n"
        "    model: duplicate\n"
        "    reasoning_effort: max\n"
        "    description: duplicate\n"
        "    instructions: duplicate\n"
        "  mechanical_worker:\n",
    )
    path = tmp_path / "workers.yaml"
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        load_manifest(path)


def test_real_hermes_v020_installs_rendered_distributions_in_temporary_root(
    tmp_path: Path,
) -> None:
    hermes = Path("/usr/local/lib/hermes-agent/venv/bin/hermes")
    if not hermes.is_file():
        pytest.skip("machine Hermes v0.20 executable is unavailable")
    version = subprocess.run(
        [str(hermes), "--version"], check=True, capture_output=True, text=True
    ).stdout
    if "v0.20." not in version:
        pytest.skip(f"machine Hermes is not v0.20: {version.strip()}")

    staging = tmp_path / "staging"
    staging.mkdir()
    manifest = load_manifest(REPOSITORY_ROOT / "src/agentporter/resources/workers.yaml")
    rendered = render_staging(
        manifest, staging, UUID("12345678-1234-4abc-8def-1234567890ab"), bindings=runtime_bindings()
    )
    hermes_home = tmp_path / "hermes-home"
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HERMES_HOME": str(hermes_home),
        "HOME": str(home),
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
    }

    for profile in rendered:
        result = subprocess.run(
            [str(hermes), "profile", "install", str(profile.directory), "--yes"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    installed = hermes_home / "profiles"
    assert {path.name for path in installed.iterdir()} == {
        "agentporter-bounded-worker",
        "agentporter-mechanical-worker",
        "agentporter-orchestrator",
    }
