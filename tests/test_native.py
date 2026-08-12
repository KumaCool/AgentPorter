from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from agentporter.execution import CommandExecutor, CommandStatus
from agentporter.hermes import (
    HermesCapabilities,
    HermesDetection,
    ProfileEntryKind,
)
from agentporter.native import NativeError, NativeHermesAdapter


class RecordingRunner:
    def __init__(self, responses: list[subprocess.CompletedProcess[str] | BaseException]) -> None:
        self.responses = responses
        self.calls: list[tuple[Sequence[str], dict[str, object]]] = []

    def __call__(self, argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["hermes"], returncode, stdout, stderr)


def detection(tmp_path: Path) -> HermesDetection:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    required = frozenset({"install", "delete", "describe", "list", "info"})
    return HermesDetection(
        executable=executable,
        version="0.20.0",
        hermes_home=home,
        profiles_root=profiles,
        capabilities=HermesCapabilities(required, frozenset()),
        profile_entries=(),
    )


def adapter(
    tmp_path: Path, responses: list[subprocess.CompletedProcess[str] | BaseException]
) -> tuple[NativeHermesAdapter, RecordingRunner, HermesDetection, Mapping[str, str]]:
    found = detection(tmp_path)
    runner = RecordingRunner(responses)
    env = {
        "HOME": str(tmp_path / "user"),
        "HERMES_HOME": str(found.hermes_home),
        "MODEL_API_KEY": "",
    }
    native = NativeHermesAdapter(CommandExecutor(runner=runner, timeout_seconds=2), env, found)
    return native, runner, found, env


@dataclass(frozen=True)
class WorkerStub:
    profile_name: str = "porter-review"
    description: str = "Review: exact text with spaces"


@dataclass(frozen=True)
class PlanStub:
    staging_dir: Path | None


def worker() -> WorkerStub:
    return WorkerStub()


def plan(staging: Path) -> PlanStub:
    return PlanStub(staging_dir=staging)


def assert_safe_call(
    runner: RecordingRunner, expected: tuple[str, ...], env: Mapping[str, str]
) -> None:
    argv, options = runner.calls[-1]
    assert tuple(argv) == expected
    assert options == {
        "shell": False,
        "env": env,
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 2,
    }


def test_install_uses_v020_exact_source_yes_argv_without_alias_force_or_name(
    tmp_path: Path,
) -> None:
    native, runner, found, env = adapter(tmp_path, [completed()])
    staging = tmp_path / "stage with spaces"

    outcome = native.install(worker(), plan(staging))

    assert outcome.status is CommandStatus.SUCCEEDED
    assert_safe_call(
        runner,
        (str(found.executable), "profile", "install", str(staging / "porter-review"), "--yes"),
        env,
    )
    assert not {"--alias", "--force", "--name"} & set(outcome.argv)


@pytest.mark.parametrize(
    ("force_config", "expected_tail"),
    [(False, ("--yes",)), (True, ("--force-config", "--yes"))],
)
def test_update_uses_v020_distribution_semantics(
    tmp_path: Path, force_config: bool, expected_tail: tuple[str, ...]
) -> None:
    native, runner, found, env = adapter(tmp_path, [completed()])

    outcome = native.update("porter-review", force_config=force_config)

    assert outcome.status is CommandStatus.SUCCEEDED
    assert_safe_call(
        runner,
        (str(found.executable), "profile", "update", "porter-review", *expected_tail),
        env,
    )


def test_actual_v020_distribution_update_preserves_config_and_local_receipt(
    tmp_path: Path,
) -> None:
    executable_value = shutil.which("hermes")
    if executable_value is None:
        pytest.skip("Hermes CLI is unavailable")
    executable = Path(executable_value).resolve()
    home = tmp_path / "hermes-home"
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    source = tmp_path / "distribution" / "phase-b-fixture"
    source.mkdir(parents=True)
    (source / "distribution.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "phase-b-fixture",
                "version": "1.0.0",
                "description": "Phase B lifecycle fixture",
                "distribution_owned": ["SOUL.md", "config.yaml"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source / "SOUL.md").write_text("version one\n", encoding="utf-8")
    (source / "config.yaml").write_text("model:\n  default: fixture-v1\n", encoding="utf-8")
    env = {
        "HOME": str(tmp_path / "user"),
        "HERMES_HOME": str(home),
        "PATH": os.environ["PATH"],
    }
    found = HermesDetection(
        executable,
        "0.20.0",
        home,
        profiles,
        HermesCapabilities(frozenset({"install", "update"}), frozenset()),
        (),
    )
    native = NativeHermesAdapter(CommandExecutor(timeout_seconds=20), env, found)
    installed = native.install(WorkerStub(profile_name="phase-b-fixture"), PlanStub(source.parent))
    assert installed.status is CommandStatus.SUCCEEDED
    profile = profiles / "phase-b-fixture"
    config = profile / "config.yaml"
    config.write_text("model:\n  default: operator-value\n", encoding="utf-8")
    receipt = profile / "local" / "agentporter" / "runtime-binding.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"fixture":true}\n', encoding="utf-8")
    (source / "SOUL.md").write_text("version two\n", encoding="utf-8")
    (source / "config.yaml").write_text("model:\n  default: fixture-v2\n", encoding="utf-8")

    assert native.update("phase-b-fixture").status is CommandStatus.SUCCEEDED
    assert config.read_text() == "model:\n  default: operator-value\n"
    assert receipt.read_text() == '{"fixture":true}\n'
    assert (profile / "SOUL.md").read_text() == "version two\n"
    assert native.update("phase-b-fixture", force_config=True).status is CommandStatus.SUCCEEDED
    assert config.read_text() == "model:\n  default: fixture-v2\n"
    assert receipt.read_text() == '{"fixture":true}\n'


def test_install_preserves_nonzero_and_timeout_as_command_outcomes(tmp_path: Path) -> None:
    timeout = subprocess.TimeoutExpired(["hermes"], 2, output="partial", stderr="slow")
    native, _, _, _ = adapter(tmp_path, [completed(7, "partial", "failed"), timeout])

    failed = native.install(worker(), plan(tmp_path / "stage"))
    timed_out = native.install(worker(), plan(tmp_path / "stage"))

    assert (failed.status, failed.returncode) == (CommandStatus.FAILED, 7)
    assert (timed_out.status, timed_out.returncode) == (CommandStatus.TIMED_OUT, None)


def test_set_description_uses_exact_text_and_never_auto(tmp_path: Path) -> None:
    native, runner, found, env = adapter(tmp_path, [completed()])

    outcome = native.set_description(worker())

    assert outcome.status is CommandStatus.SUCCEEDED
    assert_safe_call(
        runner,
        (
            str(found.executable),
            "profile",
            "describe",
            "porter-review",
            "--text",
            "Review: exact text with spaces",
        ),
        env,
    )
    assert "--auto" not in outcome.argv


def test_explicit_method_env_must_equal_sealed_adapter_environment(tmp_path: Path) -> None:
    native, runner, _, env = adapter(tmp_path, [completed()])

    native.set_description(worker(), env=env)
    with pytest.raises(NativeError, match="environment"):
        native.set_description(worker(), env={**env, "EXTRA": "changed"})

    assert len(runner.calls) == 1


def test_read_description_returns_single_exact_line_without_cli_newline(tmp_path: Path) -> None:
    native, runner, found, env = adapter(
        tmp_path, [completed(stdout="Review: exact text with spaces\n")]
    )

    result = native.read_description(worker())

    assert result == "Review: exact text with spaces"
    assert_safe_call(runner, (str(found.executable), "profile", "describe", "porter-review"), env)


@pytest.mark.parametrize(
    "stdout",
    ["[auto] generated\n", "first\nsecond\n", "description\nextra: line\n", "", "\n"],
)
def test_read_description_rejects_auto_empty_or_extra_output(tmp_path: Path, stdout: str) -> None:
    native, _, _, _ = adapter(tmp_path, [completed(stdout=stdout)])

    with pytest.raises(NativeError, match="description"):
        native.read_description(worker())


def test_read_description_maps_command_failure_without_leaking_output(tmp_path: Path) -> None:
    secret = "secret-output-must-not-leak"
    native, _, _, _ = adapter(tmp_path, [completed(9, secret, secret)])

    with pytest.raises(NativeError) as raised:
        native.read_description(worker())

    assert secret not in str(raised.value)
    assert raised.value.status is CommandStatus.FAILED


def test_info_attests_natively_then_descriptor_reads_distribution_mapping(tmp_path: Path) -> None:
    native, runner, found, env = adapter(
        tmp_path,
        [completed(stdout="Name: porter-review\nSource: /tmp/source: with colon and spaces\n")],
    )
    profile = found.profiles_root / "porter-review"
    profile.mkdir()
    expected = {
        "name": "porter-review",
        "description": "Review: exact text with spaces",
        "source": "/tmp/source: with colon and spaces",
        "distribution_owned": ["SOUL.md"],
    }
    (profile / "distribution.yaml").write_text(yaml.safe_dump(expected), encoding="utf-8")

    result = native.read_distribution_info(worker())

    assert result == expected
    assert_safe_call(runner, (str(found.executable), "profile", "info", "porter-review"), env)


def test_info_rejects_nonzero_timeout_and_does_not_read_file(tmp_path: Path) -> None:
    timeout = subprocess.TimeoutExpired(["hermes"], 2)
    native, _, found, _ = adapter(tmp_path, [completed(4, "private", "private"), timeout])
    profile = found.profiles_root / "porter-review"
    profile.mkdir()
    manifest = profile / "distribution.yaml"
    manifest.write_text("name: porter-review\n", encoding="utf-8")

    with pytest.raises(NativeError) as failed:
        native.read_distribution_info(worker())
    manifest.unlink()
    with pytest.raises(NativeError) as timed_out:
        native.read_distribution_info(worker())

    assert failed.value.status is CommandStatus.FAILED
    assert timed_out.value.status is CommandStatus.TIMED_OUT
    assert "private" not in str(failed.value)


@pytest.mark.parametrize("unsafe", ["profile-symlink", "manifest-symlink", "non-mapping"])
def test_info_fails_closed_for_unsafe_or_invalid_distribution(tmp_path: Path, unsafe: str) -> None:
    native, _, found, _ = adapter(tmp_path, [completed()])
    real = tmp_path / "real"
    real.mkdir()
    (real / "distribution.yaml").write_text("name: porter-review\n", encoding="utf-8")
    profile = found.profiles_root / "porter-review"
    if unsafe == "profile-symlink":
        profile.symlink_to(real, target_is_directory=True)
    else:
        profile.mkdir()
        manifest = profile / "distribution.yaml"
        if unsafe == "manifest-symlink":
            manifest.symlink_to(real / "distribution.yaml")
        else:
            manifest.write_text("- not\n- a mapping\n", encoding="utf-8")

    with pytest.raises(NativeError, match="distribution"):
        native.read_distribution_info(worker())


def test_enumerate_profiles_is_read_only_sorted_and_classifies_unsafe_entries(
    tmp_path: Path,
) -> None:
    native, runner, found, _ = adapter(tmp_path, [])
    (found.profiles_root / "zeta").mkdir()
    (found.profiles_root / "plain").write_text("x", encoding="utf-8")
    (found.profiles_root / "linked").symlink_to(found.profiles_root / "zeta")
    (found.profiles_root / "alpha").mkdir()

    entries = native.enumerate_profiles()

    assert [(entry.name, entry.kind) for entry in entries] == [
        ("alpha", ProfileEntryKind.PROFILE),
        ("linked", ProfileEntryKind.SYMLINK),
        ("plain", ProfileEntryKind.NON_DIRECTORY),
        ("zeta", ProfileEntryKind.PROFILE),
    ]
    assert all(entry.path == found.profiles_root / entry.name for entry in entries)
    assert runner.calls == []


def test_enumerate_profiles_rejects_symlink_root_without_commands(tmp_path: Path) -> None:
    native, runner, found, _ = adapter(tmp_path, [])
    found.profiles_root.rmdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    found.profiles_root.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(NativeError, match="profiles root"):
        native.enumerate_profiles()

    assert runner.calls == []


def test_delete_uses_exact_yes_argv_without_force_or_alias(tmp_path: Path) -> None:
    native, runner, found, env = adapter(tmp_path, [completed()])

    outcome = native.delete("porter-review")

    assert outcome.status is CommandStatus.SUCCEEDED
    assert_safe_call(
        runner, (str(found.executable), "profile", "delete", "porter-review", "--yes"), env
    )
    assert "--force" not in outcome.argv and "--alias" not in outcome.argv


@pytest.mark.parametrize("name", ["default", "../escape", "nested/name", "", "UPPER"])
def test_native_operations_reject_nonportable_or_reserved_names_without_commands(
    tmp_path: Path, name: str
) -> None:
    native, runner, _, _ = adapter(tmp_path, [])
    unsafe_worker = WorkerStub(profile_name=name, description="description")

    with pytest.raises(NativeError, match="profile name"):
        native.set_description(unsafe_worker)
    with pytest.raises(NativeError, match="profile name"):
        native.delete(name)

    assert runner.calls == []


def test_constructor_rejects_noncanonical_or_mismatched_environment(tmp_path: Path) -> None:
    found = detection(tmp_path)
    executor = CommandExecutor(runner=RecordingRunner([]))

    with pytest.raises(NativeError, match="HERMES_HOME"):
        NativeHermesAdapter(executor, {"HERMES_HOME": str(tmp_path / "other")}, found)


def test_info_uses_no_path_open_following_for_profile_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, _, found, _ = adapter(tmp_path, [completed()])
    profile = found.profiles_root / "porter-review"
    profile.mkdir()
    (profile / "distribution.yaml").write_text("name: porter-review\n", encoding="utf-8")
    observed_flags: list[int] = []
    real_open = os.open

    def recording_open(
        path: str | bytes | Path, flags: int, *args: object, **kwargs: object
    ) -> int:
        observed_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)

    assert native.read_distribution_info(worker())["name"] == "porter-review"
    assert len(observed_flags) >= 3
    assert all(flags & os.O_NOFOLLOW for flags in observed_flags)
