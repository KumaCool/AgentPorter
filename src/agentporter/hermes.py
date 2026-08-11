from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class DetectionError(RuntimeError):
    """Hermes could not be detected safely."""


class CommandRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        shell: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class HermesCapabilities:
    available_profile_commands: frozenset[str]
    missing_profile_commands: frozenset[str]

    @property
    def profile_commands(self) -> frozenset[str]:
        return self.available_profile_commands

    @property
    def supports_required_profile_commands(self) -> bool:
        return not self.missing_profile_commands


class ProfileEntryKind(StrEnum):
    PROFILE = "profile"
    SYMLINK = "symlink"
    NON_DIRECTORY = "non-directory"


@dataclass(frozen=True)
class ProfileEntry:
    name: str
    path: Path
    kind: ProfileEntryKind


@dataclass(frozen=True)
class HermesDetection:
    executable: Path
    version: str
    hermes_home: Path
    profiles_root: Path
    capabilities: HermesCapabilities
    profile_entries: tuple[ProfileEntry, ...]


def _enumerate_profiles(profiles_root: Path) -> tuple[ProfileEntry, ...]:
    if not profiles_root.exists():
        return ()
    if profiles_root.is_symlink() or not profiles_root.is_dir():
        raise DetectionError("Hermes profiles root is not a safe directory")
    entries: list[ProfileEntry] = []
    for path in sorted(profiles_root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            kind = ProfileEntryKind.SYMLINK
        elif path.is_dir():
            kind = ProfileEntryKind.PROFILE
        else:
            kind = ProfileEntryKind.NON_DIRECTORY
        entries.append(ProfileEntry(name=path.name, path=path, kind=kind))
    return tuple(entries)


def _default_runner(
    argv: Sequence[str], *, shell: bool, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        shell=shell,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def detect_hermes(
    *,
    env: Mapping[str, str] | None = None,
    runner: CommandRunner = _default_runner,
) -> HermesDetection:
    effective_env = os.environ if env is None else env
    executable_text = shutil.which("hermes", path=effective_env.get("PATH"))
    if executable_text is None:
        raise DetectionError("Hermes executable was not found")
    executable = Path(executable_text).expanduser().resolve(strict=True)
    version_result = runner((str(executable), "--version"), shell=False, env=effective_env)
    if version_result.returncode != 0:
        raise DetectionError("Hermes version probe failed")
    match = re.search(r"\bv?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b", version_result.stdout)
    if match is None:
        raise DetectionError("Hermes version output was not recognized")
    help_result = runner((str(executable), "profile", "--help"), shell=False, env=effective_env)
    if help_result.returncode != 0:
        raise DetectionError("Hermes profile help capability probe failed")
    required_commands = frozenset({"install", "delete", "describe", "list", "info"})
    words = frozenset(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", help_result.stdout))
    profile_commands = required_commands & words

    hermes_home_text = effective_env.get("HERMES_HOME")
    if hermes_home_text:
        hermes_home = Path(hermes_home_text).expanduser().resolve(strict=False)
    else:
        user_home_text = effective_env.get("HOME")
        if not user_home_text:
            raise DetectionError("Hermes home could not be resolved")
        hermes_home = (Path(user_home_text).expanduser() / ".hermes").resolve(strict=False)
    profiles_path = hermes_home / "profiles"
    profile_entries = _enumerate_profiles(profiles_path)
    profiles_root = profiles_path.resolve(strict=False)
    return HermesDetection(
        executable=executable,
        version=match.group(1),
        hermes_home=hermes_home,
        profiles_root=profiles_root,
        capabilities=HermesCapabilities(
            available_profile_commands=profile_commands,
            missing_profile_commands=required_commands - profile_commands,
        ),
        profile_entries=profile_entries,
    )
