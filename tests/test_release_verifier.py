from __future__ import annotations

import email.message
import hashlib
import io
import re
import stat
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.verify_release import ReleaseContract, verify_bootstrap, verify_release


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


def test_phase_f_contract_requires_activation_dispatch_and_observation_modules() -> None:
    repository = Path(__file__).parents[1]
    expected = {
        "activation_application.py",
        "activation_entry.py",
        "dispatch_application.py",
        "dispatch_planning.py",
        "kanban_runtime.py",
        "runtime_observation.py",
        "runtime_probe.py",
        "hermes_runtime.py",
        "readiness.py",
        "runtime_binding.py",
    }

    assert expected <= {path.name for path in (repository / "src" / "agentporter").glob("*.py")}
    project = (repository / "pyproject.toml").read_text(encoding="utf-8")
    assert 'agentporter-activate = "agentporter.activation_entry:main"' in project


def test_rejects_missing_explicit_phase_f_runtime_module(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    contract = replace(_contract(repo), required_modules=frozenset({"activation_entry.py"}))

    errors = verify_release(contract, [wheel, sdist])

    assert any("missing required runtime modules" in error for error in errors)
    assert any("missing required source runtime modules" in error for error in errors)


def test_accepts_complete_wheel_sdist_and_public_repository(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)

    assert verify_release(_contract(repo), [wheel, sdist]) == []


def test_bootstrap_contract_accepts_exact_wheel_checksum(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, _ = _artifacts(repo)
    bootstrap = repo / "install.sh"
    bootstrap.write_text(
        _valid_bootstrap_text(),
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    checksum = wheel.with_name(f"{wheel.name}.sha256")
    digest = __import__("hashlib").sha256(wheel.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {wheel.name}\n", encoding="ascii")

    contract = replace(
        _contract(repo),
        bootstrap_source_sha256=hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
    )

    assert verify_bootstrap(contract, wheel, checksum) == []


def test_bootstrap_contract_requires_three_public_entries_and_readback(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, _ = _artifacts(repo)
    bootstrap = repo / "install.sh"
    bootstrap.write_text(_valid_bootstrap_text(), encoding="utf-8")
    bootstrap.chmod(0o755)
    checksum = wheel.with_name(f"{wheel.name}.sha256")
    checksum.write_text(
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n", encoding="ascii"
    )
    contract = replace(
        _contract(repo),
        entry_points={
            "agentporter": "agentporter:main",
            "agentporter-activate": "agentporter.activation_entry:main",
            "agentporter-uninstall": "agentporter.uninstall_entry:main",
        },
        bootstrap_source_sha256=hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
    )

    errors = verify_bootstrap(contract, wheel, checksum)

    assert any("public entry publication/readback" in error for error in errors)


def _valid_bootstrap_text() -> str:
    return """#!/bin/sh
VERSION=0.1.0
RELEASE_BASE_URL=https://github.com/KumaCool/AgentPorter/releases/download/v0.1.0
WHEEL=agentporter-0.1.0-py3-none-any.whl
ENTRY_POINTS='agentporter'
PACKAGED_RESOURCES='agentporter/resources/workers.yaml'
REQUIRED_MODULES='agentporter'
for entry in $ENTRY_POINTS; do
    ENTRY=${VENV}/bin/${entry}
done
INSTALLED_VERSION=$(
    "$VENV/bin/python" -c 'import agentporter; print(agentporter.__version__)'
)
[ "$INSTALLED_VERSION" = "$VERSION" ] || fail 'installed package version does not match the release'
for resource in $PACKAGED_RESOURCES; do
    target = files(package).joinpath(relative)
    not target.is_file() or not target.read_bytes()
done
for module in $REQUIRED_MODULES; do
    importlib.import_module(sys.argv[1])
done
"""


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "WHEEL=agentporter-0.1.5-py3-none-any.whl",
            "WHEEL=agentporter-0.1.5-py3-none-any.whl\n"
            "RELEASE_BASE_URL=https://example.com/evil/releases/download/v9",
        ),
        ('"$RELEASE_BASE_URL/$WHEEL"', '"$ATTACKER_URL/$WHEEL"'),
        ("INSTALLED_VERSION=$(", "if false; then\nINSTALLED_VERSION=$("),
    ],
    ids=["release-url-reassignment", "alternate-download-variable", "dead-readback-block"],
)
def test_bootstrap_contract_rejects_any_source_change_even_when_tokens_survive(
    tmp_path: Path, old: str, new: str
) -> None:
    approved_bootstrap = Path(__file__).parents[1] / "install.sh"
    approved_source = approved_bootstrap.read_text(encoding="utf-8")
    assert old in approved_source
    repo = _repository(tmp_path)
    bootstrap = repo / "install.sh"
    bootstrap.write_text(approved_source.replace(old, new, 1), encoding="utf-8")
    bootstrap.chmod(0o755)
    wheel = repo / "agentporter-0.1.4-py3-none-any.whl"
    wheel.write_bytes(b"dummy")
    checksum = wheel.with_name(f"{wheel.name}.sha256")
    checksum.write_text(
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n",
        encoding="ascii",
    )
    contract = ReleaseContract(
        repository=repo,
        package="agentporter",
        version="0.1.4",
        dependencies=frozenset(),
        entry_points={
            "agentporter": "x",
            "agentporter-activate": "x",
            "agentporter-uninstall": "x",
        },
        resources=frozenset({"resources/workers.yaml"}),
        required_modules=frozenset(
            {
                "activation_application.py",
                "activation_entry.py",
                "dispatch_application.py",
                "dispatch_planning.py",
                "kanban_runtime.py",
                "runtime_observation.py",
                "runtime_probe.py",
            }
        ),
        bootstrap_source_sha256=hashlib.sha256(approved_bootstrap.read_bytes()).hexdigest(),
    )

    errors = verify_bootstrap(contract, wheel, checksum)

    assert "bootstrap: source SHA-256 does not match the release contract" in errors


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("v0.1.0\nWHEEL", "v0.1.9\nWHEEL", "release URL"),
        ("github.com/KumaCool", "example.com/KumaCool", "release URL"),
        (
            "KumaCool/AgentPorter/releases/download",
            "KumaCool/Other/releases/download",
            "release URL",
        ),
        ("ENTRY_POINTS='agentporter'", "ENTRY_POINTS='wrong-entry'", "entry-point rewrite"),
        ("PACKAGED_RESOURCES='agentporter/", "PACKAGED_RESOURCES='wrong/", "resource readback"),
        ("REQUIRED_MODULES='agentporter'", "REQUIRED_MODULES='wrong'", "required-module readback"),
        ("agentporter.__version__", "agentporter.wrong_version", "installed-version readback"),
        ("target.is_file()", "target.is_dir()", "resource readback semantics"),
        ("importlib.import_module", "importlib.find_spec", "module readback semantics"),
    ],
)
def test_bootstrap_contract_rejects_adversarial_download_and_readback_mutations(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    repo = _repository(tmp_path)
    wheel, _ = _artifacts(repo)
    bootstrap = repo / "install.sh"
    bootstrap.write_text(_valid_bootstrap_text().replace(old, new), encoding="utf-8")
    bootstrap.chmod(0o755)
    checksum = wheel.with_name(f"{wheel.name}.sha256")
    digest = __import__("hashlib").sha256(wheel.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {wheel.name}\n", encoding="ascii")

    errors = verify_bootstrap(_contract(repo), wheel, checksum)

    assert any(expected in error for error in errors)


def test_bootstrap_contract_rejects_mismatch_and_wrong_asset_name(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, _ = _artifacts(repo)
    bootstrap = repo / "install.sh"
    bootstrap.write_text("#!/bin/sh\nVERSION=9.9.9\nWHEEL=wrong.whl\n", encoding="utf-8")
    checksum = wheel.with_name("checksums.txt")
    checksum.write_text(f"{'0' * 64}  {wheel.name}\n", encoding="ascii")

    errors = verify_bootstrap(_contract(repo), wheel, checksum)

    assert "bootstrap: install.sh must be executable" in errors
    assert "bootstrap: pinned version does not match release contract" in errors
    assert "bootstrap: pinned wheel does not match release contract" in errors
    assert any("checksum asset must be named" in error for error in errors)


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


def _rewrite_sdist(sdist: Path, additions: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    originals: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(sdist, "r:gz") as archive:
        for member in archive.getmembers():
            extracted = archive.extractfile(member) if member.isfile() else None
            originals.append((member, extracted.read() if extracted is not None else b""))
    with tarfile.open(sdist, "w:gz") as archive:
        for member, data in [*originals, *additions]:
            archive.addfile(member, io.BytesIO(data) if member.isfile() else None)


def test_rejects_duplicate_ambiguous_encrypted_and_symlink_wheel_members(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("agentporter/core.py", b"duplicate\n")
        archive.writestr("agentporter\\ambiguous.py", b"bad\n")
        link = zipfile.ZipInfo("agentporter/link.py")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"../../outside")
        encrypted = zipfile.ZipInfo("agentporter/encrypted.py")
        encrypted.flag_bits |= 1
        archive.writestr(encrypted, b"bad\n")

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any("duplicate archive member" in error for error in errors)
    assert any("unsafe archive path" in error for error in errors)
    assert any("non-regular archive member" in error for error in errors)
    # zipfile clears unsupported encryption flags on write; the verifier still checks flag_bits.


def test_rejects_secret_and_oversized_wheel_authored_content(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("agentporter/core.py", b"password = 'abcdefghijklmnop'\n")
        archive.writestr("agentporter/large.txt", b"x" * (1024 * 1024 + 1))

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any("secret-like value" in error and wheel.name in error for error in errors)
    assert any("archive member too large" in error for error in errors)


def test_rejects_sdist_duplicate_link_escape_nonregular_and_secret(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    duplicate = tarfile.TarInfo("agentporter-0.1.0/src/agentporter/core.py")
    duplicate.size = len(b"secret = 'abcdefghijklmnop'\n")
    link = tarfile.TarInfo("agentporter-0.1.0/src/agentporter/link.py")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../../../outside"
    fifo = tarfile.TarInfo("agentporter-0.1.0/src/agentporter/fifo")
    fifo.type = tarfile.FIFOTYPE
    _rewrite_sdist(sdist, [(duplicate, b"secret = 'abcdefghijklmnop'\n"), (link, b""), (fifo, b"")])

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any("duplicate archive member" in error for error in errors)
    assert any("non-regular archive member" in error for error in errors)
    assert any("unsafe link target" in error for error in errors)
    assert any("secret-like value" in error and sdist.name in error for error in errors)


def test_encrypted_wheel_read_failure_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    original_read = zipfile.ZipFile.read

    def encrypted_read(
        self: zipfile.ZipFile, name: object, *args: object, **kwargs: object
    ) -> bytes:
        filename = name.filename if isinstance(name, zipfile.ZipInfo) else str(name)
        if filename == "agentporter/core.py":
            raise RuntimeError("File is encrypted, password required")
        return original_read(self, name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(zipfile.ZipFile, "read", encrypted_read)

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert errors == [f"{wheel.name}: unreadable wheel (RuntimeError)"]


def test_release_workflow_docs_urls_and_pyright_contract() -> None:
    repository = Path(__file__).parents[1]
    workflow = (repository / ".github/workflows/real-hermes.yml").read_text(encoding="utf-8")
    assert re.search(r"HERMES_REF: [0-9a-f]{40}", workflow)
    assert "git clone https://github.com/NousResearch/hermes-agent.git" in workflow
    assert 'checkout --detach "${HERMES_REF}"' in workflow
    assert 'rev-parse HEAD)" = "${HERMES_REF}"' in workflow
    assert "pip install --disable-pip-version-check -e /usr/local/lib/hermes-agent" in workflow
    assert "git+https://github.com/NousResearch/hermes-agent.git@${HERMES_REF}" not in workflow
    assert "importlib.metadata.version('hermes-agent') == '0.20.0'" in workflow
    assert "hermes-agent==${HERMES_VERSION}" not in workflow
    assert "sudo python -m venv" not in workflow
    assert 'ACCEPTANCE_PYTHON="$(python -c' in workflow
    assert 'sudo "${ACCEPTANCE_PYTHON}" -m venv /usr/local/lib/hermes-agent/venv' in workflow
    assert "sudo mv hermes-acceptance-venv" not in workflow
    assert "NousResearch/AgentPorter" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in repository.rglob("*.md")
        if ".git" not in path.parts
    )
    for guide in repository.glob("docs/04-installation-and-troubleshooting*.md"):
        text = guide.read_text(encoding="utf-8")
        assert "agentporter-uninstall" in text
    pyproject = (repository / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["src", "scripts", "install.py", "uninstall.py"]' in pyproject
