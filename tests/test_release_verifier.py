from __future__ import annotations

import email.message
import io
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

from scripts.verify_release import ReleaseContract, verify_release


def _metadata() -> bytes:
    message = email.message.Message()
    message["Metadata-Version"] = "2.3"
    message["Name"] = "agentporter"
    message["Version"] = "0.1.0"
    message["License-Expression"] = "MIT"
    message["Requires-Python"] = ">=3.11"
    message["Requires-Dist"] = "pydantic<3,>=2"
    message["Requires-Dist"] = "PyYAML<7,>=6"
    message["Description-Content-Type"] = "text/markdown"
    return message.as_bytes() + b"\n# AgentPorter\n"


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "src" / "agentporter"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("def main(): pass\n", encoding="utf-8")
    (package / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "resources").mkdir()
    (package / "resources" / "workers.yaml").write_text("version: 1\n", encoding="utf-8")
    (repo / "README.md").write_text("# AgentPorter\n\n[Security](SECURITY.md)\n", encoding="utf-8")
    (repo / "SECURITY.md").write_text("# Security\n", encoding="utf-8")
    (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
    return repo


def _artifacts(repo: Path) -> tuple[Path, Path]:
    dist = repo / "dist"
    dist.mkdir()
    wheel = dist / "agentporter-0.1.0-py3-none-any.whl"
    wheel_files = {
        "agentporter/__init__.py": b"def main(): pass\n",
        "agentporter/core.py": b"VALUE = 1\n",
        "agentporter/resources/workers.yaml": b"version: 1\n",
        "agentporter-0.1.0.dist-info/METADATA": _metadata(),
        "agentporter-0.1.0.dist-info/entry_points.txt": (
            b"[console_scripts]\nagentporter = agentporter:main\n"
        ),
        "agentporter-0.1.0.dist-info/licenses/LICENSE": b"MIT\n",
        "agentporter-0.1.0.dist-info/RECORD": b"",
        "agentporter-0.1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
    }
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in wheel_files.items():
            archive.writestr(name, data)

    sdist = dist / "agentporter-0.1.0.tar.gz"
    prefix = "agentporter-0.1.0/"
    sdist_files = {
        "PKG-INFO": _metadata(),
        "README.md": (repo / "README.md").read_bytes(),
        "LICENSE": b"MIT\n",
        "pyproject.toml": b"[build-system]\n",
        "src/agentporter/__init__.py": b"def main(): pass\n",
        "src/agentporter/core.py": b"VALUE = 1\n",
        "src/agentporter/resources/workers.yaml": b"version: 1\n",
    }
    with tarfile.open(sdist, "w:gz") as archive:
        for name, data in sdist_files.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return wheel, sdist


def _contract(repo: Path) -> ReleaseContract:
    return ReleaseContract(
        repository=repo,
        package="agentporter",
        version="0.1.0",
        dependencies=frozenset({"pydantic<3,>=2", "PyYAML<7,>=6"}),
        entry_points={"agentporter": "agentporter:main"},
        resources=frozenset({"resources/workers.yaml"}),
    )


def test_accepts_complete_wheel_sdist_and_public_repository(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)

    assert verify_release(_contract(repo), [wheel, sdist]) == []


def test_rejects_missing_resource_and_wrong_entry_point(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    contract = replace(
        _contract(repo),
        entry_points={"agentporter": "agentporter:wrong"},
        resources=frozenset({"resources/workers.yaml", "resources/missing.txt"}),
    )

    errors = verify_release(contract, [wheel, sdist])

    assert any("package content mismatch" in error for error in errors)
    assert any("entry points mismatch" in error for error in errors)
    assert any("source package content mismatch" in error for error in errors)


def test_rejects_secret_broken_link_and_forbidden_archive_path(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    (repo / "README.md").write_text(
        "# AgentPorter\n\n[Missing](docs/missing.md)\n\napi_key = 'abcdefghijklmnopqrst'\n",
        encoding="utf-8",
    )
    wheel, sdist = _artifacts(repo)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("tests/private.py", "token = 'abcdefghijk'\n")

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any("secret-like value" in error for error in errors)
    assert any("broken link" in error for error in errors)
    assert any("forbidden archive path" in error for error in errors)


def test_rejects_wrong_metadata_and_extra_artifact(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    extra = repo / "dist" / "checksums.txt"
    extra.write_text("not an artifact\n", encoding="utf-8")
    contract = replace(_contract(repo), version="9.9.9")

    errors = verify_release(contract, [wheel, sdist, extra])

    assert errors == ["artifacts: require exactly one wheel and one .tar.gz sdist"]
