from __future__ import annotations

import os
import shutil
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

from agentporter import readback
from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.planning import plan_installation
from agentporter.readback import (
    ReadbackError,
    validate_installed_profile,
    validate_readback_collection,
)
from tests.plan06_support import runtime_bindings

plan_installation = partial(plan_installation, binding_selection=runtime_bindings())

INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")
REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})


def _plan(tmp_path: Path):
    source = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
    manifest = tmp_path / "workers.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    home = tmp_path / "hermes"
    (home / "profiles").mkdir(parents=True)
    detection = HermesDetection(
        executable=tmp_path / "bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=(),
    )
    plan = plan_installation(
        detection,
        manifest,
        staging_parent=tmp_path / "staging",
        installation_id_factory=lambda: INSTALLATION_ID,
    )
    return plan, detection


def _installed(tmp_path: Path, index: int = 0):
    plan, detection = _plan(tmp_path)
    worker = plan.workers[index]
    assert plan.staging_dir is not None
    source = plan.staging_dir / worker.profile_name
    target = detection.profiles_root / worker.profile_name
    shutil.copytree(source, target)
    distribution = yaml.safe_load((target / "distribution.yaml").read_text(encoding="utf-8"))
    distribution.update(source=str(source.resolve()), installed_at="2026-08-11T10:00:00+00:00")
    (target / "distribution.yaml").write_text(
        yaml.safe_dump(distribution, sort_keys=False), encoding="utf-8"
    )
    return plan, detection, worker, source, target, distribution


def test_single_complete_readback_is_verified_compensable(tmp_path: Path) -> None:
    plan, detection, worker, source, target, distribution = _installed(tmp_path)

    result = validate_installed_profile(
        plan,
        worker,
        detection,
        observation_path=target,
        observation_name=worker.profile_name,
        distribution_info=distribution,
        description=worker.description,
    )

    assert result.status == "verified-compensable"
    assert result.worker == worker
    assert result.snapshot.hermes_home == detection.hermes_home.resolve()
    assert result.snapshot.profiles_root == detection.profiles_root.resolve()
    assert result.snapshot.path == target.resolve()
    assert result.snapshot.basename == worker.profile_name
    assert result.snapshot.source == source.resolve()
    assert result.snapshot.product_id
    assert result.snapshot.component_id == worker.component_id
    assert result.snapshot.installation_id == str(INSTALLATION_ID)
    assert result.snapshot.profile_device > 0
    assert result.snapshot.profile_inode > 0
    assert result.snapshot.marker_device > 0
    assert result.snapshot.marker_inode > 0
    assert len(result.snapshot.marker_sha256) == 64


def _validate(installed: tuple[Any, ...]):
    plan, detection, worker, _source, target, distribution = installed
    return validate_installed_profile(
        plan,
        worker,
        detection,
        observation_path=target,
        observation_name=worker.profile_name,
        distribution_info=distribution,
        description=worker.description,
    )


@pytest.mark.parametrize("escape", ["symlink", "outside", "wrong-name", "default"])
def test_profile_path_must_be_safe_planned_direct_child(tmp_path: Path, escape: str) -> None:
    installed = _installed(tmp_path)
    plan, detection, worker, source, target, distribution = installed
    path, name = target, worker.profile_name
    if escape == "symlink":
        shutil.rmtree(target)
        target.symlink_to(source, target_is_directory=True)
    elif escape == "outside":
        path = tmp_path / "elsewhere" / worker.profile_name
    elif escape == "wrong-name":
        name = "renamed"
    else:
        name = "default"
    with pytest.raises(ReadbackError, match="^unsafe-path:"):
        validate_installed_profile(
            plan,
            worker,
            detection,
            observation_path=path,
            observation_name=name,
            distribution_info=distribution,
            description=worker.description,
        )


def test_distribution_source_rejects_prefix_trap(tmp_path: Path) -> None:
    installed = list(_installed(tmp_path))
    distribution = dict(installed[-1])
    distribution["source"] += "-evil"
    target = installed[-2]
    (target / "distribution.yaml").write_text(yaml.safe_dump(distribution), encoding="utf-8")
    installed[-1] = distribution
    with pytest.raises(ReadbackError, match="^source-mismatch:"):
        _validate(tuple(installed))


@pytest.mark.parametrize("artifact", ["config.yaml", "SOUL.md"])
def test_installed_content_must_match_sealed_hash_and_size(tmp_path: Path, artifact: str) -> None:
    installed = _installed(tmp_path)
    target = installed[-2]
    (target / artifact).write_bytes((target / artifact).read_bytes() + b"tampered")
    with pytest.raises(ReadbackError, match="^content-mismatch:"):
        _validate(installed)


def test_description_is_only_accepted_from_explicit_native_readback(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    plan, detection, worker, _source, target, distribution = installed
    (target / "profile.yaml").write_text(
        yaml.safe_dump({"description": worker.description}), encoding="utf-8"
    )
    with pytest.raises(ReadbackError, match="^description-mismatch:"):
        validate_installed_profile(
            plan,
            worker,
            detection,
            observation_path=target,
            observation_name=worker.profile_name,
            distribution_info=distribution,
            description="",
        )


def test_hermes_bootstrap_directories_do_not_invalidate_owned_artifacts(tmp_path: Path) -> None:
    installed = _installed(tmp_path)
    target = installed[-2]
    (target / "skills").mkdir()
    (target / "sessions").mkdir()
    (target / "profile.yaml").write_text("description: native metadata\n", encoding="utf-8")
    assert _validate(installed).status == "verified-compensable"


def test_unknown_native_distribution_field_is_rejected(tmp_path: Path) -> None:
    installed = list(_installed(tmp_path))
    distribution = dict(installed[-1])
    distribution["project_private_extension"] = "not-hermes-schema"
    target = installed[-2]
    (target / "distribution.yaml").write_text(yaml.safe_dump(distribution), encoding="utf-8")
    installed[-1] = distribution
    with pytest.raises(ReadbackError, match="^invalid-artifact:"):
        _validate(tuple(installed))


def test_marker_replacement_during_readback_is_refused(tmp_path: Path, monkeypatch) -> None:
    installed = _installed(tmp_path)
    target = installed[-2]
    marker = target / "agentporter-profile.json"
    real_read = os.read
    replaced = False

    def replacing_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        data = real_read(fd, size)
        if data and not replaced and os.fstat(fd).st_ino == marker.stat().st_ino:
            replaced = True
            replacement = target / "replacement"
            replacement.write_bytes(marker.read_bytes())
            replacement.replace(marker)
        return data

    monkeypatch.setattr(os, "read", replacing_read)
    with pytest.raises(ReadbackError, match="^unsafe-path:"):
        _validate(installed)


def test_profile_rename_during_readback_is_refused(tmp_path: Path, monkeypatch) -> None:
    installed = _installed(tmp_path)
    target = installed[-2]
    marker = target / "agentporter-profile.json"
    renamed = target.with_name("renamed-after-open")
    real_read = os.read
    moved = False

    def renaming_read(fd: int, size: int) -> bytes:
        nonlocal moved
        data = real_read(fd, size)
        if data and not moved and os.fstat(fd).st_ino == marker.stat().st_ino:
            moved = True
            target.rename(renamed)
        return data

    monkeypatch.setattr(os, "read", renaming_read)
    with pytest.raises(ReadbackError, match="^unsafe-path:"):
        _validate(installed)


def test_descriptor_capability_absence_fails_closed(tmp_path: Path, monkeypatch) -> None:
    installed = _installed(tmp_path)
    monkeypatch.setattr(readback, "_OPEN_SUPPORTS_DIR_FD", False)
    with pytest.raises(ReadbackError, match="^descriptor-unavailable:"):
        _validate(installed)


def test_collection_is_order_independent_and_requires_exact_unique_components(
    tmp_path: Path,
) -> None:
    plan, detection = _plan(tmp_path)
    results = []
    assert plan.staging_dir is not None
    for worker in plan.workers:
        source = plan.staging_dir / worker.profile_name
        target = detection.profiles_root / worker.profile_name
        shutil.copytree(source, target)
        distribution = yaml.safe_load((target / "distribution.yaml").read_text(encoding="utf-8"))
        distribution["source"] = str(source.resolve())
        (target / "distribution.yaml").write_text(yaml.safe_dump(distribution), encoding="utf-8")
        results.append(
            validate_installed_profile(
                plan,
                worker,
                detection,
                observation_path=target,
                observation_name=worker.profile_name,
                distribution_info=distribution,
                description=worker.description,
            )
        )
    assert validate_readback_collection(plan, tuple(reversed(results))) == tuple(reversed(results))
    with pytest.raises(ReadbackError, match="^collection-mismatch:"):
        validate_readback_collection(plan, (results[0], results[0]))
    mismatched = replace(
        results[1], snapshot=replace(results[1].snapshot, installation_id=str(UUID(int=1)))
    )
    with pytest.raises(ReadbackError, match="^collection-mismatch:"):
        validate_readback_collection(plan, (results[0], mismatched))
