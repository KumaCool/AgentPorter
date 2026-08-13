#!/usr/bin/env python3
"""Fail-closed inspection of AgentPorter source and distribution artifacts."""

from __future__ import annotations

import argparse
import configparser
import email
import hashlib
import hmac
import re
import stat
import tarfile
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.message import Message
from pathlib import Path, PurePosixPath

_METADATA_ALLOWLIST = {
    "METADATA",
    "WHEEL",
    "RECORD",
    "entry_points.txt",
    "licenses/LICENSE",
    "top_level.txt",
}
_FORBIDDEN_PARTS = {
    ".git",
    ".hermes",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "tests",
    ".env",
    "private",
    "credentials",
    "sessions",
    "memories",
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|password|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_./+\-=]{16,}"
)
_TOKEN_LITERAL = re.compile(r"(?i)token\s*[:=]\s*[\"'][A-Za-z0-9_./+\-=]{16,}[\"']")
_LINK = re.compile(r"(?<!!)\[[^]]*]\(([^) #]+)(?:#[^)]+)?\)")
_MAX_MEMBER_SIZE = 1024 * 1024
_MAX_ARCHIVE_SIZE = 5 * 1024 * 1024


@dataclass(frozen=True)
class ReleaseContract:
    repository: Path
    package: str
    version: str
    dependencies: frozenset[str]
    entry_points: Mapping[str, str]
    resources: frozenset[str]
    required_modules: frozenset[str] = frozenset()
    bootstrap_source_sha256: str | None = None


def _canonical_requirement(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _metadata_errors(metadata: Message, contract: ReleaseContract, label: str) -> list[str]:
    errors: list[str] = []
    expected = {
        "Name": contract.package,
        "Version": contract.version,
        "License-Expression": "MIT",
        "Description-Content-Type": "text/markdown",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            errors.append(f"{label}: metadata {key!r} must equal {value!r}")
    if metadata.get("Requires-Python") != ">=3.11":
        errors.append(f"{label}: metadata 'Requires-Python' must equal '>=3.11'")
    actual_dependencies = {
        _canonical_requirement(value) for value in metadata.get_all("Requires-Dist", [])
    }
    expected_dependencies = {_canonical_requirement(value) for value in contract.dependencies}
    if actual_dependencies != expected_dependencies:
        errors.append(f"{label}: dependency metadata mismatch")
    return errors


def _normalized_archive_name(name: str) -> str:
    return unicodedata.normalize("NFC", name.rstrip("/")).casefold()


def _path_errors(names: Sequence[str] | set[str], label: str) -> list[str]:
    errors: list[str] = []
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or re.match(r"^[A-Za-z]:", name) is not None
        ):
            errors.append(f"{label}: unsafe archive path {name!r}")
        if set(path.parts) & _FORBIDDEN_PARTS or any(part.endswith(".pyc") for part in path.parts):
            errors.append(f"{label}: forbidden archive path {name!r}")
    return errors


def _duplicate_errors(names: Sequence[str], label: str) -> list[str]:
    raw = Counter(name.rstrip("/") for name in names)
    normalized = Counter(_normalized_archive_name(name) for name in names)
    errors = [
        f"{label}: duplicate archive member {name!r}" for name, count in raw.items() if count > 1
    ]
    errors.extend(
        f"{label}: duplicate normalized archive member {name!r}"
        for name, count in normalized.items()
        if count > 1
    )
    return errors


def _content_errors(data: bytes, name: str, label: str) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    if _SECRET_ASSIGNMENT.search(text) or _TOKEN_LITERAL.search(text):
        return [f"{label}: secret-like value in {name!r}"]
    return []


def _wheel_errors(path: Path, contract: ReleaseContract) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        errors.extend(_duplicate_errors([info.filename for info in infos], path.name))
        names = {info.filename.rstrip("/") for info in infos if not info.is_dir()}
        errors.extend(_path_errors([info.filename for info in infos], path.name))
        total_size = 0
        for info in infos:
            if info.is_dir():
                continue
            total_size += info.file_size
            if info.flag_bits & 1:
                errors.append(f"{path.name}: encrypted archive member {info.filename!r}")
            mode_type = stat.S_IFMT(info.external_attr >> 16) if info.create_system == 3 else 0
            if mode_type not in (0, stat.S_IFREG):
                errors.append(f"{path.name}: non-regular archive member {info.filename!r}")
            if info.file_size > _MAX_MEMBER_SIZE:
                errors.append(f"{path.name}: archive member too large {info.filename!r}")
                continue
            if total_size <= _MAX_ARCHIVE_SIZE and not info.filename.endswith("/RECORD"):
                errors.extend(_content_errors(archive.read(info), info.filename, path.name))
        if total_size > _MAX_ARCHIVE_SIZE:
            errors.append(f"{path.name}: archive expanded size exceeds limit")
        dist_info = f"{contract.package}-{contract.version}.dist-info"
        metadata_name = f"{dist_info}/METADATA"
        entry_name = f"{dist_info}/entry_points.txt"
        required = {metadata_name, entry_name, f"{dist_info}/licenses/LICENSE"}
        missing = required - names
        if missing:
            errors.append(f"{path.name}: missing required files: {sorted(missing)}")
            return errors
        package_files = {
            name.removeprefix(f"{contract.package}/")
            for name in names
            if name.startswith(f"{contract.package}/")
        }
        expected_modules = {
            item.relative_to(contract.repository / "src" / contract.package).as_posix()
            for item in (contract.repository / "src" / contract.package).rglob("*.py")
        }
        expected_package = expected_modules | set(contract.resources)
        if package_files != expected_package:
            errors.append(f"{path.name}: package content mismatch")
        missing_modules = contract.required_modules - package_files
        if missing_modules:
            errors.append(
                f"{path.name}: missing required runtime modules: {sorted(missing_modules)}"
            )
        unexpected_metadata = {
            name.removeprefix(f"{dist_info}/") for name in names if name.startswith(f"{dist_info}/")
        } - _METADATA_ALLOWLIST
        if unexpected_metadata:
            errors.append(f"{path.name}: unexpected distribution metadata files")
        metadata = email.message_from_bytes(archive.read(metadata_name))
        errors.extend(_metadata_errors(metadata, contract, path.name))
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entry_name).decode("utf-8"))
        actual_entries = (
            dict(parser.items("console_scripts")) if parser.has_section("console_scripts") else {}
        )
        if actual_entries != dict(contract.entry_points):
            errors.append(f"{path.name}: console entry points mismatch")
    return errors


def _sdist_errors(path: Path, contract: ReleaseContract) -> list[str]:
    errors: list[str] = []
    with tarfile.open(path, "r:gz") as archive:
        all_members = archive.getmembers()
        errors.extend(_duplicate_errors([member.name for member in all_members], path.name))
        errors.extend(_path_errors([member.name for member in all_members], path.name))
        total_size = 0
        for member in all_members:
            if not (member.isfile() or member.isdir()):
                errors.append(f"{path.name}: non-regular archive member {member.name!r}")
                if member.issym() or member.islnk():
                    target = PurePosixPath(member.name).parent / member.linkname
                    if member.linkname.startswith(("/", "\\")) or ".." in target.parts:
                        errors.append(f"{path.name}: unsafe link target {member.linkname!r}")
            if member.isfile():
                total_size += member.size
                if member.size > _MAX_MEMBER_SIZE:
                    errors.append(f"{path.name}: archive member too large {member.name!r}")
                    continue
                extracted = archive.extractfile(member)
                if extracted is not None and total_size <= _MAX_ARCHIVE_SIZE:
                    errors.extend(_content_errors(extracted.read(), member.name, path.name))
        if total_size > _MAX_ARCHIVE_SIZE:
            errors.append(f"{path.name}: archive expanded size exceeds limit")
        members = [member for member in all_members if member.isfile()]
        names = {member.name for member in members}
        roots = {PurePosixPath(name).parts[0] for name in names}
        expected_root = f"{contract.package}-{contract.version}"
        if roots != {expected_root}:
            return [*errors, f"{path.name}: archive must have exactly root {expected_root!r}"]
        relative_names = {str(PurePosixPath(name).relative_to(expected_root)) for name in names}
        required = {"PKG-INFO", "README.md", "LICENSE", "pyproject.toml"}
        if not required <= relative_names:
            errors.append(f"{path.name}: missing required source metadata")
        package_root = contract.repository / "src" / contract.package
        expected_modules = {
            f"src/{contract.package}/{item.relative_to(package_root).as_posix()}"
            for item in package_root.rglob("*.py")
        }
        expected_resources = {f"src/{contract.package}/{item}" for item in contract.resources}
        expected_package = expected_modules | expected_resources
        actual_package = {
            name for name in relative_names if name.startswith(f"src/{contract.package}/")
        }
        if actual_package != expected_package:
            errors.append(f"{path.name}: source package content mismatch")
        required_modules = {
            f"src/{contract.package}/{module}" for module in contract.required_modules
        }
        missing_modules = required_modules - actual_package
        if missing_modules:
            errors.append(
                f"{path.name}: missing required source runtime modules: {sorted(missing_modules)}"
            )
        pkg_info = archive.extractfile(f"{expected_root}/PKG-INFO")
        if pkg_info is not None:
            errors.extend(
                _metadata_errors(email.message_from_binary_file(pkg_info), contract, path.name)
            )
    return errors


def _repository_errors(repository: Path) -> list[str]:
    errors: list[str] = []
    for markdown in repository.rglob("*.md"):
        if set(markdown.relative_to(repository).parts) & {"dist", ".git", ".venv"}:
            continue
        text = markdown.read_text(encoding="utf-8")
        if _SECRET_ASSIGNMENT.search(text) or _TOKEN_LITERAL.search(text):
            errors.append(f"repository: secret-like value in {markdown.relative_to(repository)}")
        for target in _LINK.findall(text):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (markdown.parent / target).resolve().exists():
                errors.append(
                    f"repository: broken link {target!r} in {markdown.relative_to(repository)}"
                )
    public_roots = [repository / name for name in ("src", "scripts")]
    public_files = [repository / name for name in ("README.md", "SECURITY.md", "pyproject.toml")]
    for root in public_roots:
        if root.exists():
            public_files.extend(path for path in root.rglob("*") if path.is_file())
    for path in public_files:
        if not path.is_file() or set(path.relative_to(repository).parts) & _FORBIDDEN_PARTS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _SECRET_ASSIGNMENT.search(text) or _TOKEN_LITERAL.search(text):
            errors.append(f"repository: secret-like value in {path.relative_to(repository)}")
    return errors


def verify_release(contract: ReleaseContract, artifacts: Sequence[Path]) -> list[str]:
    errors = _repository_errors(contract.repository)
    wheels = [path for path in artifacts if path.name.endswith(".whl")]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(artifacts) != 2:
        errors.append("artifacts: require exactly one wheel and one .tar.gz sdist")
        return errors
    try:
        errors.extend(_wheel_errors(wheels[0], contract))
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        errors.append(f"{wheels[0].name}: unreadable wheel ({type(exc).__name__})")
    try:
        errors.extend(_sdist_errors(sdists[0], contract))
    except (OSError, KeyError, tarfile.TarError) as exc:
        errors.append(f"{sdists[0].name}: unreadable sdist ({type(exc).__name__})")
    return errors


def verify_bootstrap(contract: ReleaseContract, wheel: Path, checksum: Path) -> list[str]:
    errors: list[str] = []
    bootstrap = contract.repository / "install.sh"
    if not bootstrap.is_file():
        return ["bootstrap: install.sh is missing"]
    if not bootstrap.stat().st_mode & stat.S_IXUSR:
        errors.append("bootstrap: install.sh must be executable")
    source = bootstrap.read_bytes()
    actual_source_sha256 = hashlib.sha256(source).hexdigest()
    if contract.bootstrap_source_sha256 is None or not hmac.compare_digest(
        actual_source_sha256, contract.bootstrap_source_sha256
    ):
        errors.append("bootstrap: source SHA-256 does not match the release contract")
    text = source.decode("utf-8")
    version_match = re.search(r"(?m)^VERSION=([^\n]+)$", text)
    release_url_match = re.search(r"(?m)^RELEASE_BASE_URL=([^\n]+)$", text)
    wheel_match = re.search(r"(?m)^WHEEL=([^\n]+)$", text)
    entry_points_match = re.search(r"(?m)^ENTRY_POINTS='([^'\n]+)'$", text)
    resources_match = re.search(r"(?m)^PACKAGED_RESOURCES='([^'\n]+)'$", text)
    modules_match = re.search(r"(?m)^REQUIRED_MODULES='([^'\n]+)'$", text)
    expected_wheel = f"{contract.package}-{contract.version}-py3-none-any.whl"
    expected_release_url = (
        f"https://github.com/KumaCool/AgentPorter/releases/download/v{contract.version}"
    )
    if version_match is None or version_match.group(1) != contract.version:
        errors.append("bootstrap: pinned version does not match release contract")
    if wheel_match is None or wheel_match.group(1) != expected_wheel:
        errors.append("bootstrap: pinned wheel does not match release contract")
    if release_url_match is None or release_url_match.group(1) != expected_release_url:
        errors.append("bootstrap: release URL does not match the exact GitHub release tag")
    expected_entries = set(contract.entry_points)
    actual_entries: set[str] = (
        set(entry_points_match.group(1).split()) if entry_points_match else set()
    )
    if actual_entries != expected_entries or "for entry in $ENTRY_POINTS; do" not in text:
        errors.append("bootstrap: entry-point rewrite does not match release contract")
    expected_resources = {f"{contract.package}/{resource}" for resource in contract.resources}
    actual_resources: set[str] = set(resources_match.group(1).split()) if resources_match else set()
    if (
        actual_resources != expected_resources
        or "for resource in $PACKAGED_RESOURCES; do" not in text
    ):
        errors.append("bootstrap: packaged-resource readback does not match release contract")
    expected_modules = {
        f"{contract.package}.{module.removesuffix('.py').replace('/', '.')}"
        for module in contract.required_modules
    } or {contract.package}
    actual_modules: set[str] = set(modules_match.group(1).split()) if modules_match else set()
    if actual_modules != expected_modules or "for module in $REQUIRED_MODULES; do" not in text:
        errors.append("bootstrap: required-module readback does not match release contract")
    version_tokens = (
        "import agentporter; print(agentporter.__version__)",
        '[ "$INSTALLED_VERSION" = "$VERSION" ]',
    )
    if any(token not in text for token in version_tokens):
        errors.append("bootstrap: installed-version readback semantics are incomplete")
    resource_tokens = (
        "target = files(package).joinpath(relative)",
        "not target.is_file() or not target.read_bytes()",
    )
    if any(token not in text for token in resource_tokens):
        errors.append("bootstrap: packaged-resource readback semantics are incomplete")
    if "importlib.import_module(sys.argv[1])" not in text:
        errors.append("bootstrap: required-module readback semantics are incomplete")
    expected_name = f"{wheel.name}.sha256"
    if checksum.name != expected_name:
        errors.append(f"bootstrap: checksum asset must be named {expected_name!r}")
        return errors
    try:
        fields = checksum.read_text(encoding="ascii").split()
    except (OSError, UnicodeDecodeError):
        return [*errors, "bootstrap: checksum asset is unreadable"]
    if (
        len(fields) != 2
        or fields[1] != wheel.name
        or re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]) is None
    ):
        errors.append("bootstrap: checksum asset must contain one SHA-256 and exact wheel name")
        return errors
    actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if fields[0].lower() != actual:
        errors.append("bootstrap: checksum does not match wheel bytes")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--package", default="agentporter")
    parser.add_argument("--version", required=True)
    parser.add_argument("--dependency", action="append", default=[])
    parser.add_argument("--entry-point", action="append", default=[])
    parser.add_argument("--resource", action="append", default=[])
    parser.add_argument("--required-module", action="append", default=[])
    parser.add_argument("--bootstrap-checksum", type=Path)
    parser.add_argument("--bootstrap-source-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        entries = dict(item.split("=", 1) for item in args.entry_point)
    except ValueError:
        print("FAIL: each --entry-point must be NAME=MODULE:CALLABLE")
        return 2
    if args.bootstrap_checksum is not None and (
        args.bootstrap_source_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", args.bootstrap_source_sha256) is None
    ):
        print("FAIL: --bootstrap-source-sha256 must be a lowercase SHA-256")
        return 2
    contract = ReleaseContract(
        repository=args.repository.resolve(),
        package=args.package,
        version=args.version,
        dependencies=frozenset(args.dependency),
        entry_points=entries,
        resources=frozenset(args.resource),
        required_modules=frozenset(args.required_module),
        bootstrap_source_sha256=args.bootstrap_source_sha256,
    )
    errors = verify_release(contract, args.artifacts)
    if args.bootstrap_checksum is not None:
        wheels = [path for path in args.artifacts if path.name.endswith(".whl")]
        if len(wheels) == 1:
            errors.extend(verify_bootstrap(contract, wheels[0], args.bootstrap_checksum))
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: release contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
