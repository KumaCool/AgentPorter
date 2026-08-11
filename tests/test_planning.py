from __future__ import annotations

import json
import os
import shutil
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from typing import Never
from uuid import UUID

import pytest
import yaml

from agentporter.hermes import (
    DetectionError,
    HermesCapabilities,
    HermesDetection,
    ProfileEntry,
    ProfileEntryKind,
)
from agentporter.planning import (
    CleanupOutcome,
    InstallPlan,
    cleanup_staging,
    confirm_install_plan,
    plan_installation,
    preflight_installation,
    revalidate_install_plan,
)

INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")
REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})


def _manifest(tmp_path: Path, *, providers: bool = True) -> Path:
    source = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if providers:
        for worker in data["workers"].values():
            worker["provider"] = "static-public-provider"
    path = tmp_path / "workers.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _detection(tmp_path: Path, *entries: ProfileEntry) -> HermesDetection:
    home = tmp_path / "actual-hermes-home"
    return HermesDetection(
        executable=tmp_path / "bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=tuple(entries),
    )


def test_plan_aggregates_authoritative_order_shared_id_and_scanned_staging(tmp_path: Path) -> None:
    detection = _detection(tmp_path)
    plan = plan_installation(
        detection,
        _manifest(tmp_path),
        staging_parent=tmp_path / "temporary-staging",
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert isinstance(plan, InstallPlan)
    assert plan.status == "ready"
    assert plan.installation_id == str(INSTALLATION_ID)
    assert [worker.portable_id for worker in plan.workers] == [
        "luna_worker",
        "codex_5_3_small_worker",
    ]
    assert [worker.profile_name for worker in plan.workers] == [
        "luna_worker",
        "codex-5-3-small-worker",
    ]
    assert {worker.component_id for worker in plan.workers} == {
        "5c7f978c-a9a6-4cec-98fa-e65bbf8101cd",
        "7dab98fb-9ac0-44fa-90fb-4a4f30e1470c",
    }
    assert all(worker.status == "ready" for worker in plan.workers)
    assert all(worker.provider == "static-public-provider" for worker in plan.workers)
    assert plan.staging_dir is not None and plan.staging_dir.is_dir()
    assert {path.name for path in plan.staging_dir.iterdir()} == {
        "luna_worker",
        "codex-5-3-small-worker",
    }
    assert plan.hermes.executable == detection.executable
    assert plan.hermes.version == detection.version
    assert plan.hermes.home == detection.hermes_home
    assert plan.hermes.profiles_root == detection.profiles_root
    assert plan.distribution_owned == (
        "SOUL.md",
        "config.yaml",
        "agentporter-profile.json",
    )
    assert plan.copied_data == ()
    assert plan.modified_data == ()
    assert plan.model_calls is False
    assert plan.runtime_validated is False
    assert plan.compensation_boundary == "no-install-attempted"
    with pytest.raises(FrozenInstanceError):
        plan.status = "invalid"  # type: ignore[misc]
    assert cleanup_staging(plan).status == "cleaned"
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_missing_provider_is_installable_and_staged_but_requires_runtime_configuration(
    tmp_path: Path,
) -> None:
    staging_parent = tmp_path / "temporary-staging"
    plan = plan_installation(
        _detection(tmp_path),
        _manifest(tmp_path, providers=False),
        staging_parent=staging_parent,
    )

    assert plan.status == "configuration-required"
    assert plan.installable is True
    assert {worker.status for worker in plan.workers} == {"configuration-required"}
    assert all(worker.provider is None for worker in plan.workers)
    assert plan.staging_dir is not None and plan.staging_dir.is_dir()
    assert confirm_install_plan(plan, plan.confirmation_token)
    assert plan.runtime_validated is False
    assert cleanup_staging(plan).status == "cleaned"


def test_missing_required_profile_command_is_unsupported_before_staging(tmp_path: Path) -> None:
    detection = replace(
        _detection(tmp_path),
        capabilities=HermesCapabilities(REQUIRED - {"describe"}, frozenset({"describe"})),
    )
    staging_parent = tmp_path / "temporary-staging"

    plan = plan_installation(detection, _manifest(tmp_path), staging_parent=staging_parent)

    assert plan.status == "unsupported"
    assert plan.staging_dir is None
    assert not staging_parent.exists()


@pytest.mark.parametrize(
    "kind",
    [ProfileEntryKind.PROFILE, ProfileEntryKind.SYMLINK, ProfileEntryKind.NON_DIRECTORY],
)
def test_any_target_name_entry_kind_is_a_conflict_before_staging(
    tmp_path: Path, kind: ProfileEntryKind
) -> None:
    detection = _detection(
        tmp_path,
        ProfileEntry(
            name="codex-5-3-small-worker",
            path=tmp_path / "actual-hermes-home" / "profiles" / "codex-5-3-small-worker",
            kind=kind,
        ),
    )
    staging_parent = tmp_path / "temporary-staging"

    plan = plan_installation(detection, _manifest(tmp_path), staging_parent=staging_parent)

    assert plan.status == "conflict"
    assert plan.staging_dir is None
    assert not staging_parent.exists()


def test_invalid_manifest_is_closed_and_does_not_expose_parser_detail(tmp_path: Path) -> None:
    manifest = tmp_path / "workers.yaml"
    manifest.write_text("secret: audit-secret-value\n", encoding="utf-8")

    plan = plan_installation(
        _detection(tmp_path), manifest, staging_parent=tmp_path / "temporary-staging"
    )

    assert plan.status == "invalid"
    assert plan.reason == "manifest is invalid"
    assert "audit-secret-value" not in repr(plan)


def test_detection_error_maps_to_invalid_before_any_staging(tmp_path: Path) -> None:
    def fail_detection() -> Never:
        raise DetectionError("private detection detail")

    staging_parent = tmp_path / "temporary-staging"
    plan = preflight_installation(
        fail_detection, _manifest(tmp_path), staging_parent=staging_parent
    )

    assert plan.status == "invalid"
    assert plan.hermes is None
    assert plan.reason == "Hermes detection failed"
    assert not staging_parent.exists()


def test_staging_scan_failure_is_invalid_and_cleanup_is_verified(tmp_path: Path) -> None:
    staging_parent = tmp_path / "temporary-staging"

    def reject_staging(_path: Path) -> Never:
        raise ValueError("sensitive scanner detail")

    plan = plan_installation(
        _detection(tmp_path),
        _manifest(tmp_path),
        staging_parent=staging_parent,
        staging_scanner=reject_staging,
    )

    assert plan.status == "invalid"
    assert plan.reason == "staging validation failed"
    assert plan.staging_dir is None
    assert staging_parent.is_dir()
    assert list(staging_parent.iterdir()) == []
    assert "sensitive scanner detail" not in repr(plan)


def test_confirmation_binds_complete_current_plan_and_rejects_tampering(tmp_path: Path) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    assert confirm_install_plan(plan, plan.confirmation_token)
    assert not confirm_install_plan(plan, "0" * 64)

    worker = replace(plan.workers[0], model="tampered-model")
    tampered = replace(plan, workers=(worker, *plan.workers[1:]))
    assert not confirm_install_plan(tampered, plan.confirmation_token)
    assert cleanup_staging(plan).status == "cleaned"


def test_plan_projection_excludes_secrets_endpoints_and_default_profile_state(
    tmp_path: Path,
) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    payload = json.dumps(asdict(plan), default=str, sort_keys=True)

    assert "secret" not in payload.lower()
    assert "base_url" not in payload
    assert '"default"' not in payload
    assert "instructions" not in payload
    assert cleanup_staging(plan).status == "cleaned"


def test_preflight_rejects_staging_inside_actual_hermes_home_without_writing(
    tmp_path: Path,
) -> None:
    detection = _detection(tmp_path)
    detection.hermes_home.mkdir(parents=True)
    sentinel = detection.hermes_home / "sentinel"
    sentinel.write_text("unchanged", encoding="utf-8")

    plan = plan_installation(
        detection,
        _manifest(tmp_path),
        staging_parent=detection.hermes_home / "temporary-staging",
    )

    assert plan.status == "invalid"
    assert plan.reason == "staging boundary is invalid"
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert {path.name for path in detection.hermes_home.iterdir()} == {"sentinel"}


def test_cleanup_rejects_tampered_plan_path(tmp_path: Path) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    protected = tmp_path / "protected"
    protected.mkdir()
    tampered = replace(plan, staging_dir=protected)

    assert cleanup_staging(tampered).status == "refused"
    assert protected.is_dir()
    assert cleanup_staging(plan).status == "cleaned"


def test_provider_overrides_are_trimmed_closed_and_isolated_per_worker(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, providers=False)
    plan = plan_installation(
        _detection(tmp_path),
        manifest,
        staging_parent=tmp_path / "staging",
        provider_selection={"luna_worker": "  selected-provider  "},
    )

    assert plan.status == "configuration-required"
    assert plan.installable is True
    assert plan.workers[0].provider == "selected-provider"
    assert plan.workers[0].runtime_configuration == "selected-but-runtime-unvalidated"
    assert plan.workers[1].provider is None
    assert plan.workers[1].runtime_configuration == "configuration-required"
    assert cleanup_staging(plan).status == "cleaned"

    for invalid in ({"unknown": "provider"}, {"luna_worker": "   "}):
        rejected = plan_installation(
            _detection(tmp_path),
            manifest,
            staging_parent=tmp_path / "other-staging",
            provider_selection=invalid,
        )
        assert rejected.status == "invalid"
        assert rejected.staging_dir is None


def test_artifact_change_makes_revalidation_and_confirmation_stale(tmp_path: Path) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    assert revalidate_install_plan(plan)
    assert plan.staging_dir is not None
    config = plan.staging_dir / plan.workers[0].profile_name / "config.yaml"
    config.write_bytes(config.read_bytes() + b"\n")

    assert not revalidate_install_plan(plan)
    assert not confirm_install_plan(plan, plan.confirmation_token)
    assert cleanup_staging(plan).status == "cleaned"


def test_artifact_same_bytes_replacement_inode_makes_plan_stale(tmp_path: Path) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    assert plan.staging_dir is not None
    artifact = plan.staging_dir / plan.workers[0].profile_name / "config.yaml"
    replacement = artifact.with_name("replacement")
    replacement.write_bytes(artifact.read_bytes())
    os.replace(replacement, artifact)

    assert not revalidate_install_plan(plan)
    assert not confirm_install_plan(plan, plan.confirmation_token)
    assert cleanup_staging(plan).status == "cleaned"


def test_revalidation_rejects_changed_detection_and_plan_repr_hides_staging_path(
    tmp_path: Path,
) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "private-staging"
    )
    assert plan.staging_dir is not None
    assert str(plan.staging_dir) not in repr(plan)
    conflicting = _detection(
        tmp_path,
        ProfileEntry(
            name=plan.workers[0].profile_name,
            path=tmp_path / "actual-hermes-home" / "profiles" / plan.workers[0].profile_name,
            kind=ProfileEntryKind.PROFILE,
        ),
    )
    assert not revalidate_install_plan(plan, conflicting)
    assert cleanup_staging(plan).status == "cleaned"


def test_cleanup_refuses_replacement_symlink_and_renamed_original(tmp_path: Path) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    assert plan.staging_dir is not None
    original = plan.staging_dir
    renamed = original.with_name("renamed-original")
    original.rename(renamed)
    original.mkdir()

    outcome = cleanup_staging(plan)
    assert outcome.status == "refused"
    assert original.is_dir()
    assert renamed.is_dir()
    original.rmdir()
    original.symlink_to(renamed, target_is_directory=True)
    outcome = cleanup_staging(plan)
    assert outcome.status == "refused"
    assert original.is_symlink()
    original.unlink()
    shutil.rmtree(renamed)


def test_cleanup_race_never_deletes_replacement_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    assert plan.staging_dir is not None
    original = plan.staging_dir
    moved = original.with_name("moved-original")
    real_rename = os.rename
    raced = False

    def replace_at_rename(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal raced
        if not raced and src == original.name and src_dir_fd is not None:
            raced = True
            real_rename(src, moved.name, src_dir_fd=src_dir_fd, dst_dir_fd=src_dir_fd)
            os.mkdir(src, dir_fd=src_dir_fd)
            marker_fd = os.open(
                f"{src}/replacement-marker", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=src_dir_fd
            )
            os.close(marker_fd)
        real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr("agentporter.planning.os.rename", replace_at_rename)
    outcome = cleanup_staging(plan)

    assert raced
    assert outcome.status == "refused"
    assert (original / "replacement-marker").is_file()
    assert moved.is_dir()
    shutil.rmtree(original)
    shutil.rmtree(moved)


def test_cleanup_isolates_before_rmtree_so_original_name_replacement_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_installation(
        _detection(tmp_path), _manifest(tmp_path), staging_parent=tmp_path / "staging"
    )
    assert plan.staging_dir is not None
    original = plan.staging_dir
    real_rmtree = shutil.rmtree

    def replace_at_rmtree(path: str, *, dir_fd: int | None = None) -> None:
        assert dir_fd is not None
        assert path != original.name
        original.mkdir()
        (original / "replacement-marker").write_text("keep", encoding="utf-8")
        real_rmtree(path, dir_fd=dir_fd)

    monkeypatch.setattr("agentporter.planning.shutil.rmtree", replace_at_rmtree)
    outcome = cleanup_staging(plan)

    assert outcome.status == "cleaned"
    assert (original / "replacement-marker").read_text(encoding="utf-8") == "keep"
    real_rmtree(original)


def test_unexpected_runtime_error_propagates_after_identity_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging_parent = tmp_path / "staging"

    def explode(*_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("programming defect")

    monkeypatch.setattr("agentporter.planning.render_staging", explode)
    with pytest.raises(RuntimeError, match="programming defect"):
        plan_installation(_detection(tmp_path), _manifest(tmp_path), staging_parent=staging_parent)
    assert list(staging_parent.iterdir()) == []


def test_keyboard_interrupt_cleans_identity_then_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging_parent = tmp_path / "staging"

    def interrupt(*_args: object, **_kwargs: object) -> Never:
        raise KeyboardInterrupt

    monkeypatch.setattr("agentporter.planning.render_staging", interrupt)
    with pytest.raises(KeyboardInterrupt):
        plan_installation(_detection(tmp_path), _manifest(tmp_path), staging_parent=staging_parent)
    assert list(staging_parent.iterdir()) == []


def test_staging_cleanup_failure_is_visible_with_residual_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(_path: Path) -> Never:
        raise ValueError("known invalid staging")

    def fail_cleanup(*_args: object, **_kwargs: object) -> Never:
        raise OSError("cannot remove")

    monkeypatch.setattr("agentporter.planning.shutil.rmtree", fail_cleanup)
    plan = plan_installation(
        _detection(tmp_path),
        _manifest(tmp_path),
        staging_parent=tmp_path / "staging",
        staging_scanner=reject,
    )

    assert plan.status == "invalid"
    assert isinstance(plan.cleanup_outcome, CleanupOutcome)
    assert plan.cleanup_outcome.status == "failed"
    assert plan.cleanup_outcome.residual_path is not None
    assert plan.cleanup_outcome.residual_path.exists()
    assert "cannot remove" not in repr(plan)
