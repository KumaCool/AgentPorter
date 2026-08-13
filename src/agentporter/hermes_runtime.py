"""Hermes public-CLI auth and one-shot adapter with secret-safe evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .runtime_probe import ProbeObservation

RuntimeFailureReason = Literal[
    "runtime-authority-drift",
    "authentication-failed",
    "model-unsupported",
    "endpoint-unavailable",
    "rate-limited",
    "probe-timeout",
    "response-contract-failed",
    "usage-evidence-invalid",
    "unexpected-runtime-route",
]
AuthStatus = Literal["logged-in", "logged-out", "unknown"]
_MAX_EVIDENCE = 1024 * 1024


class RuntimeCommandError(RuntimeError):
    def __init__(self, reason: RuntimeFailureReason) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class HermesRuntime:
    executable: Path
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    timeout_seconds: float = 30.0
    _identity: tuple[int, int, int, str] | None = None

    def __post_init__(self) -> None:
        if not self.executable.is_absolute():
            raise ValueError("Hermes executable must be absolute")
        resolved = self.executable.resolve(strict=True)
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
            raise ValueError("Hermes executable must be a regular executable")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "executable", resolved)
        object.__setattr__(self, "_identity", self._read_identity(resolved))

    @staticmethod
    def _read_identity(path: Path) -> tuple[int, int, int, str]:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("not a regular executable")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 65536):
                digest.update(chunk)
            rebound = path.stat(follow_symlinks=False)
            if (rebound.st_dev, rebound.st_ino) != (info.st_dev, info.st_ino):
                raise OSError("executable changed")
            return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), digest.hexdigest()
        finally:
            os.close(descriptor)

    def _revalidate(self) -> None:
        try:
            current = self._read_identity(self.executable)
            target = self.executable.resolve(strict=True)
        except OSError as error:
            raise RuntimeCommandError("runtime-authority-drift") from error
        if target != self.executable or current != self._identity:
            raise RuntimeCommandError("runtime-authority-drift")

    @staticmethod
    def minimal_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
        values = os.environ if source is None else source
        return {
            key: values[key]
            for key in ("HOME", "HERMES_HOME", "PATH", "LANG", "LC_ALL", "TERM")
            if key in values
        }

    def _argv(self, profile: str, *parts: str) -> tuple[str, ...]:
        if not profile.strip() or any(not part.strip() for part in parts):
            raise ValueError("CLI values must be non-empty")
        return (str(self.executable), "-p", profile, *parts)

    def auth_status(
        self, profile: str, provider: str, *, source_env: Mapping[str, str] | None = None
    ) -> AuthStatus:
        self._revalidate()
        completed = self.command_runner(
            self._argv(profile, "auth", "status", provider),
            env=self.minimal_environment(source_env),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        text = completed.stdout.lower()[:8192]
        if any(
            marker in text for marker in ("no credentials", "not logged", "logged out", "missing")
        ):
            return "logged-out"
        if completed.returncode == 0 and any(
            marker in text for marker in ("logged in", "configured", "authenticated")
        ):
            return "logged-in"
        return "unknown"

    def auth_add(
        self, profile: str, provider: str, *, source_env: Mapping[str, str] | None = None
    ) -> None:
        self._revalidate()
        completed = self.command_runner(
            self._argv(profile, "auth", "add", provider),
            env=self.minimal_environment(source_env),
            capture_output=False,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeCommandError("authentication-failed")

    def oneshot(
        self,
        profile: str,
        model: str,
        provider: str,
        *,
        source_env: Mapping[str, str] | None = None,
        nonce: str | None = None,
    ) -> ProbeObservation:
        nonce = os.urandom(16).hex() if nonce is None else nonce
        if not nonce or len(nonce) > 128 or not nonce.isascii():
            raise ValueError("nonce must be bounded ASCII")
        with tempfile.TemporaryDirectory(prefix="agentporter-hermes-") as raw:
            directory = Path(raw)
            directory.chmod(0o700)
            usage = directory / "usage.json"
            usage_fd = os.open(usage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            usage_identity = os.fstat(usage_fd)
            os.close(usage_fd)
            prompt = f"Reply exactly AGENTPORTER_READY:{nonce}"
            argv = self._argv(
                profile,
                "-z",
                prompt,
                "--model",
                model,
                "--provider",
                provider,
                "--usage-file",
                str(usage),
            )
            try:
                self._revalidate()
                completed = self.command_runner(
                    argv,
                    env=self.minimal_environment(source_env),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeCommandError("probe-timeout") from error
            if completed.returncode != 0:
                raise RuntimeCommandError(_classify_text(completed.stderr[:8192]))
            evidence = _read_usage(
                usage, expected_identity=(usage_identity.st_dev, usage_identity.st_ino)
            )
            actual_model = evidence.get("model")
            actual_provider = evidence.get("provider")
            api_calls = evidence.get("api_calls")
            if (
                not isinstance(actual_model, str)
                or not isinstance(actual_provider, str)
                or type(api_calls) is not int
                or evidence.get("completed") is not True
                or evidence.get("failed") is not False
            ):
                raise RuntimeCommandError("usage-evidence-invalid")
            output = completed.stdout.strip()
            if output != f"AGENTPORTER_READY:{nonce}":
                raise RuntimeCommandError("response-contract-failed")
            if actual_model != model or actual_provider != provider:
                raise RuntimeCommandError("unexpected-runtime-route")
            tool_calls = evidence.get("tool_calls")
            fallback = evidence.get("fallback_used")
            if tool_calls is not None and type(tool_calls) is not int:
                raise RuntimeCommandError("usage-evidence-invalid")
            if fallback is not None and type(fallback) is not bool:
                raise RuntimeCommandError("usage-evidence-invalid")
            return ProbeObservation(
                output=output,
                actual_model=actual_model,
                actual_provider=actual_provider,
                api_calls=api_calls,
                tool_calls=tool_calls,
                fallback_used=fallback,
            )


def _read_usage(path: Path, *, expected_identity: tuple[int, int] | None = None) -> dict[str, Any]:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_size > _MAX_EVIDENCE
        ):
            raise RuntimeCommandError("usage-evidence-invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (
                expected_identity is not None
                and (opened.st_dev, opened.st_ino) != expected_identity
            ):
                raise RuntimeCommandError("usage-evidence-invalid")
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise RuntimeCommandError("usage-evidence-invalid")
            payload = os.read(descriptor, _MAX_EVIDENCE + 1)
        finally:
            os.close(descriptor)
        if len(payload) > _MAX_EVIDENCE:
            raise RuntimeCommandError("usage-evidence-invalid")
        loaded: object = json.loads(payload)
        if not isinstance(loaded, dict):
            raise RuntimeCommandError("usage-evidence-invalid")
        return cast(dict[str, Any], loaded)
    except RuntimeCommandError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeCommandError("usage-evidence-invalid") from error


def _classify_text(stderr: str) -> RuntimeFailureReason:
    lowered = stderr.lower()
    if re.search(r"\b(401|403|unauthori[sz]ed|authentication|api key)\b", lowered):
        return "authentication-failed"
    if re.search(r"\b429\b|rate.?limit|too many", lowered):
        return "rate-limited"
    if "model" in lowered and any(
        word in lowered for word in ("not found", "unsupported", "invalid")
    ):
        return "model-unsupported"
    if any(word in lowered for word in ("connection", "endpoint", "dns", "502", "503")):
        return "endpoint-unavailable"
    return "response-contract-failed"
