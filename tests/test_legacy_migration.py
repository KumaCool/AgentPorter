from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from agentporter.identity import INSTALL_COMPONENT_IDS, LEGACY_V020_COMPONENT_IDS, PRODUCT_ID
from agentporter.legacy_migration import (
    LegacyMigrationStatus,
    build_legacy_migration_plan,
    execute_legacy_migration,
    run_legacy_migration_confirmation,
)
from agentporter.uninstall_discovery import discover_installation
from agentporter.uninstall_planning import revalidate_uninstall_target

INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")
REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})


def _installation(tmp_path: Path) -> tuple[HermesDetection, tuple[Path, ...]]:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    home = tmp_path / "home"
    root = home / "profiles"
    root.mkdir(parents=True)
    paths = []
    for name, component in zip(
        ("renamed-bounded", "renamed-mechanical", "user-renamed-control"),
        LEGACY_V020_COMPONENT_IDS.values(),
        strict=True,
    ):
        profile = root / name
        profile.mkdir()
        (profile / "agentporter-profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "product_id": PRODUCT_ID,
                    "component_id": component,
                    "installation_id": str(INSTALLATION_ID),
                    "distribution_version": "0.2.0",
                }
            ),
            encoding="utf-8",
        )
        paths.append(profile)
    detection = HermesDetection(
        executable.resolve(),
        "0.20.0",
        home.resolve(),
        root.resolve(),
        HermesCapabilities(REQUIRED, frozenset()),
        tuple(ProfileEntry(path.name, path, ProfileEntryKind.PROFILE) for path in paths),
    )
    return detection, tuple(paths)


def test_plan_seals_only_marker_identified_legacy_orchestrator(tmp_path: Path) -> None:
    detection, paths = _installation(tmp_path)
    discovery = discover_installation(detection.profiles_root)

    plan = build_legacy_migration_plan(
        discovery,
        executable=detection.executable,
        journal_path=tmp_path / "state" / "migration.json",
    )

    assert plan.status is LegacyMigrationStatus.READY
    assert plan.target is not None
    assert plan.target.current_name == "user-renamed-control"
    assert plan.target.component_id == LEGACY_V020_COMPONENT_IDS["agentporter_orchestrator"]
    assert plan.retained_component_ids == tuple(INSTALL_COMPONENT_IDS.values())
    assert plan.confirmation_phrase == f"REMOVE LEGACY ORCHESTRATOR {str(INSTALLATION_ID)[:8]}"
    assert plan.target.path == paths[-1]


def test_exact_confirmation_deletes_only_orchestrator_and_observes_current_set(
    tmp_path: Path,
) -> None:
    detection, paths = _installation(tmp_path)
    plan = build_legacy_migration_plan(
        discover_installation(detection.profiles_root),
        executable=detection.executable,
        journal_path=tmp_path / "state" / "migration.json",
    )
    calls: list[tuple[str, ...]] = []

    class Executor:
        def run(self, argv: tuple[str, ...], *, env: dict[str, str]) -> CommandOutcome:
            calls.append(argv)
            paths[-1].rename(paths[-1].with_name("deleted-by-hermes"))
            # Model the native CLI's completed removal, not direct product deletion.
            import shutil

            shutil.rmtree(paths[-1].with_name("deleted-by-hermes"))
            return CommandOutcome(CommandStatus.FAILED, argv, 9)

    result = run_legacy_migration_confirmation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase or "",
        output=StringIO(),
        revalidate_collection=lambda _: True,
        continuation=lambda: execute_legacy_migration(
            plan,
            executor=Executor(),
            env={},
            per_target_revalidate=revalidate_uninstall_target,
            enumerate_profiles=lambda: tuple(
                ProfileEntry(path.name, path, ProfileEntryKind.PROFILE)
                for path in paths[:2]
                if path.exists()
            ),
        ),
    )

    assert result.status is LegacyMigrationStatus.MIGRATED
    assert calls == [
        (str(detection.executable), "profile", "delete", "user-renamed-control", "--yes")
    ]
    assert all(path.exists() for path in paths[:2])
    assert not paths[-1].exists()
    assert not plan.journal_path.exists()


def test_drift_after_confirmation_has_zero_delete_effect(tmp_path: Path) -> None:
    detection, paths = _installation(tmp_path)
    plan = build_legacy_migration_plan(
        discover_installation(detection.profiles_root),
        executable=detection.executable,
        journal_path=tmp_path / "state" / "migration.json",
    )
    calls = 0

    class Executor:
        def run(self, argv: tuple[str, ...], *, env: dict[str, str]) -> CommandOutcome:
            nonlocal calls
            calls += 1
            return CommandOutcome(CommandStatus.SUCCEEDED, argv, 0)

    result = run_legacy_migration_confirmation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase or "",
        output=StringIO(),
        revalidate_collection=lambda _: False,
        continuation=lambda: execute_legacy_migration(
            plan,
            executor=Executor(),
            env={},
            per_target_revalidate=revalidate_uninstall_target,
            enumerate_profiles=lambda: detection.profile_entries,
        ),
    )

    assert result.status is LegacyMigrationStatus.STALE
    assert calls == 0
    assert all(path.exists() for path in paths)
    assert not plan.journal_path.exists()


def test_interrupt_after_completed_native_attempt_closes_journal_and_reraises(
    tmp_path: Path,
) -> None:
    detection, paths = _installation(tmp_path)
    plan = build_legacy_migration_plan(
        discover_installation(detection.profiles_root),
        executable=detection.executable,
        journal_path=tmp_path / "state" / "migration.json",
    )
    interrupt = KeyboardInterrupt("stop")

    class Executor:
        def run(self, argv: tuple[str, ...], *, env: dict[str, str]) -> CommandOutcome:
            import shutil

            shutil.rmtree(paths[-1])
            raise interrupt

    with pytest.raises(KeyboardInterrupt) as raised:
        execute_legacy_migration(
            plan,
            executor=Executor(),
            env={},
            per_target_revalidate=revalidate_uninstall_target,
            enumerate_profiles=lambda: tuple(
                ProfileEntry(path.name, path, ProfileEntryKind.PROFILE)
                for path in paths[:2]
                if path.exists()
            ),
        )

    assert raised.value is interrupt
    assert raised.value.__notes__ == ["legacy migration post-attempt observation recorded"]
    assert not plan.journal_path.exists()
    assert all(path.exists() for path in paths[:2])


def test_interrupt_with_unresolved_effect_keeps_private_truthful_journal(tmp_path: Path) -> None:
    detection, paths = _installation(tmp_path)
    plan = build_legacy_migration_plan(
        discover_installation(detection.profiles_root),
        executable=detection.executable,
        journal_path=tmp_path / "state" / "migration.json",
    )
    interrupt = KeyboardInterrupt("stop")

    class Executor:
        def run(self, argv: tuple[str, ...], *, env: dict[str, str]) -> CommandOutcome:
            raise interrupt

    with pytest.raises(KeyboardInterrupt) as raised:
        execute_legacy_migration(
            plan,
            executor=Executor(),
            env={"AGENTPORTER_SECRET": "must-not-be-journaled"},
            per_target_revalidate=revalidate_uninstall_target,
            enumerate_profiles=lambda: detection.profile_entries,
        )

    assert raised.value is interrupt
    receipt_text = plan.journal_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert receipt["state"] == "effect-attempted"
    assert receipt["target_absent"] is False
    assert receipt["current_component_set_observed"] is False
    assert plan.journal_path.stat().st_mode & 0o777 == 0o600
    assert "must-not-be-journaled" not in receipt_text
    assert len(receipt_text) < 4096
    assert all(path.exists() for path in paths)
