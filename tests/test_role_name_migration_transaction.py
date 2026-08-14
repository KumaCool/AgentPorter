from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.identity import PRODUCT_ID
from agentporter.role_identity_compat import CANONICAL_COMPONENT_IDS
from agentporter.role_name_migration import (
    MigrationAction,
    MigrationStatus,
    build_role_name_migration_plan,
    execute_role_name_migration,
)
from agentporter.uninstall_discovery import discover_installation

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"
OLD_NAMES = ("luna_worker", "codex-5-3-small-worker", "agentporter-orchestrator")
NEW_NAMES = (
    "agentporter-bounded-worker",
    "agentporter-mechanical-worker",
    "agentporter-orchestrator",
)


def _set(root: Path, names: tuple[str, ...] = OLD_NAMES) -> None:
    for name, component in zip(names, CANONICAL_COMPONENT_IDS.values(), strict=True):
        profile = root / name
        profile.mkdir(parents=True)
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
        (profile / "config.yaml").write_text("PRIVATE-PROVIDER-SENTINEL\n", encoding="utf-8")
        (profile / "memory.db").write_bytes(b"PROFILE-LOCAL-SENTINEL")


class FilesystemRenamer:
    def __init__(self, root: Path, fail_at: int | None = None) -> None:
        self.root = root
        self.fail_at = fail_at
        self.calls: list[tuple[str, str]] = []

    def __call__(self, current: str, target: str) -> CommandOutcome:
        self.calls.append((current, target))
        if self.fail_at == len(self.calls):
            return CommandOutcome(CommandStatus.FAILED, ("hermes",), 9, "", "")
        (self.root / current).rename(self.root / target)
        return CommandOutcome(CommandStatus.SUCCEEDED, ("hermes",), 0, "", "")


def test_collection_rename_writes_private_journal_before_first_command_and_preserves_data(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root)
    journal = tmp_path / "agentporter-private" / "role-name-migration.json"
    renamer = FilesystemRenamer(root)
    observed: list[bool] = []

    def rename(current: str, target: str) -> CommandOutcome:
        observed.append(journal.exists())
        return renamer(current, target)

    plan = build_role_name_migration_plan(discover_installation(root), journal)
    result = execute_role_name_migration(
        plan,
        rename=rename,
        rediscover=lambda: discover_installation(root),
    )

    assert result.status is MigrationStatus.COMPLETE
    assert observed == [True, True]
    assert renamer.calls == list(zip(OLD_NAMES[:2], NEW_NAMES[:2], strict=True))
    assert not journal.exists()
    receipt = journal.with_name("role-name-migration-receipt.json")
    payload = receipt.read_text(encoding="utf-8")
    assert "PRIVATE-PROVIDER-SENTINEL" not in payload
    assert "PROFILE-LOCAL-SENTINEL" not in payload
    for name in NEW_NAMES:
        assert (root / name / "config.yaml").read_text() == "PRIVATE-PROVIDER-SENTINEL\n"
        assert (root / name / "memory.db").read_bytes() == b"PROFILE-LOCAL-SENTINEL"


def test_second_failure_compensates_only_first_when_still_bound(tmp_path: Path) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root)
    journal = tmp_path / "private" / "role-name-migration.json"
    renamer = FilesystemRenamer(root, fail_at=2)
    result = execute_role_name_migration(
        build_role_name_migration_plan(discover_installation(root), journal),
        rename=renamer,
        rediscover=lambda: discover_installation(root),
    )
    assert result.status is MigrationStatus.COMPENSATED
    assert renamer.calls == [
        (OLD_NAMES[0], NEW_NAMES[0]),
        (OLD_NAMES[1], NEW_NAMES[1]),
        (NEW_NAMES[0], OLD_NAMES[0]),
    ]
    assert all((root / name).is_dir() for name in OLD_NAMES)
    assert not journal.exists()


@pytest.mark.parametrize(
    ("failure_status", "returncode"),
    [
        (CommandStatus.FAILED, 9),
        (CommandStatus.TIMED_OUT, None),
        (CommandStatus.INTERRUPTED, None),
    ],
)
def test_unsuccessful_cli_after_rename_effect_is_discovered_journaled_and_compensated(
    tmp_path: Path, failure_status: CommandStatus, returncode: int | None
) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root)
    journal = tmp_path / "private" / "role-name-migration.json"
    calls: list[tuple[str, str]] = []

    def rename_then_report_failure(current: str, target: str) -> CommandOutcome:
        calls.append((current, target))
        (root / current).rename(root / target)
        status = failure_status if len(calls) == 1 else CommandStatus.SUCCEEDED
        return CommandOutcome(status, ("hermes",), returncode if len(calls) == 1 else 0, "", "")

    result = execute_role_name_migration(
        build_role_name_migration_plan(discover_installation(root), journal),
        rename=rename_then_report_failure,
        rediscover=lambda: discover_installation(root),
    )

    assert result.status is MigrationStatus.COMPENSATED
    assert calls == [(OLD_NAMES[0], NEW_NAMES[0]), (NEW_NAMES[0], OLD_NAMES[0])]
    assert all((root / name).is_dir() for name in OLD_NAMES)
    assert not journal.exists()


def test_concurrent_rename_blocks_compensation_and_leaves_recoverable_journal(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root)
    journal = tmp_path / "private" / "role-name-migration.json"
    renamer = FilesystemRenamer(root, fail_at=2)

    def rediscover():
        result = discover_installation(root)
        if len(renamer.calls) == 2 and (root / NEW_NAMES[0]).exists():
            (root / NEW_NAMES[0]).rename(root / "operator-renamed")
            result = discover_installation(root)
        return result

    outcome = execute_role_name_migration(
        build_role_name_migration_plan(discover_installation(root), journal),
        rename=renamer,
        rediscover=rediscover,
    )
    assert outcome.status is MigrationStatus.COMPENSATION_INCOMPLETE
    assert outcome.residue == ("bounded_worker",)
    assert journal.exists()
    assert renamer.calls == list(zip(OLD_NAMES[:2], NEW_NAMES[:2], strict=True))


def test_valid_crash_journal_allows_continue_or_rollback(tmp_path: Path) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root)
    journal = tmp_path / "private" / "role-name-migration.json"
    first = FilesystemRenamer(root, fail_at=2)
    execute_role_name_migration(
        build_role_name_migration_plan(discover_installation(root), journal),
        rename=first,
        rediscover=lambda: discover_installation(root),
        compensate_on_failure=False,
    )
    recovery = build_role_name_migration_plan(discover_installation(root), journal)
    assert recovery.status is MigrationStatus.RECOVERY_REQUIRED
    continued = execute_role_name_migration(
        recovery,
        action=MigrationAction.CONTINUE,
        rename=FilesystemRenamer(root),
        rediscover=lambda: discover_installation(root),
    )
    assert continued.status is MigrationStatus.COMPLETE
    assert all((root / name).is_dir() for name in NEW_NAMES)


def test_mixed_without_valid_journal_is_ambiguous_and_zero_rename(tmp_path: Path) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root, (NEW_NAMES[0], OLD_NAMES[1], OLD_NAMES[2]))
    journal = tmp_path / "private" / "role-name-migration.json"
    plan = build_role_name_migration_plan(discover_installation(root), journal)
    renamer = FilesystemRenamer(root)
    result = execute_role_name_migration(
        plan, rename=renamer, rediscover=lambda: discover_installation(root)
    )
    assert plan.status is MigrationStatus.AMBIGUOUS
    assert result.status is MigrationStatus.AMBIGUOUS
    assert renamer.calls == []


def test_target_conflict_and_user_custom_names_fail_or_preserve_before_confirmation(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "hermes" / "profiles").resolve()
    _set(root, (OLD_NAMES[0], "operator-mechanical", OLD_NAMES[2]))
    (root / NEW_NAMES[0]).mkdir()
    journal = tmp_path / "private" / "role-name-migration.json"
    conflict = build_role_name_migration_plan(discover_installation(root), journal)
    assert conflict.status is MigrationStatus.CONFLICT
    (root / NEW_NAMES[0]).rmdir()
    ready = build_role_name_migration_plan(discover_installation(root), journal)
    assert ready.status is MigrationStatus.MIGRATION_REQUIRED
    assert [item.current_name for item in ready.items] == [OLD_NAMES[0]]
