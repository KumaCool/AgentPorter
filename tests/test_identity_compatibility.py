from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentporter.identity import COMPONENT_IDS, ORCHESTRATOR_COMPONENT_ID, PRODUCT_ID
from agentporter.role_identity_compat import (
    CANONICAL_COMPONENT_IDS,
    CURRENT_INITIAL_NAMES,
    LEGACY_PORTABLE_ALIASES,
    RoleIdentityError,
    canonical_portable_id,
    project_discovery_roles,
)
from agentporter.uninstall_discovery import DiscoveryStatus, discover_installation

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"


def _profile(
    root: Path, name: str, component_id: str, installation_id: str = INSTALLATION_ID
) -> None:
    path = root / name
    path.mkdir(parents=True)
    (path / "agentporter-profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_id": PRODUCT_ID,
                "component_id": component_id,
                "installation_id": installation_id,
                "distribution_version": "0.1.8",
            }
        ),
        encoding="utf-8",
    )


def test_role_registry_projects_legacy_ids_to_role_ids_without_changing_uuids() -> None:
    legacy = tuple(COMPONENT_IDS.values())
    assert {
        "bounded_worker": legacy[0],
        "mechanical_worker": legacy[1],
        "agentporter_orchestrator": ORCHESTRATOR_COMPONENT_ID,
    } == CANONICAL_COMPONENT_IDS
    assert LEGACY_PORTABLE_ALIASES == {
        "luna_worker": "bounded_worker",
        "codex_5_3_small_worker": "mechanical_worker",
    }
    assert canonical_portable_id("luna_worker", for_write=False) == "bounded_worker"
    assert canonical_portable_id("bounded_worker", for_write=True) == "bounded_worker"
    with pytest.raises(RoleIdentityError, match="legacy"):
        canonical_portable_id("luna_worker", for_write=True)


def test_marker_uuid_projects_old_new_and_user_names_to_same_roles(tmp_path: Path) -> None:
    roots = []
    name_sets = (
        ("luna_worker", "codex-5-3-small-worker", "agentporter-orchestrator"),
        tuple(CURRENT_INITIAL_NAMES.values()),
        ("team-analysis", "team-mechanical", "team-control"),
    )
    for index, names in enumerate(name_sets):
        root = tmp_path / f"set-{index}" / "profiles"
        for name, component in zip(names, CANONICAL_COMPONENT_IDS.values(), strict=True):
            _profile(root, name, component)
        roots.append(root)

    projections = []
    for root in roots:
        discovered = discover_installation(root.resolve())
        assert discovered.status is DiscoveryStatus.READY
        projections.append({item.portable_id for item in project_discovery_roles(discovered)})
    assert projections == [set(CANONICAL_COMPONENT_IDS)] * 3


def test_projection_fails_closed_for_incomplete_duplicate_mixed_or_unknown(tmp_path: Path) -> None:
    root = (tmp_path / "profiles").resolve()
    _profile(root, "one", tuple(CANONICAL_COMPONENT_IDS.values())[0])
    incomplete = discover_installation(root)
    assert incomplete.status is DiscoveryStatus.AMBIGUOUS
    with pytest.raises(RoleIdentityError, match="complete"):
        project_discovery_roles(incomplete)


def test_new_projection_contains_no_legacy_portable_ids(tmp_path: Path) -> None:
    root = (tmp_path / "profiles").resolve()
    for name, component in zip(
        ("luna_worker", "codex-5-3-small-worker", "agentporter-orchestrator"),
        CANONICAL_COMPONENT_IDS.values(),
        strict=True,
    ):
        _profile(root, name, component)
    projected = project_discovery_roles(discover_installation(root))
    portable_ids = tuple(item.portable_id for item in projected)
    assert all(item in CANONICAL_COMPONENT_IDS for item in portable_ids)
    assert not any(alias in portable_ids for alias in LEGACY_PORTABLE_ALIASES)
