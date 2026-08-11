from __future__ import annotations

import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

Runner = Callable[..., subprocess.CompletedProcess[str]]


class CommandStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class CommandOutcome:
    status: CommandStatus
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str | None = None
    stderr: str | None = None


class CommandExecutor:
    def __init__(
        self,
        *,
        runner: Runner = subprocess.run,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout must be finite and positive")
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def run(self, argv: Sequence[str], *, env: Mapping[str, str]) -> CommandOutcome:
        raw_argv = cast(object, argv)
        raw_env = cast(object, env)
        if isinstance(raw_argv, (str, bytes)):
            raise TypeError("argv must be a sequence of strings, not a command string")
        if not argv:
            raise ValueError("argv must not be empty")
        if any(not isinstance(argument, str) for argument in cast(Sequence[object], argv)):
            raise TypeError("every argv element must be a string")
        if any(not argument for argument in argv):
            raise ValueError("argv elements must not be empty")
        if not isinstance(raw_env, Mapping):
            raise TypeError("env must be a mapping")

        normalized_argv = tuple(argv)
        try:
            completed = self._runner(
                argv,
                shell=False,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            return CommandOutcome(
                status=CommandStatus.TIMED_OUT,
                argv=normalized_argv,
                returncode=None,
                stdout=_text(error.output),
                stderr=_text(error.stderr),
            )
        except KeyboardInterrupt:
            return CommandOutcome(
                status=CommandStatus.INTERRUPTED,
                argv=normalized_argv,
                returncode=None,
            )

        status = CommandStatus.SUCCEEDED if completed.returncode == 0 else CommandStatus.FAILED
        return CommandOutcome(
            status=status,
            argv=normalized_argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)
