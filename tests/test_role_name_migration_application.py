from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from agentporter.execution import CommandExecutor
from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import PRODUCT_ID
from agentporter.role_identity_compat import CANONICAL_COMPONENT_IDS
from agentporter.role_name_migration import MigrationStatus
from agentporter.role_name_migration_application import (
    RoleMigrationApplicationStatus,
    run_role_name_migration_gate,
)

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"
OLD_NAMES = ("luna_worker", "codex-5-3-small-worker", "agentporter-orchestrator")
NEW_NAMES = (
    "agentporter-bounded-worker",
    "agentporter-mechanical-worker",
    "agentporter-orchestrator",
)


def _detection(tmp_path: Path) -> HermesDetection:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    home = (tmp_path / "hermes").resolve()
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    return HermesDetection(
        executable.resolve(),
        "0.20.0",
        home,
        profiles,
        HermesCapabilities(frozenset({"rename"}), frozenset()),
        (),
    )


def _install(found: HermesDetection, names: tuple[str, ...]) -> None:
    for name, component in zip(names, CANONICAL_COMPONENT_IDS.values(), strict=True):
        profile = found.profiles_root / name
        profile.mkdir()
        (profile / "agentporter-profile.json").write_text(
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


class NativeRenameRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[Sequence[str], Mapping[str, object]]] = []

    def __call__(self, argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        assert tuple(argv[1:3]) == ("profile", "rename")
        (self.root / argv[3]).rename(self.root / argv[4])
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_activate_gate_rejects_legacy_migration_and_stops_binding_and_canary(
    tmp_path: Path,
) -> None:
    found = _detection(tmp_path)
    _install(found, OLD_NAMES)
    runner = NativeRenameRunner(found.profiles_root)
    downstream: list[str] = []
    result = run_role_name_migration_gate(
        {},
        detector=lambda **_kwargs: found,
        executor_factory=lambda: CommandExecutor(runner=runner),
        journal_path=tmp_path / "private" / "role-name-migration.json",
        input_fn=lambda _prompt: "no",
        binding_continuation=lambda: downstream.append("binding"),
    )
    assert result.status is RoleMigrationApplicationStatus.LEGACY_NAME_MIGRATION_REQUIRED
    assert result.migration.status is MigrationStatus.MIGRATION_REQUIRED
    assert runner.calls == []
    assert downstream == []


def test_activate_gate_current_or_user_named_set_reaches_separate_binding_gate(
    tmp_path: Path,
) -> None:
    for index, names in enumerate((NEW_NAMES, ("custom-a", "custom-b", "custom-control"))):
        found = _detection(tmp_path / str(index))
        _install(found, names)
        reached: list[str] = []

        def detect_current(found: HermesDetection = found, **_kwargs: object) -> HermesDetection:
            return found

        def reach_binding(reached: list[str] = reached) -> None:
            reached.append("binding")

        result = run_role_name_migration_gate(
            {},
            detector=detect_current,
            journal_path=tmp_path / str(index) / "private" / "role-name-migration.json",
            input_fn=lambda _prompt: "unused",
            binding_continuation=reach_binding,
        )
        assert result.status is RoleMigrationApplicationStatus.BINDING_GATE_REACHED
        assert reached == ["binding"]


def test_activate_gate_confirmed_legacy_uses_native_rename_then_reaches_binding(
    tmp_path: Path,
) -> None:
    found = _detection(tmp_path)
    _install(found, OLD_NAMES)
    runner = NativeRenameRunner(found.profiles_root)
    reached: list[str] = []
    result = run_role_name_migration_gate(
        {"HERMES_HOME": str(found.hermes_home)},
        detector=lambda **_kwargs: found,
        executor_factory=lambda: CommandExecutor(runner=runner),
        journal_path=tmp_path / "private" / "role-name-migration.json",
        input_fn=lambda _prompt: "yes",
        binding_continuation=lambda: reached.append("binding"),
    )
    assert result.status is RoleMigrationApplicationStatus.BINDING_GATE_REACHED
    assert [tuple(call[0][1:]) for call in runner.calls] == [
        ("profile", "rename", OLD_NAMES[0], NEW_NAMES[0]),
        ("profile", "rename", OLD_NAMES[1], NEW_NAMES[1]),
    ]
    assert reached == ["binding"]


def test_software_update_hook_never_renames_and_manual_activate_is_reachable(
    tmp_path: Path,
) -> None:
    from agentporter.role_name_migration_application import activation_after_software_update

    found = _detection(tmp_path)
    _install(found, OLD_NAMES)
    runner = NativeRenameRunner(found.profiles_root)
    statuses = activation_after_software_update(
        {},
        detector=lambda **_kwargs: found,
        executor_factory=lambda: CommandExecutor(runner=runner),
        journal_path=tmp_path / "private" / "role-name-migration.json",
        input_fn=lambda _prompt: "no",
        binding_continuation=lambda: None,
    )
    assert statuses.status is RoleMigrationApplicationStatus.LEGACY_NAME_MIGRATION_REQUIRED
    assert runner.calls == []
