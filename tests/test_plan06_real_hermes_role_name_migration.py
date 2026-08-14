from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentporter.execution import CommandExecutor, CommandStatus
from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import PRODUCT_ID
from agentporter.native import NativeHermesAdapter
from agentporter.role_identity_compat import CANONICAL_COMPONENT_IDS
from agentporter.role_name_migration import (
    MigrationStatus,
    build_role_name_migration_plan,
    execute_role_name_migration,
)
from agentporter.uninstall_discovery import DiscoveryStatus, discover_installation

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"
OLD_NAMES = ("luna_worker", "codex-5-3-small-worker", "agentporter-orchestrator")
NEW_NAMES = (
    "agentporter-bounded-worker",
    "agentporter-mechanical-worker",
    "agentporter-orchestrator",
)


def test_isolated_real_hermes_native_role_rename_is_static_and_preserves_markers(
    tmp_path: Path,
) -> None:
    executable_value = shutil.which("hermes")
    if executable_value is None:
        pytest.skip("Hermes CLI is unavailable")
    executable = Path(executable_value).resolve()
    completed = subprocess.run(
        [str(executable), "profile", "rename", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        pytest.skip("installed Hermes has no native profile rename")

    home = (tmp_path / "isolated-hermes").resolve()
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    sentinel = "NO-PROVIDER-DEFINITION-READ-ALLOWED"
    marker_bytes: dict[str, bytes] = {}
    for name, component in zip(OLD_NAMES, CANONICAL_COMPONENT_IDS.values(), strict=True):
        profile = profiles / name
        profile.mkdir()
        marker = profile / "agentporter-profile.json"
        marker.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "product_id": PRODUCT_ID,
                    "component_id": component,
                    "installation_id": INSTALLATION_ID,
                    "distribution_version": "0.1.8",
                }
            ),
            encoding="utf-8",
        )
        marker_bytes[component] = marker.read_bytes()
        (profile / "config.yaml").write_text(sentinel, encoding="utf-8")
        (profile / "memory.bin").write_bytes(b"PROFILE-LOCAL-DATA")
    env = {"HOME": str(tmp_path / "user"), "HERMES_HOME": str(home), "PATH": os.environ["PATH"]}
    found = HermesDetection(
        executable,
        "0.20.0",
        home,
        profiles,
        HermesCapabilities(frozenset({"rename"}), frozenset()),
        (),
    )
    native = NativeHermesAdapter(CommandExecutor(timeout_seconds=20), env, found)
    journal = tmp_path / "agentporter-private" / "role-name-migration.json"
    plan = build_role_name_migration_plan(discover_installation(profiles), journal)
    result = execute_role_name_migration(
        plan,
        rename=native.rename,
        rediscover=lambda: discover_installation(profiles),
    )

    assert result.status is MigrationStatus.COMPLETE
    discovered = discover_installation(profiles)
    assert discovered.status is DiscoveryStatus.READY
    assert {target.current_name for target in discovered.targets} == set(NEW_NAMES)
    assert {target.installation_id for target in discovered.targets} == {INSTALLATION_ID}
    assert {target.component_id for target in discovered.targets} == set(
        CANONICAL_COMPONENT_IDS.values()
    )
    for target in discovered.targets:
        assert target.marker_path.read_bytes() == marker_bytes[target.component_id]
        assert (target.path / "config.yaml").read_text() == sentinel
        assert (target.path / "memory.bin").read_bytes() == b"PROFILE-LOCAL-DATA"
    assert all(native.info(name).status is CommandStatus.SUCCEEDED for name in NEW_NAMES)
