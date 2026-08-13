from __future__ import annotations

import email.message
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.verify_release import ReleaseContract, main, verify_bootstrap, verify_release


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


def _standalone_helper_assets(repo: Path, wheel: Path, sdist: Path) -> tuple[Path, Path]:
    helper_bytes = b'"""transaction helper"""\nVALUE = 1\n'
    (repo / "src" / "agentporter" / "bootstrap_txn.py").write_bytes(helper_bytes)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("agentporter/bootstrap_txn.py", helper_bytes)
    member = tarfile.TarInfo("agentporter-0.1.0/src/agentporter/bootstrap_txn.py")
    member.size = len(helper_bytes)
    _rewrite_sdist(sdist, [(member, helper_bytes)])
    helper = repo / "dist" / "bootstrap_txn.py"
    helper.write_bytes(helper_bytes)
    sidecar = helper.with_name(f"{helper.name}.sha256")
    sidecar.write_text(
        f"{hashlib.sha256(helper_bytes).hexdigest()}  {helper.name}\n", encoding="utf-8"
    )
    return helper, sidecar


def _helper_contract(repo: Path) -> ReleaseContract:
    return replace(_contract(repo), standalone_helper_name="bootstrap_txn.py")


def test_accepts_standalone_helper_sidecar_and_identical_archive_copies(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    helper, sidecar = _standalone_helper_assets(repo, wheel, sdist)

    assert verify_release(_helper_contract(repo), [wheel, sdist], helper, sidecar) == []


@pytest.mark.parametrize("missing", ["helper", "sidecar"])
def test_required_standalone_helper_assets_fail_closed_when_missing(
    tmp_path: Path, missing: str
) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    helper, sidecar = _standalone_helper_assets(repo, wheel, sdist)
    (helper if missing == "helper" else sidecar).unlink()

    errors = verify_release(_helper_contract(repo), [wheel, sdist], helper, sidecar)

    assert any(f"standalone helper {missing}" in error and "missing" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("directory-helper", "regular file"),
        ("symlink-helper", "regular file"),
        ("oversized-helper", "size exceeds limit"),
        ("non-utf8-helper", "UTF-8"),
        ("wrong-helper-path", "helper must be named"),
        ("directory-sidecar", "regular file"),
        ("oversized-sidecar", "size exceeds limit"),
        ("non-utf8-sidecar", "UTF-8"),
        ("wrong-sidecar-path", "sidecar must be named"),
        ("multiple-sidecar-records", "exactly one record"),
        ("wrong-sidecar-grammar", "invalid grammar"),
        ("wrong-sidecar-basename", "exact helper basename"),
        ("wrong-sidecar-hash", "does not match helper bytes"),
        ("replaced-helper", "does not match wheel package copy"),
        ("replaced-wheel-copy", "does not match wheel package copy"),
        ("replaced-sdist-copy", "does not match sdist package copy"),
    ],
)
def test_standalone_helper_validation_fails_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    helper, sidecar = _standalone_helper_assets(repo, wheel, sdist)
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    if mutation == "directory-helper":
        helper.unlink()
        helper.mkdir()
    elif mutation == "symlink-helper":
        helper.unlink()
        helper.symlink_to(repo / "src" / "agentporter" / "bootstrap_txn.py")
    elif mutation == "oversized-helper":
        helper.write_bytes(b"x" * (1024 * 1024 + 1))
    elif mutation == "non-utf8-helper":
        helper.write_bytes(b"\xff")
    elif mutation == "wrong-helper-path":
        renamed = helper.with_name("replacement.py")
        helper.rename(renamed)
        helper = renamed
    elif mutation == "directory-sidecar":
        sidecar.unlink()
        sidecar.mkdir()
    elif mutation == "oversized-sidecar":
        sidecar.write_bytes(b"x" * 4097)
    elif mutation == "non-utf8-sidecar":
        sidecar.write_bytes(b"\xff")
    elif mutation == "wrong-sidecar-path":
        renamed = sidecar.with_name("checksums.txt")
        sidecar.rename(renamed)
        sidecar = renamed
    elif mutation == "multiple-sidecar-records":
        sidecar.write_text(f"{digest}  {helper.name}\n{digest}  {helper.name}\n", encoding="utf-8")
    elif mutation == "wrong-sidecar-grammar":
        sidecar.write_text(f"{digest} *{helper.name}\n", encoding="utf-8")
    elif mutation == "wrong-sidecar-basename":
        sidecar.write_text(f"{digest}  path/{helper.name}\n", encoding="utf-8")
    elif mutation == "wrong-sidecar-hash":
        sidecar.write_text(f"{'0' * 64}  {helper.name}\n", encoding="utf-8")
    elif mutation == "replaced-helper":
        helper.write_text('VALUE = "replacement"\n', encoding="utf-8")
        sidecar.write_text(
            f"{hashlib.sha256(helper.read_bytes()).hexdigest()}  {helper.name}\n", encoding="utf-8"
        )
    elif mutation == "replaced-wheel-copy":
        replacement = repo / "dist" / "replacement.whl"
        with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(replacement, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename == "agentporter/bootstrap_txn.py":
                    data = b"VALUE = 2\n"
                target.writestr(info, data)
        replacement.replace(wheel)
    elif mutation == "replaced-sdist-copy":
        replacement = b"VALUE = 2\n"
        member = tarfile.TarInfo("agentporter-0.1.0/src/agentporter/bootstrap_txn.py")
        member.size = len(replacement)
        _rewrite_sdist(sdist, [(member, replacement)])

    errors = verify_release(_helper_contract(repo), [wheel, sdist], helper, sidecar)

    assert any(expected in error for error in errors)


def test_legacy_release_contract_does_not_require_standalone_assets(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)

    assert verify_release(_contract(repo), [wheel, sdist]) == []


def test_v016_cli_call_requires_and_accepts_standalone_assets(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    dist = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(dist)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    helper = dist / "bootstrap_txn.py"
    helper.write_bytes((repository / "src" / "agentporter" / "bootstrap_txn.py").read_bytes())
    sidecar = dist / "bootstrap_txn.py.sha256"
    sidecar.write_text(
        f"{hashlib.sha256(helper.read_bytes()).hexdigest()}  bootstrap_txn.py\n", encoding="utf-8"
    )

    result = main(
        [
            str(wheel),
            str(sdist),
            "--repository",
            str(repository),
            "--version",
            "0.1.8",
            "--dependency",
            "pydantic<3,>=2",
            "--dependency",
            "PyYAML<7,>=6",
            "--entry-point",
            "agentporter=agentporter:main",
            "--entry-point",
            "agentporter-activate=agentporter.activation_entry:main",
            "--entry-point",
            "agentporter-uninstall=agentporter.uninstall_entry:main",
            "--resource",
            "resources/workers.yaml",
            "--required-module",
            "bootstrap_txn.py",
            "--standalone-helper",
            str(helper),
            "--standalone-helper-checksum",
            str(sidecar),
        ]
    )

    assert result == 0


def test_cli_rejects_partial_standalone_asset_arguments(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)

    result = main(
        [
            str(wheel),
            str(sdist),
            "--repository",
            str(repo),
            "--version",
            "0.1.0",
            "--standalone-helper",
            str(repo / "dist" / "bootstrap_txn.py"),
        ]
    )

    assert result == 2


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


def test_bootstrap_contract_requires_transaction_helper_release_assets(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    wheel, _ = _artifacts(repo)
    bootstrap = repo / "install.sh"
    bootstrap.write_text(
        _valid_bootstrap_text().replace("TXN_HELPER=bootstrap_txn.py\n", ""), encoding="utf-8"
    )
    bootstrap.chmod(0o755)
    checksum = wheel.with_name(f"{wheel.name}.sha256")
    checksum.write_text(
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n", encoding="ascii"
    )

    errors = verify_bootstrap(_contract(repo), wheel, checksum)

    assert any("transaction helper release asset" in error for error in errors)


def _valid_bootstrap_text() -> str:
    return """#!/bin/sh
VERSION=0.1.0
RELEASE_BASE_URL=https://github.com/KumaCool/AgentPorter/releases/download/v0.1.0
WHEEL=agentporter-0.1.0-py3-none-any.whl
ENTRY_POINTS='agentporter'
PACKAGED_RESOURCES='agentporter/resources/workers.yaml'
REQUIRED_MODULES='agentporter'
TXN_HELPER=bootstrap_txn.py
TXN_HELPER_CHECKSUM=${TXN_HELPER}.sha256
"$RELEASE_BASE_URL/$asset"
verify_checksum "$STAGING/$TXN_HELPER" "$STAGING/$TXN_HELPER_CHECKSUM"
"$PYTHON" "$INSTALL_ROOT/$TXN_HELPER" apply "$SPEC"
"$PYTHON" "$INSTALL_ROOT/$TXN_HELPER" recover "$SPEC"
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
            "WHEEL=agentporter-0.1.8-py3-none-any.whl",
            "WHEEL=agentporter-0.1.8-py3-none-any.whl\n"
            "RELEASE_BASE_URL=https://example.com/evil/releases/download/v9",
        ),
        ('"$RELEASE_BASE_URL/$asset"', '"$ATTACKER_URL/$asset"'),
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


@pytest.mark.parametrize("suffix", ["json", "yaml"])
def test_structured_secret_value_semantics_and_binary_fail_closed(
    tmp_path: Path, suffix: str
) -> None:
    repo = _repository(tmp_path)
    secret = repo / "src" / "agentporter" / f"secret.{suffix}"
    placeholder = repo / "src" / "agentporter" / f"placeholder.{suffix}"
    binary = repo / "src" / "agentporter" / "opaque.bin"
    if suffix == "json":
        secret.write_text(json.dumps({"password": "!Abc def$Ghij#Klmn"}), encoding="utf-8")
        placeholder.write_text(json.dumps({"token": "replace-with-your-token"}), encoding="utf-8")
    else:
        secret.write_text('password: "!Abc def$Ghij#Klmn"\n', encoding="utf-8")
        placeholder.write_text('token: "replace-with-your-token"\n', encoding="utf-8")
    wheel, sdist = _artifacts(repo)
    binary.write_bytes(b"token=abcdefghijklmnop\xff")

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any(secret.name in error and "secret-like value" in error for error in errors)
    assert not any(placeholder.name in error and "secret-like value" in error for error in errors)
    assert any(binary.name in error and "non-UTF-8" in error for error in errors)


@pytest.mark.parametrize("suffix", ["json", "yaml"])
@pytest.mark.parametrize("value", [7, True, ["configured"], {"configured": True}])
def test_structured_sensitive_keys_reject_nonempty_nonstring_values(
    tmp_path: Path, suffix: str, value: object
) -> None:
    repo = _repository(tmp_path)
    source = repo / "src" / "agentporter" / f"nonstring-secret.{suffix}"
    if suffix == "json":
        source.write_text(json.dumps({"token": value}), encoding="utf-8")
    else:
        import yaml

        source.write_text(yaml.safe_dump({"token": value}), encoding="utf-8")
    wheel, sdist = _artifacts(repo)

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any(source.name in error and "secret-like value" in error for error in errors)


@pytest.mark.parametrize("secret_key", ["token", "api_key", "password"])
def test_rejects_structured_json_secret_fields(tmp_path: Path, secret_key: str) -> None:
    repo = _repository(tmp_path)
    secret_file = repo / "src" / "agentporter" / f"structured-{secret_key}.json"
    secret_file.write_text(
        f'{{"nested":{{"{secret_key}":"abcdefghijklmnop"}}}}\n',
        encoding="utf-8",
    )
    wheel, sdist = _artifacts(repo)

    errors = verify_release(_contract(repo), [wheel, sdist])

    relative = secret_file.relative_to(repo).as_posix()
    assert any("repository: secret-like value" in error and relative in error for error in errors)


@pytest.mark.parametrize("suffix", ["json", "yaml"])
@pytest.mark.parametrize("secret_key", ["token", "api_key", "password"])
def test_rejects_nested_structured_secrets_in_repository_and_archives(
    tmp_path: Path, suffix: str, secret_key: str
) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    if suffix == "json":
        payload = f'{{"outer": [{{"{secret_key}": "abcdefghijklmnop"}}]}}\n'
    else:
        payload = f"outer:\n  - {secret_key}: abcdefghijklmnop\n"
    source = repo / "src" / "agentporter" / f"secret.{suffix}"
    source.write_text(payload, encoding="utf-8")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(f"agentporter/secret.{suffix}", payload)
    member = tarfile.TarInfo(f"agentporter-0.1.0/src/agentporter/secret.{suffix}")
    encoded = payload.encode()
    member.size = len(encoded)
    _rewrite_sdist(sdist, [(member, encoded)])

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any(error.startswith("repository:") and "secret-like value" in error for error in errors)
    assert any(error.startswith(wheel.name) and "secret-like value" in error for error in errors)
    assert any(error.startswith(sdist.name) and "secret-like value" in error for error in errors)


@pytest.mark.parametrize("suffix", ["json", "yaml"])
@pytest.mark.parametrize("secret_key", ["token", "api_key", "password"])
def test_rejects_short_symbol_structured_secrets_in_repository_and_archives(
    tmp_path: Path, suffix: str, secret_key: str
) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    if suffix == "json":
        payload = json.dumps({"outer": [{secret_key: "p@$$w0rd!"}]}) + "\n"
    else:
        payload = f'outer:\n  - {secret_key}: "p@$$w0rd!"\n'
    source = repo / "src" / "agentporter" / f"short-secret.{suffix}"
    source.write_text(payload, encoding="utf-8")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(f"agentporter/short-secret.{suffix}", payload)
    member = tarfile.TarInfo(f"agentporter-0.1.0/src/agentporter/short-secret.{suffix}")
    encoded = payload.encode()
    member.size = len(encoded)
    _rewrite_sdist(sdist, [(member, encoded)])

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert any(error.startswith("repository:") and "secret-like value" in error for error in errors)
    assert any(error.startswith(wheel.name) and "secret-like value" in error for error in errors)
    assert any(error.startswith(sdist.name) and "secret-like value" in error for error in errors)


@pytest.mark.parametrize("suffix", ["json", "yaml"])
@pytest.mark.parametrize(
    ("secret_key", "value"),
    [
        (key, value)
        for key, label in (("token", "token"), ("api_key", "api-key"), ("password", "password"))
        for value in (
            None,
            "",
            "example",
            "changeme",
            "not configured",
            f"your-{label}-here",
            f"replace-with-your-{label}",
        )
    ],
)
def test_accepts_empty_and_benign_structured_secret_placeholders(
    tmp_path: Path, suffix: str, secret_key: str, value: str | None
) -> None:
    repo = _repository(tmp_path)
    wheel, sdist = _artifacts(repo)
    if suffix == "json":
        payload = json.dumps({"outer": {secret_key: value}}) + "\n"
    else:
        rendered = "null" if value is None else json.dumps(value)
        payload = f"outer:\n  {secret_key}: {rendered}\n"
    source = repo / "src" / "agentporter" / f"placeholder.{suffix}"
    source.write_text(payload, encoding="utf-8")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(f"agentporter/placeholder.{suffix}", payload)
    member = tarfile.TarInfo(f"agentporter-0.1.0/src/agentporter/placeholder.{suffix}")
    encoded = payload.encode()
    member.size = len(encoded)
    _rewrite_sdist(sdist, [(member, encoded)])

    errors = verify_release(_contract(repo), [wheel, sdist])

    assert not any("secret-like value" in error for error in errors)


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
