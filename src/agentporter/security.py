from __future__ import annotations

import ipaddress
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Final, Never, cast
from urllib.parse import urlsplit

import yaml
from pydantic import ValidationError

from .identity import COMPONENT_IDS, INITIAL_PROFILE_NAMES, PRODUCT_ID
from .models import MarkerV1
from .render import DISTRIBUTION_OWNED, DISTRIBUTION_VERSION

_ALLOWED_FILES: Final[set[str]] = {
    "distribution.yaml",
    "config.yaml",
    "SOUL.md",
    "agentporter-profile.json",
}
_SECRET_KEYS: Final = re.compile(
    r"(?i)^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|password|passwd|authorization|cookie)$"
)
_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)\bAuthorization\s*:\s*\S+"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|password|passwd|cookie)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)
_PRIVATE_PATH_PATTERNS: Final = (
    re.compile(r"/(?:home|Users)/[^/\s]+(?:/|(?=\s|$))"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+(?:\\|(?=\s|$))"),
    re.compile(r"/root(?:/|\b)"),
)
_URL_PATTERN: Final = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_ENDPOINT_KEYS: Final = {"endpoint", "base_url", "base-url"}
_OPEN_SUPPORTS_DIR_FD: Final = os.open in os.supports_dir_fd
_STAT_SUPPORTS_DIR_FD: Final = os.stat in os.supports_dir_fd
_LISTDIR_SUPPORTS_FD: Final = os.listdir in os.supports_fd


class StagingViolation(ValueError):
    pass


def _fail(category: str, relative_path: Path) -> Never:
    raise StagingViolation(f"{category}: {relative_path.as_posix()}")


def _url_is_private_or_credentialed(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        return True
    host = parsed.hostname
    if host is None:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    return (
        host == "localhost"
        or host.endswith((".local", ".internal", ".lan"))
        or (address is not None and not address.is_global)
    )


def _contains_private_endpoint(text: str, data: object) -> bool:
    for match in _URL_PATTERN.finditer(text):
        if _url_is_private_or_credentialed(match.group()):
            return True
    return _structured_pair_match(
        data,
        lambda key, value: (
            key.lower() in _ENDPOINT_KEYS and isinstance(value, str) and bool(value.strip())
        ),
    )


def _structured_match(data: object, predicate: Callable[[str], bool]) -> bool:
    if isinstance(data, dict):
        mapping = cast(dict[object, object], data)
        return any(
            (isinstance(key, str) and predicate(key)) or _structured_match(value, predicate)
            for key, value in mapping.items()
        )
    if isinstance(data, list):
        return any(_structured_match(item, predicate) for item in cast(list[object], data))
    return False


def _structured_pair_match(data: object, predicate: Callable[[str, object], bool]) -> bool:
    if isinstance(data, dict):
        mapping = cast(dict[object, object], data)
        return any(
            (isinstance(key, str) and predicate(key, value))
            or _structured_pair_match(value, predicate)
            for key, value in mapping.items()
        )
    if isinstance(data, list):
        return any(_structured_pair_match(item, predicate) for item in cast(list[object], data))
    return False


def _contains_secret(text: str, data: object) -> bool:
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return True
    if any(
        urlsplit(match.group()).username is not None or urlsplit(match.group()).password is not None
        for match in _URL_PATTERN.finditer(text)
    ):
        return True
    return _structured_match(data, lambda key: _SECRET_KEYS.fullmatch(key) is not None)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode) and (
        left.st_dev,
        left.st_ino,
    ) == (right.st_dev, right.st_ino)


def _open_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_verified_directory(path: Path, expected: os.stat_result) -> int | None:
    if not _LISTDIR_SUPPORTS_FD or not hasattr(os, "O_DIRECTORY"):
        if not _same_file(expected, path.lstat()):
            raise OSError("directory identity changed")
        return None
    descriptor = os.open(path, _open_flags() | getattr(os, "O_DIRECTORY", 0))
    actual = os.fstat(descriptor)
    if not stat.S_ISDIR(actual.st_mode) or not _same_file(expected, actual):
        os.close(descriptor)
        raise OSError("directory identity changed")
    return descriptor


def _list_verified_directory(
    path: Path, descriptor: int | None, expected: os.stat_result
) -> list[str]:
    names = os.listdir(descriptor if descriptor is not None else path)
    if descriptor is None:
        after = path.lstat()
        if not stat.S_ISDIR(after.st_mode) or not _same_file(expected, after):
            raise OSError("directory identity changed")
    return names


def _lstat_at(path: Path, parent_fd: int | None) -> os.stat_result:
    if parent_fd is not None and _STAT_SUPPORTS_DIR_FD:
        return os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    return path.lstat()


def _read_verified_file(path: Path, parent_fd: int | None) -> str:
    before = _lstat_at(path, parent_fd)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("artifact is not a regular file")
    kwargs: dict[str, int] = {}
    target: str | Path = path
    if parent_fd is not None and _OPEN_SUPPORTS_DIR_FD:
        kwargs["dir_fd"] = parent_fd
        target = path.name
    descriptor = os.open(target, _open_flags(), **kwargs)
    try:
        opened = os.fstat(descriptor)
        after = _lstat_at(path, parent_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_file(before, opened)
            or not _same_file(opened, after)
        ):
            raise OSError("artifact identity changed")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)


def _validate_distribution(data: object, profile_name: str) -> None:
    expected = {
        "name": profile_name,
        "version": DISTRIBUTION_VERSION,
        "description": str,
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
    try:
        root_before = staging_root.lstat()
        if not stat.S_ISDIR(root_before.st_mode):
            raise OSError("staging root is not a directory")
        root_fd = _open_verified_directory(staging_root, root_before)
    except OSError:
        _fail("unsafe-path", Path("."))
    try:
        profile_names = _list_verified_directory(staging_root, root_fd, root_before)
        for profile_name in profile_names:
            entry = staging_root / profile_name
            relative = Path(profile_name)
            try:
                profile_before = _lstat_at(entry, root_fd)
                if not stat.S_ISDIR(profile_before.st_mode):
                    category = (
                        "symlink" if stat.S_ISLNK(profile_before.st_mode) else "unexpected-path"
                    )
                    _fail(category, relative)
                if profile_name not in expected_profiles:
                    _fail("unexpected-path", relative)
                profile_fd = _open_verified_directory(entry, profile_before)
            except OSError:
                _fail("unsafe-path", relative)
            actual_profiles.add(profile_name)
            try:
                artifact_names = _list_verified_directory(entry, profile_fd, profile_before)
                if set(artifact_names) != _ALLOWED_FILES:
                    _fail("unexpected-path", relative)
                snapshots: dict[str, str] = {}
                parsed: dict[str, object] = {}
                for artifact_name in artifact_names:
                    artifact = entry / artifact_name
                    artifact_relative = relative / artifact_name
                    try:
                        if stat.S_ISLNK(_lstat_at(artifact, profile_fd).st_mode):
                            _fail("symlink", artifact_relative)
                        text = _read_verified_file(artifact, profile_fd)
                    except (OSError, UnicodeError) as error:
                        raise StagingViolation(
                            f"unsafe-path: {artifact_relative.as_posix()}"
                        ) from error
                    snapshots[artifact_name] = text
                    try:
                        data = yaml.safe_load(text)
                    except yaml.YAMLError:
                        data = None
                    parsed[artifact_name] = data
                    if _contains_secret(text, data):
                        _fail("secret", artifact_relative)
                    if _contains_private_endpoint(text, data):
                        _fail("private-endpoint", artifact_relative)
                    if any(pattern.search(text) for pattern in _PRIVATE_PATH_PATTERNS):
                        _fail("private-path", artifact_relative)
            finally:
                if profile_fd is not None:
                    os.close(profile_fd)
            try:
                _validate_distribution(parsed["distribution.yaml"], profile_name)
                _validate_config(parsed["config.yaml"])
                marker = MarkerV1.model_validate_json(snapshots["agentporter-profile.json"])
                portable_id = next(
                    key
                    for key, initial_name in INITIAL_PROFILE_NAMES.items()
                    if initial_name == profile_name
                )
                if (
                    marker.product_id != PRODUCT_ID
                    or marker.component_id != COMPONENT_IDS[portable_id]
                ):
                    raise ValueError("marker identity")
                installation_ids.add(marker.installation_id)
                if not snapshots["SOUL.md"].strip():
                    raise ValueError("empty SOUL")
            except (KeyError, ValidationError, ValueError):
                _fail("invalid-schema", relative)
    finally:
        if root_fd is not None:
            os.close(root_fd)
    if actual_profiles != expected_profiles:
        _fail("unexpected-path", Path("."))
    if len(installation_ids) != 1:
        _fail("invalid-schema", Path("."))
    return ()
