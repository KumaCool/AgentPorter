from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Never, Protocol, cast

import yaml

from .execution import CommandExecutor, CommandOutcome, CommandStatus
from .hermes import HermesDetection, ProfileEntry, ProfileEntryKind
from .models import HermesProfileName


class _Worker(Protocol):
    @property
    def profile_name(self) -> str: ...

    @property
    def description(self) -> str: ...


class _Plan(Protocol):
    @property
    def staging_dir(self) -> Path | None: ...


class NativeError(RuntimeError):
    """A Hermes-native operation or its readback could not be trusted."""

    def __init__(
        self,
        operation: str,
        detail: str,
        *,
        status: CommandStatus | None = None,
        returncode: int | None = None,
    ) -> None:
        self.operation = operation
        self.status = status
        self.returncode = returncode
        super().__init__(f"{operation}: {detail}")


def _raise(operation: str, detail: str) -> Never:
    raise NativeError(operation, detail)


class NativeHermesAdapter:
    """Hermes v0.20 profile commands plus read-only, descriptor-safe readback."""

    def __init__(
        self,
        executor: CommandExecutor,
        env: Mapping[str, str],
        detection: HermesDetection,
    ) -> None:
        try:
            executable = detection.executable.resolve(strict=True)
            home = detection.hermes_home.resolve(strict=False)
            profiles_root = detection.profiles_root.resolve(strict=False)
        except OSError as error:
            raise NativeError("environment", "Hermes paths could not be canonicalized") from error
        if executable != detection.executable:
            raise NativeError("environment", "Hermes executable is not canonical")
        if home != detection.hermes_home or profiles_root != detection.profiles_root:
            raise NativeError("environment", "Hermes paths are not canonical")
        if profiles_root != home / "profiles":
            raise NativeError("environment", "Hermes profiles root is not canonical")
        configured_home = env.get("HERMES_HOME")
        if configured_home is not None:
            configured = Path(configured_home).expanduser().resolve(strict=False)
            if configured != home:
                raise NativeError("environment", "HERMES_HOME differs from detected Hermes home")
        self._executor = executor
        self._env = dict(env)
        self._detection = detection

    def _effective_env(self, env: Mapping[str, str] | None) -> Mapping[str, str]:
        if env is not None and dict(env) != self._env:
            raise NativeError("environment", "supplied environment differs from sealed environment")
        return self._env

    @staticmethod
    def _profile_name(value: str) -> str:
        try:
            return str(HermesProfileName(value))
        except ValueError as error:
            raise NativeError("profile name", "profile name is invalid or reserved") from error

    def _run(
        self, operation: str, argv: tuple[str, ...], env: Mapping[str, str] | None = None
    ) -> CommandOutcome:
        try:
            return self._executor.run(argv, env=self._effective_env(env))
        except NativeError:
            raise
        except Exception as error:
            raise NativeError(operation, "command execution raised an exception") from error

    def _require_success(self, operation: str, outcome: CommandOutcome) -> None:
        if outcome.status is not CommandStatus.SUCCEEDED:
            raise NativeError(
                operation,
                "Hermes command did not succeed",
                status=outcome.status,
                returncode=outcome.returncode,
            )

    def enumerate_profiles(self) -> tuple[ProfileEntry, ...]:
        root = self._detection.profiles_root
        try:
            root_info = root.lstat()
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise NativeError(
                "enumerate profiles", "profiles root could not be inspected"
            ) from error
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            _raise("enumerate profiles", "profiles root is not a safe directory")

        root_fd: int | None = None
        try:
            root_fd = os.open(
                root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            opened = os.fstat(root_fd)
            if opened.st_dev != root_info.st_dev or opened.st_ino != root_info.st_ino:
                _raise("enumerate profiles", "profiles root changed while opening")
            entries: list[ProfileEntry] = []
            for name in sorted(os.listdir(root_fd)):
                info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    kind = ProfileEntryKind.SYMLINK
                elif stat.S_ISDIR(info.st_mode):
                    kind = ProfileEntryKind.PROFILE
                else:
                    kind = ProfileEntryKind.NON_DIRECTORY
                entries.append(ProfileEntry(name, root / name, kind))
            current = root.lstat()
            if current.st_dev != opened.st_dev or current.st_ino != opened.st_ino:
                _raise("enumerate profiles", "profiles root changed during enumeration")
            return tuple(entries)
        except NativeError:
            raise
        except OSError as error:
            raise NativeError(
                "enumerate profiles", "profiles could not be safely enumerated"
            ) from error
        finally:
            if root_fd is not None:
                os.close(root_fd)

    def install(
        self,
        worker: _Worker,
        plan: _Plan,
        *,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutcome:
        if plan.staging_dir is None:
            _raise("install", "installation plan has no staging directory")
        name = self._profile_name(worker.profile_name)
        argv = (
            str(self._detection.executable),
            "profile",
            "install",
            str(plan.staging_dir / name),
            "--yes",
        )
        return self._run("install", argv, env)

    def set_description(
        self, worker: _Worker, *, env: Mapping[str, str] | None = None
    ) -> CommandOutcome:
        name = self._profile_name(worker.profile_name)
        argv = (
            str(self._detection.executable),
            "profile",
            "describe",
            name,
            "--text",
            worker.description,
        )
        return self._run("set description", argv, env)

    def read_description(self, worker: _Worker, *, env: Mapping[str, str] | None = None) -> str:
        name = self._profile_name(worker.profile_name)
        argv = (
            str(self._detection.executable),
            "profile",
            "describe",
            name,
        )
        outcome = self._run("read description", argv, env)
        self._require_success("read description", outcome)
        stdout = outcome.stdout
        if stdout is None:
            _raise("read description", "description output is absent")
        if stdout.endswith("\r\n"):
            description = stdout[:-2]
        elif stdout.endswith("\n"):
            description = stdout[:-1]
        else:
            description = stdout
        if not description or "\n" in description or "\r" in description:
            _raise("read description", "description output is not exactly one line")
        if description.startswith("[auto]"):
            _raise("read description", "auto-generated description is not accepted")
        return description

    def info(self, name: str, *, env: Mapping[str, str] | None = None) -> CommandOutcome:
        safe_name = self._profile_name(name)
        argv = (str(self._detection.executable), "profile", "info", safe_name)
        return self._run("distribution info", argv, env)

    def update(
        self,
        name: str,
        *,
        force_config: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutcome:
        """Update a Hermes v0.20 Distribution, preserving user data by default."""
        safe_name = self._profile_name(name)
        options = ("--force-config", "--yes") if force_config else ("--yes",)
        argv = (str(self._detection.executable), "profile", "update", safe_name, *options)
        return self._run("distribution update", argv, env)

    def read_distribution_info(
        self, worker: _Worker, *, env: Mapping[str, str] | None = None
    ) -> Mapping[str, object]:
        name = self._profile_name(worker.profile_name)
        outcome = self.info(name, env=env)
        self._require_success("distribution info", outcome)
        return self._read_distribution(name)

    def _read_distribution(self, name: str) -> Mapping[str, object]:
        root_fd: int | None = None
        profile_fd: int | None = None
        manifest_fd: int | None = None
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            root_fd = os.open(
                self._detection.profiles_root,
                flags | os.O_DIRECTORY,
            )
            profile_fd = os.open(name, flags | os.O_DIRECTORY, dir_fd=root_fd)
            profile_info = os.fstat(profile_fd)
            bound_profile = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(profile_info.st_mode)
                or profile_info.st_dev != bound_profile.st_dev
                or profile_info.st_ino != bound_profile.st_ino
            ):
                _raise("distribution info", "distribution profile is not safely bound")
            manifest_fd = os.open("distribution.yaml", flags, dir_fd=profile_fd)
            manifest_info = os.fstat(manifest_fd)
            if not stat.S_ISREG(manifest_info.st_mode):
                _raise("distribution info", "distribution manifest is not a regular file")
            chunks: list[bytes] = []
            while chunk := os.read(manifest_fd, 65536):
                chunks.append(chunk)
            rebound_manifest = os.stat(
                "distribution.yaml", dir_fd=profile_fd, follow_symlinks=False
            )
            rebound_profile = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if (
                rebound_manifest.st_dev != manifest_info.st_dev
                or rebound_manifest.st_ino != manifest_info.st_ino
                or not stat.S_ISREG(rebound_manifest.st_mode)
                or rebound_profile.st_dev != profile_info.st_dev
                or rebound_profile.st_ino != profile_info.st_ino
                or not stat.S_ISDIR(rebound_profile.st_mode)
            ):
                _raise("distribution info", "distribution changed during readback")
            loaded = cast(object, yaml.safe_load(b"".join(chunks)))
            if not isinstance(loaded, dict):
                _raise("distribution info", "distribution manifest is not a string-keyed mapping")
            untyped = cast(dict[object, object], loaded)
            if not all(isinstance(key, str) for key in untyped):
                _raise("distribution info", "distribution manifest is not a string-keyed mapping")
            return cast(dict[str, object], untyped)
        except NativeError:
            raise
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise NativeError(
                "distribution info", "distribution manifest could not be safely read"
            ) from error
        finally:
            for descriptor in (manifest_fd, profile_fd, root_fd):
                if descriptor is not None:
                    os.close(descriptor)

    def rename(
        self,
        current: str,
        target: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> CommandOutcome:
        safe_current = self._profile_name(current)
        safe_target = self._profile_name(target)
        if safe_current == safe_target:
            _raise("rename", "source and target profile names must differ")
        argv = (
            str(self._detection.executable),
            "profile",
            "rename",
            safe_current,
            safe_target,
        )
        return self._run("rename", argv, env)

    def delete(self, name: str, *, env: Mapping[str, str] | None = None) -> CommandOutcome:
        safe_name = self._profile_name(name)
        argv = (
            str(self._detection.executable),
            "profile",
            "delete",
            safe_name,
            "--yes",
        )
        return self._run("delete", argv, env)
