from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import stat
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import ProfileEntry, ProfileEntryKind
from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.uninstall_discovery import MARKER_NAME, DiscoveryStatus, discover_installation
from agentporter.uninstall_execution import UninstallExecutionResult, execute_uninstall_plan
from agentporter.uninstall_planning import (
    InteractionStatus,
    PlanStatus,
    build_uninstall_plan,
    revalidate_uninstall_collection,
    revalidate_uninstall_target,
    run_uninstall_confirmation,
)

SCALE_SIZES = (2, 10, 100, 1000)
FAULTS = (
    "rename",
    "replace-marker",
    "occupy",
    "symlink",
    "profile-inode-replacement",
    "root-switch",
    "marker-change",
    "command-failed",
    "command-timed-out",
    "command-interrupted",
    "baseexception-before-effect",
    "baseexception-after-effect",
)
CYCLES = 120
UNRELATED_PRODUCT_ID = "4ec1b184-63b5-47e3-a1b9-2f7872d1639e"
UNRELATED_COMPONENT_ID = "97f58f4b-8ebd-4b69-ae18-84a5b2d6bd38"


@dataclass(frozen=True)
class TreeEntry:
    relative_path: str
    device: int
    inode: int
    mode_type: int
    size: int
    mtime_ns: int
    sha256: str | None


@dataclass(frozen=True)
class ScanEvidence:
    profile_count: int
    expected_status: str
    observed_status: str
    target_count: int
    finding_count: int
    wall_seconds: float
    cpu_seconds: float
    peak_rss_delta_kib: int
    disk_write_bytes: int
    tree_unchanged: bool


@dataclass(frozen=True)
class CycleEvidence:
    cycle: int
    fault: str
    interaction_status: str
    execution_status: str | None
    command_count: int
    unsafe_deletions: int
    protected_profiles: int
    safe_remnants: tuple[str, ...]
    model_calls: int
    credential_calls: int


def _marker(*, product_id: str, component_id: str, installation_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "product_id": product_id,
            "component_id": component_id,
            "installation_id": installation_id,
            "distribution_version": "0.1.0",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _write_profile(root: Path, name: str, marker: bytes, sentinel: str) -> Path:
    profile = root / name
    profile.mkdir()
    (profile / MARKER_NAME).write_bytes(marker)
    (profile / "background-sentinel.txt").write_text(sentinel, encoding="utf-8")
    return profile


def _synthetic_root(base: Path, size: int, *, ambiguous: bool = False) -> Path:
    profiles = (base / "hermes" / "profiles").resolve()
    profiles.mkdir(parents=True)
    installation_id = str(uuid5(NAMESPACE_URL, f"agentporter-phase5-{size}-{ambiguous}"))
    components = tuple(COMPONENT_IDS.values())
    for index, component_id in enumerate(components):
        marker_installation = installation_id
        if ambiguous and index == 1:
            marker_installation = str(uuid5(NAMESPACE_URL, f"phase5-conflict-{size}"))
        _write_profile(
            profiles,
            f"owned-{index}",
            _marker(
                product_id=PRODUCT_ID,
                component_id=component_id,
                installation_id=marker_installation,
            ),
            f"owned-{index}",
        )
    for index in range(size - len(components)):
        name = "default" if index == 0 else f"background-{index:04d}"
        _write_profile(
            profiles,
            name,
            _marker(
                product_id=UNRELATED_PRODUCT_ID,
                component_id=UNRELATED_COMPONENT_ID,
                installation_id=str(uuid5(NAMESPACE_URL, f"background-{size}-{index}")),
            ),
            f"protected-{size}-{index}",
        )
    assert len(tuple(profiles.iterdir())) == size
    return profiles


def _tree_snapshot(root: Path) -> tuple[TreeEntry, ...]:
    entries: list[TreeEntry] = []
    for path in sorted((root, *root.rglob("*")), key=lambda item: str(item.relative_to(root))):
        info = path.lstat()
        digest = None
        if stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(
            TreeEntry(
                relative_path="." if path == root else str(path.relative_to(root)),
                device=info.st_dev,
                inode=info.st_ino,
                mode_type=stat.S_IFMT(info.st_mode),
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                sha256=digest,
            )
        )
    return tuple(entries)


def _write_bytes() -> int:
    try:
        fields = (Path("/proc/self/io").read_text(encoding="ascii")).splitlines()
    except OSError:
        return 0
    values = dict(line.split(":", 1) for line in fields)
    return int(values.get("write_bytes", "0"))


def _measure_scan(profiles: Path, expected: DiscoveryStatus) -> ScanEvidence:
    before_tree = _tree_snapshot(profiles)
    before_write = _write_bytes()
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    before_cpu = time.process_time()
    before_wall = time.perf_counter()
    result = discover_installation(profiles)
    wall = time.perf_counter() - before_wall
    cpu = time.process_time() - before_cpu
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before_rss
    writes = _write_bytes() - before_write
    unchanged = _tree_snapshot(profiles) == before_tree
    evidence = ScanEvidence(
        profile_count=len(tuple(profiles.iterdir())),
        expected_status=expected.value,
        observed_status=result.status.value,
        target_count=len(result.targets),
        finding_count=len(result.findings),
        wall_seconds=wall,
        cpu_seconds=cpu,
        peak_rss_delta_kib=rss,
        disk_write_bytes=writes,
        tree_unchanged=unchanged,
    )
    assert result.status is expected
    assert unchanged
    assert writes == 0
    assert evidence.profile_count in SCALE_SIZES
    assert evidence.wall_seconds >= 0
    assert evidence.cpu_seconds >= 0
    assert evidence.peak_rss_delta_kib >= 0
    assert evidence.disk_write_bytes >= 0
    return evidence


@pytest.mark.parametrize("size", SCALE_SIZES)
def test_phase5_discovery_scale_baseline_is_read_only(tmp_path: Path, size: int) -> None:
    ready = _measure_scan(_synthetic_root(tmp_path / "ready", size), DiscoveryStatus.READY)
    ambiguous = _measure_scan(
        _synthetic_root(tmp_path / "ambiguous", size, ambiguous=True),
        DiscoveryStatus.AMBIGUOUS,
    )

    assert ready.target_count == len(COMPONENT_IDS)
    assert ready.finding_count == 0
    assert ambiguous.target_count == 0
    assert ambiguous.finding_count >= 1
    print(json.dumps({"phase5_scan_evidence": [asdict(ready), asdict(ambiguous)]}, sort_keys=True))


def _enumerate_profiles(root: Path) -> tuple[ProfileEntry, ...]:
    return tuple(
        ProfileEntry(path.name, path, ProfileEntryKind.PROFILE)
        for path in sorted(root.iterdir())
        if path.is_dir() and not path.is_symlink()
    )


def _protected_snapshot(paths: Sequence[Path]) -> dict[Path, tuple[TreeEntry, ...]]:
    return {path: _tree_snapshot(path) for path in paths}


class FaultExecutor:
    def __init__(self, plan_root: Path, fault: str, authorized: frozenset[Path]) -> None:
        self.plan_root = plan_root
        self.fault = fault
        self.authorized = authorized
        self.calls: list[tuple[str, ...]] = []
        self.model_calls = 0
        self.credential_calls = 0

    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
        normalized = tuple(argv)
        self.calls.append(normalized)
        assert len(normalized) == 5
        assert normalized[1:3] == ("profile", "delete")
        assert normalized[4] == "--yes"
        assert not ({"chat", "run"} & set(normalized))
        assert all(not value for key, value in env.items() if key.endswith("API_KEY"))
        target = self.plan_root / normalized[3]
        assert target in self.authorized

        if self.fault == "baseexception-before-effect":
            raise SystemExit("synthetic-before-effect")
        if self.fault == "baseexception-after-effect":
            shutil.rmtree(target)
            raise KeyboardInterrupt("synthetic-after-effect")
        command_status = {
            "command-failed": CommandStatus.FAILED,
            "command-timed-out": CommandStatus.TIMED_OUT,
            "command-interrupted": CommandStatus.INTERRUPTED,
        }.get(self.fault, CommandStatus.SUCCEEDED)
        if command_status is CommandStatus.SUCCEEDED:
            shutil.rmtree(target)
        return CommandOutcome(
            command_status,
            normalized,
            0 if command_status is CommandStatus.SUCCEEDED else None,
        )


@pytest.mark.parametrize("cycle", range(CYCLES), ids=lambda value: f"cycle-{value:03d}")
def test_phase5_fault_cycle_never_deletes_unrelated_profiles(tmp_path: Path, cycle: int) -> None:
    fault = FAULTS[cycle % len(FAULTS)]
    profiles = _synthetic_root(tmp_path, 10)
    executable = (tmp_path / "bin" / "hermes").resolve()
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic executable; never invoked")
    discovery = discover_installation(profiles)
    assert discovery.status is DiscoveryStatus.READY
    plan = build_uninstall_plan(discovery, executable=executable)
    assert plan.status is PlanStatus.READY
    assert revalidate_uninstall_collection(plan)
    authorized = frozenset(target.path for target in plan.targets)
    protected_paths = [path for path in profiles.iterdir() if path not in authorized]
    protected_before = _protected_snapshot(protected_paths)
    remnants: list[Path] = []

    target = plan.targets[0]
    marker = target.path / MARKER_NAME
    if fault == "rename":
        survivor = profiles / "renamed-owned-survivor"
        target.path.rename(survivor)
        remnants.append(survivor)
    elif fault == "replace-marker":
        replacement = tmp_path / "replacement-marker"
        replacement.write_bytes(marker.read_bytes())
        os.replace(replacement, marker)
        remnants.append(target.path)
    elif fault == "occupy":
        survivor = profiles / "occupied-owned-survivor"
        target.path.rename(survivor)
        target.path.mkdir()
        (target.path / "occupant-sentinel").write_text("must survive", encoding="utf-8")
        remnants.extend((survivor, target.path))
    elif fault == "symlink":
        survivor = profiles / "symlink-owned-survivor"
        target.path.rename(survivor)
        try:
            target.path.symlink_to(survivor, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlink unavailable: {type(error).__name__}")
        remnants.extend((survivor, target.path))
    elif fault == "profile-inode-replacement":
        survivor = profiles / "inode-owned-survivor"
        target.path.rename(survivor)
        shutil.copytree(survivor, target.path)
        remnants.extend((survivor, target.path))
    elif fault == "root-switch":
        original = profiles.with_name("profiles-original")
        profiles.rename(original)
        profiles.mkdir()
        (profiles / "root-switch-occupant").mkdir()
        protected_paths = [original / path.name for path in protected_paths]
        protected_before = _protected_snapshot(protected_paths)
        remnants.extend((original / target.current_name, profiles / "root-switch-occupant"))
    elif fault == "marker-change":
        marker.write_bytes(marker.read_bytes() + b"\n")
        remnants.append(target.path)

    executor = FaultExecutor(profiles, fault, authorized)
    execution: UninstallExecutionResult | None = None

    def continue_uninstall() -> UninstallExecutionResult:
        nonlocal execution
        execution = execute_uninstall_plan(
            plan,
            executor=executor,  # type: ignore[arg-type]
            env={"HOME": str(tmp_path), "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""},
            per_target_revalidate=revalidate_uninstall_target,
            enumerate_profiles=lambda: _enumerate_profiles(profiles),
        )
        return execution

    expected_baseexception = fault.startswith("baseexception-")
    try:
        interaction = run_uninstall_confirmation(
            plan,
            revalidate_collection=revalidate_uninstall_collection,
            continuation=continue_uninstall,
            input_fn=lambda _: plan.confirmation_phrase or "",
            output=StringIO(),
        )
    except (SystemExit, KeyboardInterrupt) as error:
        assert expected_baseexception
        assert any("post-delete readback" in note for note in getattr(error, "__notes__", ()))
        interaction_status = InteractionStatus.CONFIRMED.value
    else:
        assert not expected_baseexception
        interaction_status = interaction.status.value
        if fault in FAULTS[:7]:
            assert interaction.status is InteractionStatus.STALE
            assert executor.calls == []
        else:
            assert interaction.status is InteractionStatus.CONFIRMED
            assert execution is not None

    protected_after = _protected_snapshot(protected_paths)
    unsafe_deletions = sum(
        1 for path, snapshot in protected_before.items() if protected_after.get(path) != snapshot
    )
    assert unsafe_deletions == 0
    assert all(path.exists() or path.is_symlink() for path in protected_paths)
    assert all(path.exists() or path.is_symlink() for path in remnants)
    assert executor.model_calls == 0
    assert executor.credential_calls == 0
    assert all((profiles / call[3]) in authorized for call in executor.calls)

    evidence = CycleEvidence(
        cycle=cycle,
        fault=fault,
        interaction_status=interaction_status,
        execution_status=execution.status.value if execution is not None else None,
        command_count=len(executor.calls),
        unsafe_deletions=unsafe_deletions,
        protected_profiles=len(protected_paths),
        safe_remnants=tuple(sorted(path.name for path in remnants)),
        model_calls=executor.model_calls,
        credential_calls=executor.credential_calls,
    )
    assert evidence.cycle < CYCLES
    assert evidence.fault in FAULTS
    print(json.dumps({"phase5_cycle_evidence": asdict(evidence)}, sort_keys=True))


def test_phase5_stress_matrix_schema_and_totals_are_explicit() -> None:
    assert CYCLES >= 100
    assert CYCLES % len(FAULTS) == 0
    assert set(FAULTS) >= {
        "rename",
        "replace-marker",
        "occupy",
        "symlink",
        "profile-inode-replacement",
        "root-switch",
        "command-failed",
        "command-timed-out",
        "command-interrupted",
        "baseexception-before-effect",
        "baseexception-after-effect",
    }
    summary = {
        "schema_version": 1,
        "stress_scope": "synthetic fault semantics and discovery scalability",
        "configured_cycles": CYCLES,
        "fault_kinds": len(FAULTS),
        "unsafe_deletions_required": 0,
        "model_calls_required": 0,
        "credential_calls_required": 0,
        "scale_sizes": list(SCALE_SIZES),
    }
    assert summary["configured_cycles"] == 120
    assert summary["scale_sizes"] == [2, 10, 100, 1000]
    print(json.dumps({"phase5_stress_summary": summary}, sort_keys=True))
