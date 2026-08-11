from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from io import StringIO
from pathlib import Path

import pytest

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.uninstall_application import UninstallerStatus, run_uninstaller
from agentporter.uninstall_execution import UninstallExecutionStatus

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"
REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})


def _write_installation(root: Path) -> tuple[str, ...]:
    names = ("batch-renamed-luna", "batch-renamed-orion")
    for name, component_id in zip(names, COMPONENT_IDS.values(), strict=True):
        profile = root / name
        profile.mkdir(parents=True)
        (profile / "agentporter-profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "product_id": PRODUCT_ID,
                    "component_id": component_id,
                    "installation_id": INSTALLATION_ID,
                    "distribution_version": "0.1.0",
                }
            ),
            encoding="utf-8",
        )
    return names


def _detection(home: Path, executable: Path) -> HermesDetection:
    return HermesDetection(
        executable=executable,
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=(),
    )


def test_already_absent_is_typed_success_without_interaction_or_commands(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.touch()
    detection = _detection(tmp_path / ".hermes", executable.resolve())

    result = run_uninstaller(
        {},
        input_fn=lambda _: pytest.fail("must not interact"),
        output=StringIO(),
        detector=lambda **_: detection,
        executor_factory=lambda: pytest.fail("must not create executor"),
        adapter_factory=lambda *args: pytest.fail("must not create adapter"),
    )

    assert result.status is UninstallerStatus.ALREADY_ABSENT
    assert result.execution is None


def test_ambiguous_result_is_safe_and_never_interacts_or_executes(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.touch()
    root = tmp_path / ".hermes" / "profiles"
    profile = root / "private-profile-name"
    profile.mkdir(parents=True)
    secret = "raw-private-marker-secret"
    (profile / "agentporter-profile.json").write_text(secret, encoding="utf-8")
    output = StringIO()

    result = run_uninstaller(
        {},
        input_fn=lambda _: pytest.fail("must not interact"),
        output=output,
        detector=lambda **_: _detection(tmp_path / ".hermes", executable.resolve()),
        executor_factory=lambda: pytest.fail("must not execute"),
        adapter_factory=lambda *args: pytest.fail("must not adapt"),
    )

    assert result.status is UninstallerStatus.AMBIGUOUS
    assert result.findings
    rendered = output.getvalue()
    assert str(profile / "agentporter-profile.json") in rendered
    assert secret not in rendered
    assert "marker schema is invalid" not in rendered


def test_confirmed_batch_rename_deletes_with_fresh_detection_per_target(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch()
    executable = executable.resolve()
    home = (tmp_path / ".hermes").resolve()
    names = _write_installation(home / "profiles")
    detections = 0
    commands: list[tuple[str, ...]] = []

    def detector(*, env: Mapping[str, str]) -> HermesDetection:
        nonlocal detections
        detections += 1
        return _detection(home, executable)

    class Executor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            normalized = tuple(argv)
            commands.append(normalized)
            shutil.rmtree(home / "profiles" / normalized[3])
            return CommandOutcome(CommandStatus.SUCCEEDED, normalized, 0)

    output = StringIO()

    def answer(_: str) -> str:
        text = output.getvalue()
        installation = text.split("Installation ID: ", 1)[1].splitlines()[0]
        return f"DELETE AGENTPORTER {installation[:8]}"

    result = run_uninstaller(
        {"HOME": str(tmp_path)},
        input_fn=answer,
        output=output,
        detector=detector,
        executor_factory=Executor,  # type: ignore[arg-type]
    )

    assert result.status is UninstallerStatus.DELETED
    assert result.execution is not None
    assert result.execution.status is UninstallExecutionStatus.DELETED
    assert detections == 4  # discovery, continuation binding, then immediately before each target
    assert commands == [(str(executable), "profile", "delete", name, "--yes") for name in names]


def test_cancel_has_zero_executor_adapter_or_delete(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.touch()
    home = tmp_path / ".hermes"
    _write_installation(home / "profiles")

    result = run_uninstaller(
        {},
        input_fn=lambda _: "no",
        output=StringIO(),
        detector=lambda **_: _detection(home, executable.resolve()),
        executor_factory=lambda: pytest.fail("cancel must not create executor"),
        adapter_factory=lambda *args: pytest.fail("cancel must not create adapter"),
    )

    assert result.status is UninstallerStatus.CANCELLED
    assert result.execution is None


def test_root_switch_after_confirmation_is_stale_with_zero_delete(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.touch()
    home = tmp_path / ".hermes"
    root = home / "profiles"
    _write_installation(root)
    output = StringIO()

    def answer(_: str) -> str:
        moved = tmp_path / "moved-root"
        root.rename(moved)
        root.mkdir()
        installation = output.getvalue().split("Installation ID: ", 1)[1].splitlines()[0]
        return f"DELETE AGENTPORTER {installation[:8]}"

    result = run_uninstaller(
        {},
        input_fn=answer,
        output=output,
        detector=lambda **_: _detection(home, executable.resolve()),
        executor_factory=lambda: pytest.fail("stale plan must not execute"),
    )

    assert result.status is UninstallerStatus.STALE


def test_second_target_marker_replacement_returns_partial_delete(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.touch()
    executable = executable.resolve()
    home = tmp_path / ".hermes"
    names = _write_installation(home / "profiles")
    output = StringIO()
    calls = 0

    class Executor:
        def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
            nonlocal calls
            calls += 1
            normalized = tuple(argv)
            shutil.rmtree(home / "profiles" / normalized[3])
            if calls == 1:
                marker = home / "profiles" / names[1] / "agentporter-profile.json"
                marker.write_bytes(marker.read_bytes() + b"\n")
            return CommandOutcome(CommandStatus.SUCCEEDED, normalized, 0)

    def answer(_: str) -> str:
        installation = output.getvalue().split("Installation ID: ", 1)[1].splitlines()[0]
        return f"DELETE AGENTPORTER {installation[:8]}"

    result = run_uninstaller(
        {},
        input_fn=answer,
        output=output,
        detector=lambda **_: _detection(home, executable),
        executor_factory=Executor,  # type: ignore[arg-type]
    )

    assert result.status is UninstallerStatus.PARTIAL_DELETE
    assert result.execution is not None
    assert result.execution.status is UninstallExecutionStatus.PARTIAL_DELETE
    assert calls == 1
