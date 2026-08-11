from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Never

import pytest

from agentporter.hermes import DetectionError, ProfileEntryKind, detect_hermes


class RecordingRunner:
    def __init__(
        self, responses: Mapping[tuple[str, ...], subprocess.CompletedProcess[str]]
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], bool, Mapping[str, str]]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        shell: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        self.calls.append((key, shell, env))
        return self.responses[key]


def completed(
    argv: tuple[str, ...], stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, "")


def test_detect_reports_executable_and_parsed_version_with_argv_and_shell_false(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "hermes-home"
    (home / "profiles").mkdir(parents=True)
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes Agent v1.2.3\n"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"),
                "commands: install delete describe list info\n",
            ),
        }
    )
    isolated_env = {"PATH": str(executable.parent), "HERMES_HOME": str(home)}

    result = detect_hermes(env=isolated_env, runner=runner)

    assert result.executable == executable
    assert result.version == "1.2.3"
    assert result.hermes_home == home
    assert result.profiles_root == home / "profiles"
    assert result.capabilities.profile_commands == frozenset(
        {"install", "delete", "describe", "list", "info"}
    )
    assert [call[0] for call in runner.calls] == [
        (str(executable), "--version"),
        (str(executable), "profile", "--help"),
    ]
    assert all(shell is False for _, shell, _ in runner.calls)
    assert all(call_env is isolated_env for _, _, call_env in runner.calls)


def test_detect_fails_when_executable_is_absent_without_running_commands(tmp_path: Path) -> None:
    class FailIfCalled:
        def __call__(self, *_args: object, **_kwargs: object) -> Never:
            pytest.fail("runner must not be called")

    with pytest.raises(DetectionError, match="executable"):
        detect_hermes(env={"PATH": str(tmp_path)}, runner=FailIfCalled())


def test_detect_enumerates_only_direct_profile_directories_and_marks_unsafe_entries(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "alpha").mkdir()
    (profiles / "alpha" / "nested").mkdir()
    (profiles / "plain-file").write_text("not a profile", encoding="utf-8")
    (profiles / "linked").symlink_to(profiles / "alpha", target_is_directory=True)
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes v2.0.0"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"),
                "install delete describe list info",
            ),
        }
    )

    result = detect_hermes(
        env={"PATH": str(executable.parent), "HERMES_HOME": str(home)}, runner=runner
    )

    assert [(entry.name, entry.kind) for entry in result.profile_entries] == [
        ("alpha", ProfileEntryKind.PROFILE),
        ("linked", ProfileEntryKind.SYMLINK),
        ("plain-file", ProfileEntryKind.NON_DIRECTORY),
    ]
    assert all(entry.path.parent == profiles for entry in result.profile_entries)


def test_detect_fails_when_version_output_is_invalid(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    home.mkdir()
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "unparseable"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"), "install delete describe list info"
            ),
        }
    )

    with pytest.raises(DetectionError, match="version output"):
        detect_hermes(env={"PATH": str(executable.parent), "HERMES_HOME": str(home)}, runner=runner)


def test_detect_reports_missing_profile_capabilities_without_hard_coding_host_values(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    home.mkdir()
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes v2.0.0"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"), "install delete list"
            ),
        }
    )

    result = detect_hermes(
        env={"PATH": str(executable.parent), "HERMES_HOME": str(home)}, runner=runner
    )

    assert result.capabilities.available_profile_commands == frozenset(
        {"install", "delete", "list"}
    )
    assert result.capabilities.missing_profile_commands == frozenset({"describe", "info"})
    assert result.capabilities.supports_required_profile_commands is False


def test_detect_rejects_symlink_profiles_root(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    home.mkdir()
    real_profiles = tmp_path / "elsewhere"
    real_profiles.mkdir()
    (home / "profiles").symlink_to(real_profiles, target_is_directory=True)
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes v2.0.0"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"),
                "install delete describe list info",
            ),
        }
    )

    with pytest.raises(DetectionError, match="profiles root"):
        detect_hermes(env={"PATH": str(executable.parent), "HERMES_HOME": str(home)}, runner=runner)


def test_detect_uses_home_only_as_isolated_fallback_when_hermes_home_is_unset(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    fallback_home = tmp_path / "user-home" / ".hermes"
    fallback_home.mkdir(parents=True)
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes v2.0.0"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"),
                "install delete describe list info",
            ),
        }
    )

    result = detect_hermes(
        env={"PATH": str(executable.parent), "HOME": str(tmp_path / "user-home")},
        runner=runner,
    )

    assert result.hermes_home == fallback_home


def test_detect_canonicalizes_relative_which_and_home_paths_before_cwd_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    executable = origin / "bin" / "hermes"
    executable.parent.mkdir(parents=True)
    executable.touch(mode=0o700)
    home = origin / "state"
    (home / "profiles" / "existing").mkdir(parents=True)
    canonical_executable = executable.resolve(strict=True)
    canonical_home = home.resolve(strict=False)
    runner = RecordingRunner(
        {
            (str(canonical_executable), "--version"): completed(
                (str(canonical_executable), "--version"), "Hermes v2.0.0"
            ),
            (str(canonical_executable), "profile", "--help"): completed(
                (str(canonical_executable), "profile", "--help"),
                "install delete describe list info",
            ),
        }
    )
    monkeypatch.chdir(origin)

    result = detect_hermes(env={"PATH": "bin", "HERMES_HOME": "state/../state"}, runner=runner)
    monkeypatch.chdir(tmp_path)

    assert result.executable == canonical_executable
    assert result.hermes_home == canonical_home
    assert result.profiles_root == canonical_home / "profiles"
    assert result.profile_entries[0].path == canonical_home / "profiles" / "existing"
    assert all(
        path.is_absolute() for path in (result.executable, result.hermes_home, result.profiles_root)
    )
    assert [call[0][0] for call in runner.calls] == [str(canonical_executable)] * 2


def test_detect_canonicalizes_relative_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    executable = origin / "bin" / "hermes"
    executable.parent.mkdir(parents=True)
    executable.touch(mode=0o700)
    fallback = origin / "user" / ".hermes"
    fallback.mkdir(parents=True)
    canonical_executable = executable.resolve(strict=True)
    runner = RecordingRunner(
        {
            (str(canonical_executable), "--version"): completed(
                (str(canonical_executable), "--version"), "Hermes v2.0.0"
            ),
            (str(canonical_executable), "profile", "--help"): completed(
                (str(canonical_executable), "profile", "--help"),
                "install delete describe list info",
            ),
        }
    )
    monkeypatch.chdir(origin)

    result = detect_hermes(env={"PATH": "bin", "HOME": "user"}, runner=runner)
    monkeypatch.chdir(tmp_path)

    assert result.hermes_home == fallback.resolve(strict=False)
    assert result.profiles_root == (fallback / "profiles").resolve(strict=False)


def test_detection_path_never_uses_filesystem_mutation_or_model_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    (home / "profiles" / "existing").mkdir(parents=True)
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes v2.0.0"
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"),
                "install delete describe list info",
            ),
        }
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("detection attempted a filesystem mutation")

    mutation_methods = (
        "mkdir",
        "write_text",
        "write_bytes",
        "touch",
        "unlink",
        "rename",
        "replace",
    )
    for method_name in mutation_methods:
        monkeypatch.setattr(Path, method_name, forbidden)

    result = detect_hermes(
        env={"PATH": str(executable.parent), "HERMES_HOME": str(home)}, runner=runner
    )

    assert [entry.name for entry in result.profile_entries] == ["existing"]
    assert all("chat" not in argv and "model" not in argv for argv, _, _ in runner.calls)


@pytest.mark.parametrize("failed_probe", ["version", "help"])
def test_detect_maps_nonzero_probe_exit_to_detection_error(
    tmp_path: Path, failed_probe: str
) -> None:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.touch(mode=0o700)
    home = tmp_path / "state"
    home.mkdir()
    version_code = 9 if failed_probe == "version" else 0
    help_code = 9 if failed_probe == "help" else 0
    runner = RecordingRunner(
        {
            (str(executable), "--version"): completed(
                (str(executable), "--version"), "Hermes v2.0.0", version_code
            ),
            (str(executable), "profile", "--help"): completed(
                (str(executable), "profile", "--help"),
                "install delete describe list info",
                help_code,
            ),
        }
    )

    with pytest.raises(DetectionError, match=failed_probe):
        detect_hermes(env={"PATH": str(executable.parent), "HERMES_HOME": str(home)}, runner=runner)
