from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

import pytest

from agentporter import uninstall_planning
from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.uninstall_discovery import DiscoveryStatus, discover_installation
from agentporter.uninstall_planning import (
    InteractionStatus,
    PlanStatus,
    build_uninstall_plan,
    render_uninstall_plan,
    revalidate_uninstall_collection,
    run_uninstall_confirmation,
)

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"
MARKER_NAME = "agentporter-profile.json"


def _write_marker(profile: Path, component_id: str) -> None:
    profile.mkdir(parents=True)
    (profile / MARKER_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_id": PRODUCT_ID,
                "component_id": component_id,
                "installation_id": INSTALLATION_ID,
                "distribution_version": "0.1.0",
            }
        )
    )


def _discover(tmp_path: Path):
    home = tmp_path / ".hermes"
    root = home / "profiles"
    for name, component_id in zip(
        ("batch-renamed-luna", "batch-renamed-orion"), COMPONENT_IDS.values(), strict=True
    ):
        _write_marker(root / name, component_id)
    return discover_installation(root)


def test_ready_discovery_builds_sealed_plan_and_revalidates_before_continuation(
    tmp_path: Path,
) -> None:
    discovery = _discover(tmp_path)

    assert discovery.status is DiscoveryStatus.READY
    plan = build_uninstall_plan(discovery)

    assert plan.status is PlanStatus.READY
    assert discovery.hermes_home == tmp_path / ".hermes"
    assert discovery.profiles_root == tmp_path / ".hermes" / "profiles"
    rendered = render_uninstall_plan(plan)
    assert "batch-renamed-luna" in rendered
    assert "batch-renamed-orion" in rendered
    continuations = 0

    def continue_once() -> str:
        nonlocal continuations
        continuations += 1
        return "delete-stage"

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=continue_once,
        input_fn=lambda _: plan.confirmation_phrase,
        output=StringIO(),
    )

    assert outcome.status is InteractionStatus.CONFIRMED
    assert outcome.continuation_result == "delete-stage"
    assert continuations == 1


def test_non_ready_discovery_cannot_build_plan(tmp_path: Path) -> None:
    discovery = discover_installation(tmp_path / ".hermes" / "profiles")

    assert discovery.status is DiscoveryStatus.ALREADY_ABSENT
    assert build_uninstall_plan(discovery).status is PlanStatus.INVALID


@pytest.mark.parametrize(
    "mutation",
    [
        "marker-bytes",
        "marker-same-bytes-replacement",
        "profile-rename-and-occupy",
        "candidate-symlink",
        "root-switch",
    ],
)
def test_collection_revalidation_fails_closed_for_path_or_identity_mutation(
    tmp_path: Path, mutation: str
) -> None:
    discovery = _discover(tmp_path)
    plan = build_uninstall_plan(discovery)
    assert plan.status is PlanStatus.READY
    first = plan.targets[0]
    marker = first.path / MARKER_NAME

    if mutation == "marker-bytes":
        marker.write_bytes(marker.read_bytes() + b"\n")
    elif mutation == "marker-same-bytes-replacement":
        replacement = tmp_path / "replacement-marker"
        replacement.write_bytes(marker.read_bytes())
        os.replace(replacement, marker)
    elif mutation == "profile-rename-and-occupy":
        moved = tmp_path / "moved-profile"
        first.path.rename(moved)
        first.path.mkdir()
        (first.path / MARKER_NAME).write_bytes((moved / MARKER_NAME).read_bytes())
    elif mutation == "candidate-symlink":
        moved = tmp_path / "moved-profile"
        first.path.rename(moved)
        first.path.symlink_to(moved, target_is_directory=True)
    elif mutation == "root-switch":
        assert plan.profiles_root is not None
        moved = tmp_path / "moved-root"
        plan.profiles_root.rename(moved)
        plan.profiles_root.mkdir()
        for target in plan.targets:
            source = moved / target.current_name
            destination = plan.profiles_root / target.current_name
            destination.mkdir()
            (destination / MARKER_NAME).write_bytes((source / MARKER_NAME).read_bytes())

    continuations = 0

    def must_not_continue() -> None:
        nonlocal continuations
        continuations += 1

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate_uninstall_collection,
        continuation=must_not_continue,
        input_fn=lambda _: plan.confirmation_phrase,
        output=StringIO(),
    )

    assert outcome.status is InteractionStatus.STALE
    assert continuations == 0


def test_revalidation_capability_check_is_dynamic_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = build_uninstall_plan(_discover(tmp_path))
    monkeypatch.setattr(uninstall_planning, "_revalidation_supported", lambda: False)
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("filesystem accessed"))

    assert not revalidate_uninstall_collection(plan)


def test_repeated_collection_revalidation_closes_every_descriptor(tmp_path: Path) -> None:
    plan = build_uninstall_plan(_discover(tmp_path))
    descriptor_dir = Path("/proc/self/fd")
    if not descriptor_dir.exists():
        pytest.skip("descriptor counter unavailable")
    before = len(tuple(descriptor_dir.iterdir()))

    for _ in range(50):
        assert revalidate_uninstall_collection(plan)

    assert len(tuple(descriptor_dir.iterdir())) == before
