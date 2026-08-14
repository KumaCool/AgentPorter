from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

from agentporter import compensation
from agentporter.compensation import compensate_profiles
from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from agentporter.planning import plan_installation
from agentporter.readback import InstalledProfileReadback, validate_installed_profile
from tests.plan06_support import runtime_bindings

plan_installation = partial(plan_installation, binding_selection=runtime_bindings())

INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")
REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})


class FakeExecutor:
    def __init__(
        self, outcomes: Sequence[CommandOutcome | BaseException], targets: list[Path]
    ) -> None:
        self.outcomes = iter(outcomes)
        self.targets = targets
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str]]] = []

    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
        normalized = tuple(argv)
        self.calls.append((normalized, env))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome.status is CommandStatus.SUCCEEDED and self.targets:
            shutil.rmtree(self.targets.pop())
        return outcome


def _outcome(status: CommandStatus, returncode: int | None = None) -> CommandOutcome:
    return CommandOutcome(status, ("ignored",), returncode)


def _fixtures(tmp_path: Path) -> tuple[HermesDetection, tuple[InstalledProfileReadback, ...]]:
    source_manifest = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
    manifest = tmp_path / "workers.yaml"
    data = yaml.safe_load(source_manifest.read_text(encoding="utf-8"))
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.write_text("binary", encoding="utf-8")
    home = tmp_path / "hermes"
    (home / "profiles").mkdir(parents=True)
    detection = HermesDetection(
        executable=executable.resolve(),
        version="0.20.0",
        hermes_home=home.resolve(),
        profiles_root=(home / "profiles").resolve(),
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=(),
    )
    plan = plan_installation(
        detection,
        manifest,
        staging_parent=tmp_path / "staging",
        installation_id_factory=lambda: INSTALLATION_ID,
    )
    assert plan.staging_dir is not None
    readbacks = []
    for worker in plan.workers:
        source = plan.staging_dir / worker.profile_name
        target = detection.profiles_root / worker.profile_name
        shutil.copytree(source, target)
        distribution = yaml.safe_load((target / "distribution.yaml").read_text(encoding="utf-8"))
        distribution["source"] = str(source.resolve())
        (target / "distribution.yaml").write_text(yaml.safe_dump(distribution), encoding="utf-8")
        readbacks.append(
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
    return detection, tuple(readbacks)


def _enumerator(detection: HermesDetection):
    def enumerate_profiles() -> tuple[ProfileEntry, ...]:
        if not detection.profiles_root.exists():
            return ()
        return tuple(
            ProfileEntry(path.name, path, ProfileEntryKind.PROFILE)
            for path in detection.profiles_root.iterdir()
            if path.is_dir()
        )

    return enumerate_profiles


def _run(
    detection: HermesDetection,
    readbacks: tuple[InstalledProfileReadback, ...],
    executor: FakeExecutor,
    **kwargs: Any,
):
    env = {"HERMES_HOME": str(detection.hermes_home)}
    return compensate_profiles(
        readbacks,
        current_detection=lambda: detection,
        executor=executor,  # type: ignore[arg-type]
        env=env,
        enumerate_profiles=kwargs.pop("enumerate_profiles", _enumerator(detection)),
        **kwargs,
    )


def test_compensates_in_reverse_order_with_native_argv_and_double_readback(tmp_path: Path) -> None:
    detection, readbacks = _fixtures(tmp_path)
    targets = [item.snapshot.path for item in readbacks]
    executor = FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0) for _ in readbacks], targets)

    result = _run(detection, readbacks, executor)

    assert result.status == "compensated"
    assert [item.status for item in result.items] == ["deleted"] * len(readbacks)
    assert [call[0] for call in executor.calls] == [
        (str(detection.executable), "profile", "delete", item.snapshot.basename, "--yes")
        for item in reversed(readbacks)
    ]
    assert all(
        call_env["HERMES_HOME"] == str(detection.hermes_home) for _, call_env in executor.calls
    )
    assert all(not item.snapshot.path.exists() for item in readbacks)


def test_first_reverse_delete_success_then_second_failure_is_incomplete(tmp_path: Path) -> None:
    detection, readbacks = _fixtures(tmp_path)
    executor = FakeExecutor(
        [_outcome(CommandStatus.SUCCEEDED, 0), _outcome(CommandStatus.FAILED, 7)],
        [item.snapshot.path for item in readbacks],
    )

    result = _run(detection, readbacks, executor)

    assert result.status == "compensation-incomplete"
    assert [item.status for item in result.items] == ["deleted", "delete-failed"]


@pytest.mark.parametrize(
    "mutation", ["rename", "replace", "occupied", "marker", "root", "default", "invalid"]
)
def test_snapshot_change_refuses_delete_and_stops(tmp_path: Path, mutation: str) -> None:
    detection, readbacks = _fixtures(tmp_path)
    selected = readbacks[-1]
    snapshot = selected.snapshot
    current = detection
    if mutation == "rename":
        snapshot.path.rename(snapshot.path.with_name("renamed"))
    elif mutation == "replace":
        old = snapshot.path.with_name("old")
        snapshot.path.rename(old)
        shutil.copytree(old, snapshot.path)
    elif mutation == "occupied":
        snapshot.path.rename(snapshot.path.with_name("renamed"))
        snapshot.path.mkdir()
        (snapshot.path / "do-not-delete").write_text("replacement", encoding="utf-8")
    elif mutation == "marker":
        marker = snapshot.path / "agentporter-profile.json"
        replacement = snapshot.path / "replacement"
        replacement.write_bytes(marker.read_bytes())
        replacement.replace(marker)
    elif mutation == "root":
        other = tmp_path / "other-hermes"
        (other / "profiles").mkdir(parents=True)
        current = replace(
            detection, hermes_home=other.resolve(), profiles_root=(other / "profiles").resolve()
        )
    elif mutation == "default":
        selected = replace(
            selected,
            snapshot=replace(snapshot, basename="default", path=snapshot.path.with_name("default")),
        )
        readbacks = (*readbacks[:-1], selected)
    else:
        selected = replace(selected, snapshot=replace(snapshot, basename="../bad"))
        readbacks = (*readbacks[:-1], selected)
    executor = FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0)], [])

    result = compensate_profiles(
        readbacks,
        current_detection=lambda: current,
        executor=executor,  # type: ignore[arg-type]
        env={},
        enumerate_profiles=_enumerator(detection),
    )

    assert result.status == "compensation-incomplete"
    assert result.items[0].status == "snapshot-changed"
    assert len(result.items) == 1
    assert executor.calls == []


def test_enumerator_error_after_successful_command_is_verification_failed(tmp_path: Path) -> None:
    detection, readbacks = _fixtures(tmp_path)
    executor = FakeExecutor(
        [_outcome(CommandStatus.SUCCEEDED, 0)], [item.snapshot.path for item in readbacks]
    )

    result = _run(
        detection,
        (readbacks[-1],),
        executor,
        enumerate_profiles=lambda: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    assert result.status == "compensation-incomplete"
    assert result.items[0].status == "verification-failed"
    assert "private detail" not in repr(result)


def test_path_lstat_still_runs_when_post_delete_enumerator_errors(
    tmp_path: Path, monkeypatch
) -> None:
    detection, readbacks = _fixtures(tmp_path)
    executor = FakeExecutor(
        [_outcome(CommandStatus.SUCCEEDED, 0)], [item.snapshot.path for item in readbacks]
    )
    real_lstat = os.lstat
    observed: list[Path] = []

    def recording_lstat(path: Path, *, dir_fd: int | None = None) -> os.stat_result:
        if dir_fd is None:
            observed.append(path)
        return real_lstat(path, dir_fd=dir_fd)

    monkeypatch.setattr(compensation.os, "lstat", recording_lstat)
    result = _run(
        detection,
        (readbacks[-1],),
        executor,
        enumerate_profiles=lambda: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    assert result.items[0].status == "verification-failed"
    assert readbacks[-1].snapshot.path in observed


def test_successful_command_with_path_remaining_is_verification_failed(tmp_path: Path) -> None:
    detection, readbacks = _fixtures(tmp_path)
    executor = FakeExecutor([_outcome(CommandStatus.SUCCEEDED, 0)], [])

    result = _run(detection, (readbacks[-1],), executor)

    assert result.items[0].status == "verification-failed"
    assert readbacks[-1].snapshot.path.exists()


def test_command_failure_is_delete_failed_even_when_path_remains(tmp_path: Path) -> None:
    detection, readbacks = _fixtures(tmp_path)
    executor = FakeExecutor([_outcome(CommandStatus.FAILED, 9)], [])

    result = _run(detection, (readbacks[-1],), executor)

    assert result.items[0].status == "delete-failed"


@pytest.mark.parametrize("error", [SystemExit(17), KeyboardInterrupt()])
def test_executor_baseexception_runs_both_readbacks_then_propagates(
    tmp_path: Path, error: BaseException
) -> None:
    detection, readbacks = _fixtures(tmp_path)
    observations: list[str] = []

    def enumerate_profiles() -> tuple[ProfileEntry, ...]:
        observations.append("enumerated")
        return _enumerator(detection)()

    executor = FakeExecutor([error], [])
    with pytest.raises(type(error)) as raised:
        _run(
            detection,
            (readbacks[-1],),
            executor,
            enumerate_profiles=enumerate_profiles,
        )

    assert raised.value is error
    assert observations == ["enumerated"]
    assert any("post-delete" in note and "uncertain" in note for note in error.__notes__)


def test_descriptor_is_closed_after_snapshot_rejection(tmp_path: Path, monkeypatch) -> None:
    detection, readbacks = _fixtures(tmp_path)
    marker = readbacks[-1].snapshot.path / "agentporter-profile.json"
    marker.write_bytes(marker.read_bytes() + b" ")
    real_close = os.close
    closed: list[int] = []

    def recording_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "close", recording_close)
    result = _run(detection, (readbacks[-1],), FakeExecutor([], []))

    assert result.items[0].status == "snapshot-changed"
    assert len(closed) >= 2
