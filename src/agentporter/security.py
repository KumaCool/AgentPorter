from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit

import yaml
from pydantic import ValidationError

from .identity import COMPONENT_IDS, INITIAL_PROFILE_NAMES, PRODUCT_ID
from .models import MarkerV1
from .render import DISTRIBUTION_OWNED, DISTRIBUTION_VERSION, MINIMUM_HERMES_VERSION

_ALLOWED_FILES: Final[set[str]] = {
    "distribution.yaml",
    "config.yaml",
    "SOUL.md",
    "agentporter-profile.json",
}
_SECRET_PATTERNS: Final = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|authorization|cookie)\b"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)
_PRIVATE_PATH_PATTERNS: Final = (
    re.compile(r"/(?:home|Users)/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
    re.compile(r"/root(?:/|\b)"),
)
_URL_PATTERN: Final = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


class StagingViolation(ValueError):
    pass


def _fail(category: str, relative_path: Path) -> None:
    raise StagingViolation(f"{category}: {relative_path.as_posix()}")


def _contains_private_endpoint(text: str) -> bool:
    lowered = text.lower()
    for match in _URL_PATTERN.finditer(text):
        host = urlsplit(match.group()).hostname
        if host is None:
            continue
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        private_host = (
            host == "localhost"
            or host.endswith((".local", ".internal", ".lan"))
            or (address is not None and not address.is_global)
        )
        if private_host or any(key in lowered for key in ("base_url", "base-url", "endpoint")):
            return True
    return False


def _validate_distribution(data: object, profile_name: str) -> None:
    expected = {
        "initial_profile_name": profile_name,
        "distribution_version": DISTRIBUTION_VERSION,
        "description": str,
        "minimum_hermes_version": MINIMUM_HERMES_VERSION,
        "license": "MIT",
        "distribution_owned": list(DISTRIBUTION_OWNED),
    }
    if not isinstance(data, dict):
        raise ValueError("distribution shape")
    distribution = cast(dict[object, object], data)
    if not all(isinstance(key, str) for key in distribution):
        raise ValueError("distribution shape")
    if set(distribution) != set(expected):
        raise ValueError("distribution shape")
    for key, expected_value in expected.items():
        actual = distribution[key]
        if expected_value is str:
            if not isinstance(actual, str) or not actual.strip():
                raise ValueError(key)
        elif actual != expected_value:
            raise ValueError(key)


def _validate_config(data: object) -> None:
    if not isinstance(data, dict):
        raise ValueError("config shape")
    config = cast(dict[object, object], data)
    if not all(isinstance(key, str) for key in config):
        raise ValueError("config shape")
    if set(config) != {"model", "agent"}:
        raise ValueError("config shape")
    model = config["model"]
    agent = config["agent"]
    if not isinstance(model, dict):
        raise ValueError("model shape")
    typed_model = cast(dict[object, object], model)
    if not all(isinstance(key, str) for key in typed_model):
        raise ValueError("model shape")
    if not {"default"} <= set(typed_model) <= {"default", "provider"}:
        raise ValueError("model shape")
    if not all(isinstance(value, str) and value.strip() for value in typed_model.values()):
        raise ValueError("model values")
    if not isinstance(agent, dict):
        raise ValueError("agent shape")
    typed_agent = cast(dict[object, object], agent)
    if not all(isinstance(key, str) for key in typed_agent):
        raise ValueError("agent shape")
    if set(typed_agent) != {"reasoning_effort"}:
        raise ValueError("agent shape")


def scan_staging(staging_root: Path) -> tuple[()]:
    expected_profiles = set(INITIAL_PROFILE_NAMES.values())
    actual_profiles: set[str] = set()
    installation_ids: set[str] = set()
    if staging_root.is_symlink() or not staging_root.is_dir():
        _fail("unsafe-path", Path("."))
    for entry in staging_root.iterdir():
        relative = entry.relative_to(staging_root)
        if entry.is_symlink():
            _fail("symlink", relative)
        if not entry.is_dir() or entry.name not in expected_profiles:
            _fail("unexpected-path", relative)
        actual_profiles.add(entry.name)
        actual_files: set[str] = set()
        for artifact in entry.iterdir():
            artifact_relative = artifact.relative_to(staging_root)
            if artifact.is_symlink():
                _fail("symlink", artifact_relative)
            if not artifact.is_file() or artifact.name not in _ALLOWED_FILES:
                _fail("unexpected-path", artifact_relative)
            actual_files.add(artifact.name)
            try:
                text = artifact.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise StagingViolation(f"unsafe-content: {artifact_relative.as_posix()}") from error
            if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
                _fail("secret", artifact_relative)
            if _contains_private_endpoint(text):
                _fail("private-endpoint", artifact_relative)
            if any(pattern.search(text) for pattern in _PRIVATE_PATH_PATTERNS):
                _fail("private-path", artifact_relative)
        if actual_files != _ALLOWED_FILES:
            _fail("unexpected-path", relative)
        try:
            _validate_distribution(
                yaml.safe_load((entry / "distribution.yaml").read_text(encoding="utf-8")),
                entry.name,
            )
            _validate_config(yaml.safe_load((entry / "config.yaml").read_text(encoding="utf-8")))
            marker = MarkerV1.model_validate_json(
                (entry / "agentporter-profile.json").read_text(encoding="utf-8")
            )
            portable_id = next(
                key
                for key, initial_name in INITIAL_PROFILE_NAMES.items()
                if initial_name == entry.name
            )
            if marker.product_id != PRODUCT_ID or marker.component_id != COMPONENT_IDS[portable_id]:
                raise ValueError("marker identity")
            installation_ids.add(marker.installation_id)
            if not (entry / "SOUL.md").read_text(encoding="utf-8").strip():
                raise ValueError("empty SOUL")
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError):
            _fail("invalid-schema", relative)
    if actual_profiles != expected_profiles:
        _fail("unexpected-path", Path("."))
    if len(installation_ids) != 1:
        _fail("invalid-schema", Path("."))
    return ()
