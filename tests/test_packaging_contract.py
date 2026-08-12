from __future__ import annotations

import importlib.resources
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml

import agentporter
from agentporter.models import WorkersManifest

ROOT = Path(__file__).parents[1]


def _project() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_version_has_one_package_source() -> None:
    config = _project()

    assert agentporter.__version__ == "0.1.3"
    assert config["project"]["dynamic"] == ["version"]  # type: ignore[index]
    assert "version" not in config["project"]  # type: ignore[operator]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {  # type: ignore[index]
        "attr": "agentporter.__version__"
    }


def test_authoritative_manifest_is_packaged_under_agentporter() -> None:
    config = _project()
    package_data = config["tool"]["setuptools"]["package-data"]  # type: ignore[index]

    assert package_data == {"agentporter.resources": ["workers.yaml"]}
    assert not (ROOT / "workers.yaml").exists()
    resource = importlib.resources.files("agentporter.resources").joinpath("workers.yaml")
    data = yaml.safe_load(resource.read_text(encoding="utf-8"))
    assert WorkersManifest.model_validate(data).version == 1


def test_installer_uses_packaged_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Path] = []

    class Workflow:
        status = agentporter.WorkflowStatus.CANCELLED

    class Result:
        workflow = Workflow()
        transaction = None

    def fake_installer(manifest: Path, staging: Path, env: dict[str, str]) -> Result:
        assert manifest.is_file()
        captured.append(manifest)
        return Result()

    monkeypatch.setattr(agentporter, "run_installer", fake_installer)
    with pytest.raises(SystemExit, match="cancelled"):
        agentporter.run_product_installer()

    assert captured
    assert (
        captured[0].read_bytes()
        == importlib.resources.files("agentporter.resources").joinpath("workers.yaml").read_bytes()
    )


def test_project_declares_install_activation_and_uninstall_console_scripts() -> None:
    scripts = _project()["project"]["scripts"]  # type: ignore[index]
    assert scripts == {
        "agentporter": "agentporter:main",
        "agentporter-activate": "agentporter.activation_entry:main",
        "agentporter-uninstall": "agentporter.uninstall_entry:main",
    }


def test_built_wheel_contains_resource_and_both_console_entries(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheelhouse"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(wheel_dir.glob("agentporter-*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert "agentporter/resources/workers.yaml" in names
        assert "agentporter/uninstall_entry.py" in names
        entry_points = archive.read("agentporter-0.1.3.dist-info/entry_points.txt").decode()

    assert "agentporter = agentporter:main" in entry_points
    assert "agentporter-activate = agentporter.activation_entry:main" in entry_points
    assert "agentporter-uninstall = agentporter.uninstall_entry:main" in entry_points


def test_built_sdist_contains_package_but_not_tests_or_caches(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    archives = tuple(tmp_path.glob("agentporter-*.tar.gz"))
    assert len(archives) == 1

    with tarfile.open(archives[0]) as archive:
        names = set(archive.getnames())

    prefix = "agentporter-0.1.3/"
    assert prefix + "src/agentporter/resources/workers.yaml" in names
    assert prefix + "src/agentporter/uninstall_entry.py" in names
    assert not any(name.startswith(prefix + "tests/") for name in names)
    assert not any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names)
