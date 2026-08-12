from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID

import yaml

from agentporter.execution import CommandOutcome, CommandStatus
from agentporter.hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from agentporter.install_workflow import InstallWorkflowStatus, install_confirmed_plan
from agentporter.planning import InstallPlan, WorkerInstallPlan, plan_installation
from agentporter.readback import InstalledProfileReadback, validate_readback_collection

REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})
INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")


def _plan(tmp_path: Path) -> tuple[InstallPlan, HermesDetection]:
    source = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    for worker in data["workers"].values():
        worker["provider"] = "static-public-provider"
    manifest = tmp_path / "workers.yaml"
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
    return (
        plan_installation(
            detection,
            manifest,
            staging_parent=tmp_path / "staging",
            installation_id_factory=lambda: INSTALLATION_ID,
        ),
        detection,
    )


class NativeAdapters:
    def __init__(self, plan: InstallPlan, detection: HermesDetection) -> None:
        self.plan = plan
        self.detection = detection
        self.events: list[str] = []
        self.entries: list[ProfileEntry] = []
        self.distributions: dict[str, dict[str, object]] = {}

    def enumerate_profiles(self) -> tuple[ProfileEntry, ...]:
        self.events.append("enumerate")
        return tuple(self.entries)

    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
        profile_name = Path(argv[3]).name
        self.events.append(f"install:{profile_name}")
        worker = next(item for item in self.plan.workers if item.profile_name == profile_name)
        assert self.plan.staging_dir is not None
        source = self.plan.staging_dir / profile_name
        target = self.detection.profiles_root / profile_name
        shutil.copytree(source, target)
        distribution = yaml.safe_load((target / "distribution.yaml").read_text(encoding="utf-8"))
        distribution["source"] = str(source.resolve())
        (target / "distribution.yaml").write_text(
            yaml.safe_dump(distribution, sort_keys=False), encoding="utf-8"
        )
        self.distributions[worker.portable_id] = distribution
        self.entries.append(ProfileEntry(profile_name, target, ProfileEntryKind.PROFILE))
        return CommandOutcome(CommandStatus.SUCCEEDED, tuple(argv), 0)

    def set_description(
        self, worker: WorkerInstallPlan, *, env: Mapping[str, str]
    ) -> CommandOutcome:
        self.events.append(f"describe:{worker.profile_name}:{worker.description}")
        return CommandOutcome(CommandStatus.SUCCEEDED, ("description", worker.profile_name), 0)

    def read_distribution_info(
        self, worker: WorkerInstallPlan, *, env: Mapping[str, str]
    ) -> Mapping[str, object]:
        self.events.append(f"info:{worker.profile_name}")
        return self.distributions[worker.portable_id]

    def read_description(self, worker: WorkerInstallPlan, *, env: Mapping[str, str]) -> str:
        self.events.append(f"read-description:{worker.profile_name}")
        return worker.description

    def validate_collection(
        self,
        plan: InstallPlan,
        readbacks: tuple[InstalledProfileReadback, ...],
    ) -> tuple[InstalledProfileReadback, ...]:
        self.events.append("collection")
        return validate_readback_collection(plan, readbacks)


def test_each_profile_is_described_and_fully_read_back_before_next_install(tmp_path: Path) -> None:
    plan, detection = _plan(tmp_path)
    native = NativeAdapters(plan, detection)

    result = install_confirmed_plan(
        plan,
        executor=native,
        env={"HERMES_HOME": str(detection.hermes_home)},
        enumerate_profiles=native.enumerate_profiles,
        set_description=native.set_description,
        read_distribution_info=native.read_distribution_info,
        read_description=native.read_description,
        validate_collection=native.validate_collection,
    )

    first, second, third = (worker.profile_name for worker in plan.workers)
    assert result.status is InstallWorkflowStatus.SUCCEEDED
    assert len(result.confirmed_created) == 3
    assert len(result.verified_compensable) == 3
    assert native.events.index(f"read-description:{first}") < native.events.index(
        f"install:{second}"
    )
    assert native.events.index(
        f"describe:{first}:{plan.workers[0].description}"
    ) < native.events.index(f"info:{first}")
    assert native.events.index(f"read-description:{second}") < native.events.index(
        f"install:{third}"
    )
    assert native.events.index(f"read-description:{third}") < len(native.events) - 1
    assert native.events[-1] == "collection"


def test_description_failure_keeps_confirmed_without_marking_compensable(tmp_path: Path) -> None:
    plan, detection = _plan(tmp_path)
    native = NativeAdapters(plan, detection)

    def fail_description(worker: WorkerInstallPlan, *, env: Mapping[str, str]) -> CommandOutcome:
        native.events.append(f"describe-failed:{worker.profile_name}")
        return CommandOutcome(CommandStatus.FAILED, ("description", worker.profile_name), 9)

    result = install_confirmed_plan(
        plan,
        executor=native,
        env={},
        enumerate_profiles=native.enumerate_profiles,
        set_description=fail_description,
        read_distribution_info=native.read_distribution_info,
        read_description=native.read_description,
    )

    assert result.status is InstallWorkflowStatus.DESCRIPTION_FAILED
    assert [item.profile_name for item in result.confirmed_created] == [
        plan.workers[0].profile_name
    ]
    assert result.verified_compensable == ()
    assert sum(event.startswith("install:") for event in native.events) == 1


def test_description_baseexception_propagates_with_confirmed_state(tmp_path: Path) -> None:
    plan, detection = _plan(tmp_path)
    native = NativeAdapters(plan, detection)
    interrupted = KeyboardInterrupt("stop")

    def interrupt_description(
        worker: WorkerInstallPlan, *, env: Mapping[str, str]
    ) -> CommandOutcome:
        raise interrupted

    try:
        install_confirmed_plan(
            plan,
            executor=native,
            env={},
            enumerate_profiles=native.enumerate_profiles,
            set_description=interrupt_description,
            read_distribution_info=native.read_distribution_info,
            read_description=native.read_description,
        )
    except KeyboardInterrupt as raised:
        assert raised is interrupted
        state = raised.install_workflow_result  # type: ignore[attr-defined]
        assert state.status is InstallWorkflowStatus.DESCRIPTION_FAILED
        assert len(state.confirmed_created) == 1
        assert state.verified_compensable == ()
    else:
        raise AssertionError("KeyboardInterrupt was not propagated")


def test_second_attempt_failure_preserves_first_verified_readback(tmp_path: Path) -> None:
    plan, detection = _plan(tmp_path)
    native = NativeAdapters(plan, detection)
    install_calls = 0
    real_run = native.run

    def fail_second(argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
        nonlocal install_calls
        install_calls += 1
        if install_calls == 2:
            native.events.append(f"install-failed:{Path(argv[3]).name}")
            return CommandOutcome(CommandStatus.FAILED, tuple(argv), 4)
        return real_run(argv, env=env)

    class Executor:
        run = staticmethod(fail_second)

    result = install_confirmed_plan(
        plan,
        executor=Executor(),
        env={},
        enumerate_profiles=native.enumerate_profiles,
        set_description=native.set_description,
        read_distribution_info=native.read_distribution_info,
        read_description=native.read_description,
    )

    assert result.status is InstallWorkflowStatus.ATTEMPT_NO_REMNANT
    assert len(result.confirmed_created) == 1
    assert [item.worker for item in result.verified_compensable] == [plan.workers[0]]


def test_collection_failure_keeps_all_per_item_readbacks(tmp_path: Path) -> None:
    plan, detection = _plan(tmp_path)
    native = NativeAdapters(plan, detection)

    def fail_collection(
        plan: InstallPlan, readbacks: tuple[InstalledProfileReadback, ...]
    ) -> tuple[InstalledProfileReadback, ...]:
        raise RuntimeError("collection rejected")

    result = install_confirmed_plan(
        plan,
        executor=native,
        env={},
        enumerate_profiles=native.enumerate_profiles,
        set_description=native.set_description,
        read_distribution_info=native.read_distribution_info,
        read_description=native.read_description,
        validate_collection=fail_collection,
    )

    assert result.status is InstallWorkflowStatus.COLLECTION_FAILED
    assert len(result.confirmed_created) == 3
    assert len(result.verified_compensable) == 3
