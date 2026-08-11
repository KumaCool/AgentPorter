from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence

import pytest

from agentporter.execution import CommandExecutor, CommandStatus


class RunnerSpy:
    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        self.calls: list[tuple[Sequence[str], dict[str, object]]] = []

    def __call__(self, argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        return self.result


def test_executor_passes_argv_without_shell_joining_and_uses_safe_options() -> None:
    result = subprocess.CompletedProcess(["tool"], 0, stdout="ok", stderr="")
    runner = RunnerSpy(result)
    executor = CommandExecutor(runner=runner, timeout_seconds=12.5)
    argv = ["tool", "literal; rm -rf /", "$(not-executed)"]
    env: Mapping[str, str] = {"SAFE": "value"}

    outcome = executor.run(argv, env=env)

    assert outcome.status is CommandStatus.SUCCEEDED
    assert outcome.argv == tuple(argv)
    assert outcome.returncode == 0
    assert outcome.stdout == "ok"
    assert runner.calls == [
        (
            argv,
            {
                "shell": False,
                "env": env,
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 12.5,
            },
        )
    ]
    assert runner.calls[0][0][1] == "literal; rm -rf /"


def test_executor_normalizes_nonzero_exit() -> None:
    runner = RunnerSpy(
        subprocess.CompletedProcess(["tool", "arg"], 7, stdout="partial", stderr="failed")
    )

    outcome = CommandExecutor(runner=runner).run(["tool", "arg"], env={})

    assert outcome.status is CommandStatus.FAILED
    assert outcome.returncode == 7
    assert outcome.stdout == "partial"
    assert outcome.stderr == "failed"


def test_executor_normalizes_timeout_with_partial_output() -> None:
    def runner(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="partial", stderr="slow")

    outcome = CommandExecutor(runner=runner, timeout_seconds=1).run(["tool"], env={})

    assert outcome.status is CommandStatus.TIMED_OUT
    assert outcome.returncode is None
    assert outcome.stdout == "partial"
    assert outcome.stderr == "slow"


def test_executor_normalizes_keyboard_interrupt() -> None:
    def runner(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise KeyboardInterrupt

    outcome = CommandExecutor(runner=runner).run(["tool"], env={})

    assert outcome.status is CommandStatus.INTERRUPTED
    assert outcome.returncode is None


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_executor_rejects_unbounded_or_nonpositive_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        CommandExecutor(timeout_seconds=timeout)


@pytest.mark.parametrize("argv", [[], ["tool", ""], ["tool", 1]])
def test_executor_rejects_invalid_argv(argv: list[object]) -> None:
    runner = RunnerSpy(subprocess.CompletedProcess(["tool"], 0, stdout="", stderr=""))

    with pytest.raises((TypeError, ValueError)):
        CommandExecutor(runner=runner).run(argv, env={})  # type: ignore[arg-type]

    assert runner.calls == []


def test_executor_rejects_string_command_api() -> None:
    runner = RunnerSpy(subprocess.CompletedProcess(["tool"], 0, stdout="", stderr=""))

    with pytest.raises(TypeError, match="argv must be a sequence"):
        CommandExecutor(runner=runner).run("tool --danger", env={})

    assert runner.calls == []


def test_executor_requires_explicit_environment_mapping() -> None:
    runner = RunnerSpy(subprocess.CompletedProcess(["tool"], 0, stdout="", stderr=""))

    with pytest.raises(TypeError, match="env must be a mapping"):
        CommandExecutor(runner=runner).run(["tool"], env=None)  # type: ignore[arg-type]

    assert runner.calls == []
