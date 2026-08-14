from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import agentporter.hermes_runtime as hermes_runtime_module
from agentporter.hermes_runtime import HermesRuntime, RuntimeCommandError


def test_minimal_environment_preserves_explicit_hermes_home() -> None:
    assert HermesRuntime.minimal_environment(
        {"HOME": "/tmp/home", "HERMES_HOME": "/tmp/hermes", "API_KEY": "secret"}
    ) == {"HOME": "/tmp/home", "HERMES_HOME": "/tmp/hermes"}


def test_executable_drift_stops_before_runner(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    calls: list[object] = []
    adapter = HermesRuntime(executable, command_runner=lambda *a, **k: calls.append(a))  # type: ignore[arg-type]
    replacement = tmp_path / "replacement"
    replacement.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    replacement.chmod(0o755)
    replacement.replace(executable)
    with pytest.raises(RuntimeCommandError, match="runtime-authority-drift"):
        adapter.auth_status("worker", "provider")
    assert calls == []


def runtime(
    tmp_path: Path, calls: list[dict[str, object]], result: CompletedProcess[str]
) -> HermesRuntime:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    def runner(argv: tuple[str, ...], **kwargs: object) -> CompletedProcess[str]:
        calls.append({"argv": argv, **kwargs})
        return result

    return HermesRuntime(executable, command_runner=runner)


def oneshot_runtime(
    executable: Path,
    runner: Callable[..., CompletedProcess[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> HermesRuntime:
    def process_factory(argv: tuple[str, ...], **kwargs: object) -> object:
        class Process:
            pid = 1
            returncode = 0

            def communicate(
                self, input: str | None = None, timeout: float | None = None
            ) -> tuple[str, str]:
                del input, timeout
                result = runner(
                    argv,
                    env=kwargs["env"],
                    capture_output=True,
                    text=kwargs["text"],
                    check=False,
                )
                self.returncode = result.returncode
                return result.stdout, result.stderr

        return Process()

    monkeypatch.setattr(hermes_runtime_module, "Popen", process_factory)
    return HermesRuntime(executable)


def test_custom_process_factory_cannot_bypass_safe_spawn_contract(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    with pytest.raises(TypeError, match="process_factory"):
        HermesRuntime(
            executable,
            process_factory=lambda *_args, **_kwargs: None,  # type: ignore[call-arg]
        )


def test_auth_status_logged_out_exit_zero_is_not_authorized(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    adapter = runtime(tmp_path, calls, CompletedProcess([], 0, "No credentials configured", ""))
    result = adapter.auth_status("worker-one", "openai")
    assert result == "logged-out"
    assert calls[0]["argv"] == (
        str(adapter.executable),
        "-p",
        "worker-one",
        "auth",
        "status",
        "openai",
    )
    assert calls[0]["capture_output"] is True


def test_auth_add_uses_real_tty_and_never_api_key_argv(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    adapter = runtime(tmp_path, calls, CompletedProcess([], 0, "", ""))
    adapter.auth_add("worker-one", "openai")
    call = calls[0]
    assert call["argv"] == (str(adapter.executable), "-p", "worker-one", "auth", "add", "openai")
    assert call["capture_output"] is False
    argv = call["argv"]
    assert isinstance(argv, tuple)
    assert "--api-key" not in argv


def test_minimal_environment_drops_credentials_and_default_profile(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    adapter = runtime(tmp_path, calls, CompletedProcess([], 0, "logged in", ""))
    adapter.auth_status(
        "worker-one",
        "openai",
        source_env={
            "PATH": "/bin",
            "HOME": "/safe",
            "OPENAI_API_KEY": "secret",
            "HERMES_PROFILE": "default",
        },
    )
    assert calls[0]["env"] == {"HOME": "/safe", "PATH": "/bin"}


def test_oneshot_uses_explicit_route_nonce_private_usage_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    observed_usage: list[Path] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> CompletedProcess[str]:
        usage = Path(argv[argv.index("--usage-file") + 1])
        observed_usage.append(usage)
        assert usage.parent.stat().st_mode & 0o777 == 0o700
        nonce = argv[argv.index("-z") + 1].removeprefix("Reply exactly AGENTPORTER_READY:")
        usage.write_text(
            json.dumps(
                {"model": "m", "provider": "p", "api_calls": 1, "completed": True, "failed": False}
            ),
            encoding="utf-8",
        )
        calls.append({"argv": argv, **kwargs})
        return CompletedProcess(argv, 0, f"AGENTPORTER_READY:{nonce}\n", "")

    result = oneshot_runtime(executable, runner, monkeypatch).oneshot("worker-one", "m", "p")
    argv = calls[0]["argv"]
    assert isinstance(argv, tuple)
    assert argv[:3] == (str(executable.resolve()), "-p", "worker-one")
    assert (argv[argv.index("--model")], argv[argv.index("--model") + 1]) == ("--model", "m")
    assert (
        argv[argv.index("--provider")],
        argv[argv.index("--provider") + 1],
    ) == ("--provider", "p")
    assert result.actual_model == "m" and result.actual_provider == "p" and result.api_calls == 1
    assert result.tool_calls is None and result.fallback_used is None
    assert observed_usage and not observed_usage[0].parent.exists()


def test_oneshot_uses_probe_owned_nonce_when_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    def runner(argv: tuple[str, ...], **kwargs: object) -> CompletedProcess[str]:
        usage = Path(argv[argv.index("--usage-file") + 1])
        usage.write_text(
            json.dumps(
                {"model": "m", "provider": "p", "api_calls": 1, "completed": True, "failed": False}
            ),
            encoding="utf-8",
        )
        calls.append({"argv": argv, **kwargs})
        return CompletedProcess(argv, 0, "AGENTPORTER_READY:owned-nonce\n", "")

    oneshot_runtime(executable, runner, monkeypatch).oneshot(
        "worker", "m", "p", nonce="owned-nonce"
    )
    argv = calls[0]["argv"]
    assert isinstance(argv, tuple)
    assert argv[argv.index("-z") + 1] == "Reply exactly AGENTPORTER_READY:owned-nonce"


def test_oneshot_wrapped_runner_cannot_bypass_process_tree_reaping(tmp_path: Path) -> None:
    executable = tmp_path / "hermes"
    child_marker = tmp_path / "child-finished"
    executable.write_text(
        f"#!/bin/sh\n(sleep 1; printf finished > '{child_marker}') &\nsleep 30\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)

    def wrapped_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return subprocess.run(*args, **kwargs)  # type: ignore[call-overload]

    adapter = HermesRuntime(executable, command_runner=wrapped_runner, timeout_seconds=0.1)
    with pytest.raises(RuntimeCommandError, match="probe-timeout"):
        adapter.oneshot(
            "worker",
            "m",
            "p",
            source_env={"PATH": "/bin:/usr/bin", "CHILD_MARKER": str(child_marker)},
        )

    time.sleep(1.2)
    assert not child_marker.exists()


def test_oneshot_killpg_lookup_race_remains_probe_timeout_and_reaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    timeout = subprocess.TimeoutExpired([str(executable)], 0.1)

    class RacingProcess:
        pid = 12345
        returncode = 0
        communicate_calls = 0

        def communicate(
            self, input: str | None = None, timeout: float | None = None
        ) -> tuple[str, str]:
            self.communicate_calls += 1
            if timeout is not None:
                raise subprocess.TimeoutExpired([str(executable)], timeout)
            return "", ""

    process = RacingProcess()
    factory_calls: list[dict[str, object]] = []

    def process_factory(argv: tuple[str, ...], **kwargs: object) -> RacingProcess:
        factory_calls.append({"argv": argv, **kwargs})
        return process

    def raced_killpg(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", raced_killpg)
    monkeypatch.setattr(hermes_runtime_module, "Popen", process_factory)
    adapter = HermesRuntime(executable, timeout_seconds=timeout.timeout)

    with pytest.raises(RuntimeCommandError) as caught:
        adapter.oneshot("worker", "m", "p")

    assert caught.value.reason == "probe-timeout"
    assert process.communicate_calls == 2
    assert factory_calls[0]["start_new_session"] is True


def test_oneshot_killpg_permission_and_reap_errors_still_fallback_to_kill_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    class UncooperativeProcess:
        pid = 12345
        returncode = None
        communicate_calls = 0
        kill_calls = 0

        def communicate(
            self, input: str | None = None, timeout: float | None = None
        ) -> tuple[str, str]:
            del input
            self.communicate_calls += 1
            if timeout is not None:
                raise subprocess.TimeoutExpired([str(executable)], timeout)
            raise OSError("reap failed")

        def kill(self) -> None:
            self.kill_calls += 1

    process = UncooperativeProcess()

    def denied_killpg(_pid: int, _signal: int) -> None:
        raise PermissionError("group signal denied")

    def fake_popen(*_args: object, **_kwargs: object) -> UncooperativeProcess:
        return process

    monkeypatch.setattr(hermes_runtime_module, "Popen", fake_popen)
    monkeypatch.setattr(os, "killpg", denied_killpg)

    with pytest.raises(RuntimeCommandError) as caught:
        HermesRuntime(executable, timeout_seconds=0.1).oneshot("worker", "m", "p")

    assert caught.value.reason == "probe-timeout"
    assert process.kill_calls == 1
    assert process.communicate_calls == 2


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("401 unauthorized", "authentication-failed"),
        ("429 too many", "rate-limited"),
        ("model not found", "model-unsupported"),
        ("connection refused", "endpoint-unavailable"),
    ],
)
def test_oneshot_errors_are_safely_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str, reason: str
) -> None:
    calls: list[dict[str, object]] = []
    adapter = runtime(tmp_path, calls, CompletedProcess([], 1, "", stderr + " RAW_SECRET"))
    adapter = oneshot_runtime(adapter.executable, adapter.command_runner, monkeypatch)
    with pytest.raises(RuntimeCommandError) as caught:
        adapter.oneshot("worker", "m", "p")
    assert caught.value.reason == reason
    assert "RAW_SECRET" not in str(caught.value)


def test_missing_or_malformed_usage_is_invalid_and_cleanup_is_unconditional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    parents: list[Path] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> CompletedProcess[str]:
        usage = Path(argv[argv.index("--usage-file") + 1])
        parents.append(usage.parent)
        usage.write_text("{broken", encoding="utf-8")
        return CompletedProcess(argv, 0, "irrelevant", "")

    with pytest.raises(RuntimeCommandError) as caught:
        oneshot_runtime(executable, runner, monkeypatch).oneshot("worker", "m", "p")
    assert caught.value.reason == "usage-evidence-invalid"
    assert not parents[0].exists()


def test_named_custom_provider_accepts_only_canonical_custom_usage_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    def runner(argv: tuple[str, ...], **_kwargs: object) -> CompletedProcess[str]:
        usage = Path(argv[argv.index("--usage-file") + 1])
        usage.write_text(
            json.dumps(
                {
                    "model": "m",
                    "provider": "custom",
                    "api_calls": 1,
                    "completed": True,
                    "failed": False,
                }
            ),
            encoding="utf-8",
        )
        return CompletedProcess(argv, 0, "AGENTPORTER_READY:n\n", "")

    result = oneshot_runtime(executable, runner, monkeypatch).oneshot(
        "worker", "m", "MySub2API GPT", nonce="n", expected_usage_provider="custom"
    )
    assert result.actual_provider == "MySub2API GPT"


def test_exit_zero_with_failed_usage_is_classified_from_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    def runner(argv: tuple[str, ...], **_kwargs: object) -> CompletedProcess[str]:
        usage = Path(argv[argv.index("--usage-file") + 1])
        usage.write_text(
            json.dumps(
                {
                    "model": "m",
                    "provider": "custom",
                    "api_calls": 1,
                    "completed": True,
                    "failed": True,
                    "error": "401 unauthorized",
                }
            ),
            encoding="utf-8",
        )
        return CompletedProcess(argv, 0, "", "")

    with pytest.raises(RuntimeCommandError) as caught:
        oneshot_runtime(executable, runner, monkeypatch).oneshot(
            "worker", "m", "named", expected_usage_provider="custom"
        )
    assert caught.value.reason == "authentication-failed"


def test_usage_file_must_be_exclusively_created_by_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    def runner(argv: tuple[str, ...], **_kwargs: object) -> CompletedProcess[str]:
        usage = Path(argv[argv.index("--usage-file") + 1])
        assert usage.is_file()
        usage.write_text(
            json.dumps(
                {"model": "m", "provider": "p", "api_calls": 1, "completed": True, "failed": False}
            ),
            encoding="utf-8",
        )
        return CompletedProcess(argv, 0, "AGENTPORTER_READY:n\n", "")

    oneshot_runtime(executable, runner, monkeypatch).oneshot("worker", "m", "p", nonce="n")


def test_executable_must_be_absolute_regular_executable(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        HermesRuntime(Path("hermes"))
    directory = tmp_path / "hermes"
    directory.mkdir()
    with pytest.raises(ValueError):
        HermesRuntime(directory)
