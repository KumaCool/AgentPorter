from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

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


def test_oneshot_uses_explicit_route_nonce_private_usage_and_cleans(tmp_path: Path) -> None:
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

    result = HermesRuntime(executable, command_runner=runner).oneshot("worker-one", "m", "p")
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


def test_oneshot_uses_probe_owned_nonce_when_supplied(tmp_path: Path) -> None:
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

    HermesRuntime(executable, command_runner=runner).oneshot(
        "worker", "m", "p", nonce="owned-nonce"
    )
    argv = calls[0]["argv"]
    assert isinstance(argv, tuple)
    assert argv[argv.index("-z") + 1] == "Reply exactly AGENTPORTER_READY:owned-nonce"


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("401 unauthorized", "authentication-failed"),
        ("429 too many", "rate-limited"),
        ("model not found", "model-unsupported"),
        ("connection refused", "endpoint-unavailable"),
    ],
)
def test_oneshot_errors_are_safely_classified(tmp_path: Path, stderr: str, reason: str) -> None:
    calls: list[dict[str, object]] = []
    adapter = runtime(tmp_path, calls, CompletedProcess([], 1, "", stderr + " RAW_SECRET"))
    with pytest.raises(RuntimeCommandError) as caught:
        adapter.oneshot("worker", "m", "p")
    assert caught.value.reason == reason
    assert "RAW_SECRET" not in str(caught.value)


def test_missing_or_malformed_usage_is_invalid_and_cleanup_is_unconditional(tmp_path: Path) -> None:
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
        HermesRuntime(executable, command_runner=runner).oneshot("worker", "m", "p")
    assert caught.value.reason == "usage-evidence-invalid"
    assert not parents[0].exists()


def test_usage_file_must_be_exclusively_created_by_runtime(tmp_path: Path) -> None:
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

    HermesRuntime(executable, command_runner=runner).oneshot("worker", "m", "p", nonce="n")


def test_executable_must_be_absolute_regular_executable(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        HermesRuntime(Path("hermes"))
    directory = tmp_path / "hermes"
    directory.mkdir()
    with pytest.raises(ValueError):
        HermesRuntime(directory)
