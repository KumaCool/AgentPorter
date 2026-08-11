from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import UUID

import pytest

from agentporter import security
from agentporter.manifest import load_manifest
from agentporter.render import render_staging
from agentporter.security import StagingViolation, scan_staging


def _valid_staging(tmp_path: Path) -> Path:
    manifest = load_manifest(Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml")
    render_staging(manifest, tmp_path, UUID("12345678-1234-4abc-8def-1234567890ab"))
    return tmp_path


def test_scan_accepts_explicitly_allowlisted_staging(tmp_path: Path) -> None:
    assert scan_staging(_valid_staging(tmp_path)) == ()


@pytest.mark.parametrize(
    "missing_capability",
    ["open-dir-fd", "stat-dir-fd", "listdir-fd", "directory-flag", "nofollow-flag"],
)
def test_scan_fails_closed_before_filesystem_access_without_descriptor_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_capability: str
) -> None:
    root = _valid_staging(tmp_path)
    if missing_capability == "open-dir-fd":
        monkeypatch.setattr(security, "_OPEN_SUPPORTS_DIR_FD", False)
    elif missing_capability == "stat-dir-fd":
        monkeypatch.setattr(security, "_STAT_SUPPORTS_DIR_FD", False)
    elif missing_capability == "listdir-fd":
        monkeypatch.setattr(security, "_LISTDIR_SUPPORTS_FD", False)
    elif missing_capability == "directory-flag":
        monkeypatch.delattr(os, "O_DIRECTORY")
    else:
        monkeypatch.delattr(os, "O_NOFOLLOW")

    def unexpected_access(*args: object, **kwargs: object) -> None:
        pytest.fail("staging filesystem was accessed without descriptor safety")

    monkeypatch.setattr(Path, "lstat", unexpected_access)
    monkeypatch.setattr(Path, "read_text", unexpected_access)
    monkeypatch.setattr(os, "listdir", unexpected_access)
    monkeypatch.setattr(os, "open", unexpected_access)
    monkeypatch.setattr(os, "read", unexpected_access)

    with pytest.raises(StagingViolation, match=r"^unsafe-path: \.$"):
        scan_staging(root)


def test_scan_fallback_does_not_consume_replaced_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _valid_staging(tmp_path)
    profile = root / "luna_worker"
    original = root.parent / "original-profile"
    replacement = root.parent / "replacement-profile"
    shutil.copytree(profile, replacement)
    (replacement / "SOUL.md").write_text("Replacement Worker SOUL\n")
    original_lstat = Path.lstat
    original_open = os.open
    profile_identity_checks = 0
    replaced = False
    replacement_consumed = False

    monkeypatch.setattr(security, "_OPEN_SUPPORTS_DIR_FD", False)
    monkeypatch.setattr(security, "_STAT_SUPPORTS_DIR_FD", False)
    monkeypatch.setattr(security, "_LISTDIR_SUPPORTS_FD", False)

    def replace_after_profile_identity_check(path: Path) -> os.stat_result:
        nonlocal profile_identity_checks, replaced
        result = original_lstat(path)
        if path == profile:
            profile_identity_checks += 1
            if profile_identity_checks == 3:
                replaced = True
                profile.rename(original)
                replacement.rename(profile)
        return result

    def observe_open(
        path: str | bytes | os.PathLike[str], flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal replacement_consumed
        if Path(path).parent == profile:
            replacement_consumed = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", replace_after_profile_identity_check)
    monkeypatch.setattr(os, "open", observe_open)

    with pytest.raises(StagingViolation, match=r"^unsafe-path: \.$"):
        scan_staging(root)
    assert not replaced
    assert not replacement_consumed


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


def test_scan_rejects_artifact_swapped_to_symlink_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _valid_staging(tmp_path)
    soul = root / "luna_worker" / "SOUL.md"
    original_open = os.open
    swapped = False

    def swap_before_open(
        path: str | bytes | os.PathLike[str], flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal swapped
        if path == "SOUL.md" and not swapped:
            swapped = True
            soul.unlink()
            soul.symlink_to(soul.with_name("config.yaml"))
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)

    with pytest.raises(StagingViolation, match="(?:symlink|unsafe-path)"):
        scan_staging(root)


def test_scan_rejects_artifact_inode_replacement_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _valid_staging(tmp_path)
    soul = root / "luna_worker" / "SOUL.md"
    profile = soul.parent
    replacement = root.parent / f"{root.name}-replacement"
    replacement.write_text("Replacement Worker SOUL\n")
    original_open = os.open
    swapped = False

    def swap_after_open(
        path: str | bytes | os.PathLike[str], flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal swapped
        descriptor = original_open(path, flags, *args, **kwargs)
        parent_descriptor = kwargs.get("dir_fd")
        if (
            path == "SOUL.md"
            and isinstance(parent_descriptor, int)
            and os.fstat(parent_descriptor).st_ino == profile.stat().st_ino
            and not swapped
        ):
            swapped = True
            os.replace(replacement, soul)
        return descriptor

    monkeypatch.setattr(os, "open", swap_after_open)

    with pytest.raises(StagingViolation, match="unsafe-path"):
        scan_staging(root)


def test_scan_rejects_profile_directory_replacement_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _valid_staging(tmp_path)
    profile = root / "luna_worker"
    moved = root.parent / f"{root.name}-moved-profile"
    replacement = root.parent / f"{root.name}-replacement-profile"
    replacement.mkdir()
    original_open = os.open
    swapped = False

    def swap_before_open(
        path: str | bytes | os.PathLike[str], flags: int, *args: object, **kwargs: object
    ) -> int:
        nonlocal swapped
        if Path(path) == profile and not swapped:
            swapped = True
            profile.rename(moved)
            replacement.rename(profile)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)

    with pytest.raises(StagingViolation, match="unsafe-path"):
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


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ("Connect to https://audit-user:audit-pass@example.com/v1\n", "secret"),
        ("Authorization: Bearer audit-token\n", "secret"),
        ("password = audit-pass\n", "secret"),
        ("Read /home/alice\n", "private-path"),
        ("Read C:\\Users\\Alice\n", "private-path"),
        ("endpoint: https://example.com/v1\n", "private-endpoint"),
        ("outer:\n  credentials:\n    token: audit-token\n", "secret"),
        ("outer:\n  service:\n    base_url: https://example.com/v1\n", "private-endpoint"),
    ],
)
def test_scan_rejects_precise_sensitive_families(
    tmp_path: Path, payload: str, category: str
) -> None:
    root = _valid_staging(tmp_path)
    (root / "luna_worker" / "SOUL.md").write_text(payload)

    with pytest.raises(StagingViolation, match=category):
        scan_staging(root)


@pytest.mark.parametrize(
    "payload",
    [
        "The endpoint policy is documented at https://example.com/docs\n",
        "This Worker explains password hygiene without embedding a credential.\n",
        "Use the token budget and cookie policy documented for this Worker.\n",
        "The public API is https://example.com/v1\n",
        "The example home directory is /home/ without a private user segment.\n",
    ],
)
def test_scan_allows_benign_security_vocabulary(tmp_path: Path, payload: str) -> None:
    root = _valid_staging(tmp_path)
    (root / "luna_worker" / "SOUL.md").write_text(payload)

    assert scan_staging(root) == ()


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
