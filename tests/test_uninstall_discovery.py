from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentporter import uninstall_discovery
from agentporter.identity import COMPONENT_IDS, INSTALL_COMPONENT_IDS, PRODUCT_ID
from agentporter.uninstall_discovery import DiscoveryStatus, FindingCode, discover_installation

INSTALLATION_A = "12345678-1234-4abc-8def-1234567890ab"
INSTALLATION_B = "87654321-4321-4abc-8def-ba0987654321"
MARKER = "agentporter-profile.json"


def _marker(
    root: Path,
    name: str,
    component_id: str,
    *,
    installation_id: str = INSTALLATION_A,
    product_id: str = PRODUCT_ID,
    schema_version: int = 1,
) -> Path:
    profile = root / name
    profile.mkdir(parents=True, exist_ok=True)
    marker = profile / MARKER
    marker.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "product_id": product_id,
                "component_id": component_id,
                "installation_id": installation_id,
                "distribution_version": "0.1.0",
            }
        )
    )
    return marker


def _complete(root: Path, *, installation_id: str = INSTALLATION_A, legacy: bool = False) -> None:
    components = tuple(COMPONENT_IDS.values()) if legacy else tuple(INSTALL_COMPONENT_IDS.values())
    names = (
        ("renamed-one", "totally-different")
        if legacy
        else (
            "renamed-one",
            "totally-different",
            "control-plane",
        )
    )
    for name, component in zip(names, components, strict=True):
        _marker(root, name, component, installation_id=installation_id)


def _codes(result: object) -> list[FindingCode]:
    return [finding.code for finding in result.findings]  # type: ignore[attr-defined]


def test_absent_profiles_root_is_already_absent(tmp_path: Path) -> None:
    result = discover_installation(tmp_path / "profiles")

    assert result.status is DiscoveryStatus.ALREADY_ABSENT
    assert result.targets == ()
    assert result.findings == ()


def test_batch_renamed_complete_set_is_ready_with_identity_snapshots(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _complete(root)

    result = discover_installation(root)

    assert result.status is DiscoveryStatus.READY
    assert [target.current_name for target in result.targets] == [
        "control-plane",
        "renamed-one",
        "totally-different",
    ]
    assert {target.marker.component_id for target in result.targets} == set(
        INSTALL_COMPONENT_IDS.values()
    )
    assert all(target.profile_identity.inode > 0 for target in result.targets)
    assert all(
        target.marker_identity.inode > 0 and len(target.marker_hash) == 64
        for target in result.targets
    )
    assert result.findings == ()


def test_legacy_two_component_installation_remains_a_complete_uninstall_set(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _complete(root, legacy=True)

    result = discover_installation(root)

    assert result.status is DiscoveryStatus.READY
    assert len(result.targets) == 2
    assert {target.component_id for target in result.targets} == set(COMPONENT_IDS.values())


def test_valid_unrelated_marker_and_profiles_without_markers_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _complete(root)
    _marker(
        root,
        "unrelated",
        next(iter(COMPONENT_IDS.values())),
        product_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    (root / "ordinary-profile").mkdir()

    assert discover_installation(root).status is DiscoveryStatus.READY


def test_only_valid_unrelated_marker_is_already_absent(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _marker(
        root,
        "unrelated",
        next(iter(COMPONENT_IDS.values())),
        product_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    result = discover_installation(root)

    assert result.status is DiscoveryStatus.ALREADY_ABSENT
    assert result.findings == ()


@pytest.mark.parametrize("payload", [b"{", b"\xff", b"{}"])
def test_corrupt_candidate_blocks_even_without_readable_product_id(
    tmp_path: Path, payload: bytes
) -> None:
    root = tmp_path / "profiles"
    _complete(root)
    marker = root / "corrupt" / MARKER
    marker.parent.mkdir()
    marker.write_bytes(payload)

    result = discover_installation(root)

    assert result.status is DiscoveryStatus.AMBIGUOUS
    assert FindingCode.INVALID_MARKER in _codes(result)
    assert result.targets == ()


def test_oversize_and_nonfile_candidates_are_invalid(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    (root / "big").mkdir(parents=True)
    (root / "big" / MARKER).write_bytes(b" " * (uninstall_discovery.MAX_MARKER_BYTES + 1))
    (root / "directory" / MARKER).mkdir(parents=True)

    result = discover_installation(root)

    assert _codes(result).count(FindingCode.INVALID_MARKER) == 2


def test_symlink_profile_or_marker_is_unsafe(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    outside = tmp_path / "outside"
    _marker(outside, "real", next(iter(COMPONENT_IDS.values())))
    root.mkdir()
    (root / "linked-profile").symlink_to(outside / "real", target_is_directory=True)
    profile = root / "linked-marker"
    profile.mkdir()
    (profile / MARKER).symlink_to(outside / "real" / MARKER)

    result = discover_installation(root)

    assert _codes(result).count(FindingCode.UNSAFE_PATH) == 2
    assert result.primary_finding.code is FindingCode.UNSAFE_PATH


@pytest.mark.parametrize("root_kind", ["symlink", "file"])
def test_noncanonical_or_nondirectory_root_is_unsafe(tmp_path: Path, root_kind: str) -> None:
    root = tmp_path / "profiles"
    if root_kind == "symlink":
        target = tmp_path / "actual"
        target.mkdir()
        root.symlink_to(target, target_is_directory=True)
    else:
        root.write_text("not a directory")

    result = discover_installation(root)

    assert result.status is DiscoveryStatus.AMBIGUOUS
    assert result.primary_finding.code is FindingCode.UNSAFE_PATH


def test_unknown_component_and_unsupported_schema_are_distinct_protocol_findings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    _marker(root, "unknown", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    _marker(root, "schema", next(iter(COMPONENT_IDS.values())), schema_version=2)

    result = discover_installation(root)

    assert _codes(result).count(FindingCode.UNKNOWN_COMPONENT) == 1
    assert _codes(result).count(FindingCode.INVALID_MARKER) == 1
    assert result.primary_finding is not None
    assert result.primary_finding.code is FindingCode.INVALID_MARKER


def test_duplicate_component_is_ambiguous(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    component = next(iter(COMPONENT_IDS.values()))
    _marker(root, "one", component)
    _marker(root, "two", component)

    result = discover_installation(root)

    assert FindingCode.DUPLICATE_COMPONENT in _codes(result)
    assert FindingCode.INCOMPLETE in _codes(result)


def test_two_complete_installations_report_multiple_installations(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _complete(root)
    for index, component in enumerate(COMPONENT_IDS.values()):
        _marker(root, f"other-{index}", component, installation_id=INSTALLATION_B)

    result = discover_installation(root)

    assert FindingCode.MULTIPLE_INSTALLATIONS in _codes(result)


def test_components_split_across_installations_report_conflict_and_incomplete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    components = tuple(COMPONENT_IDS.values())
    _marker(root, "one", components[0], installation_id=INSTALLATION_A)
    _marker(root, "two", components[1], installation_id=INSTALLATION_B)

    result = discover_installation(root)

    assert FindingCode.INSTALLATION_CONFLICT in _codes(result)
    assert _codes(result).count(FindingCode.INCOMPLETE) == 2


def test_zero_candidates_with_extra_profiles_is_already_absent(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    (root / "default").mkdir(parents=True)
    (root / "other").mkdir()

    assert discover_installation(root).status is DiscoveryStatus.ALREADY_ABSENT


def test_missing_descriptor_capability_fails_closed_before_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    monkeypatch.setattr(uninstall_discovery, "_descriptor_scan_supported", lambda: False)
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("accessed filesystem"))

    result = discover_installation(root)

    assert result.primary_finding.code is FindingCode.UNSAFE_PATH


def test_profile_replacement_race_is_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "profiles"
    marker = _marker(root, "race", next(iter(COMPONENT_IDS.values())))
    profile = marker.parent
    moved = tmp_path / "moved"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    original_open_directory = uninstall_discovery._open_directory
    replaced = False

    def replace_before_profile_open(name: str | Path, *, parent_fd: int | None = None) -> int:
        nonlocal replaced
        if name == "race" and parent_fd is not None and not replaced:
            replaced = True
            profile.rename(moved)
            replacement.rename(profile)
        return original_open_directory(name, parent_fd=parent_fd)

    monkeypatch.setattr(uninstall_discovery, "_open_directory", replace_before_profile_open)

    result = discover_installation(root)

    assert replaced
    assert result.primary_finding.code is FindingCode.UNSAFE_PATH


def test_marker_replacement_race_is_unsafe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "profiles"
    marker = _marker(root, "race", next(iter(COMPONENT_IDS.values())))
    replacement = tmp_path / "replacement-marker"
    replacement.write_text(marker.read_text())
    original_read_marker = uninstall_discovery._read_marker
    replaced = False

    def replace_after_marker_open(
        profile_fd: int, marker_before: os.stat_result
    ) -> tuple[bytes, os.stat_result]:
        nonlocal replaced
        payload = original_read_marker(profile_fd, marker_before)
        if not replaced:
            replaced = True
            os.replace(replacement, marker)
        return payload

    monkeypatch.setattr(uninstall_discovery, "_read_marker", replace_after_marker_open)

    result = discover_installation(root)

    assert replaced
    assert result.primary_finding.code is FindingCode.UNSAFE_PATH


def test_repeated_discovery_closes_all_descriptors(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _complete(root)
    descriptor_dir = Path("/proc/self/fd")
    if not descriptor_dir.exists():
        pytest.skip("descriptor counter unavailable")
    before = len(tuple(descriptor_dir.iterdir()))

    for _ in range(50):
        assert discover_installation(root).status is DiscoveryStatus.READY

    assert len(tuple(descriptor_dir.iterdir())) == before
