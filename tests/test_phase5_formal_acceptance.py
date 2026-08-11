from __future__ import annotations

import builtins
import json
import os
import resource
import shutil
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

import agentporter
import agentporter.application as install_application
import uninstall as uninstall_entry
from agentporter.execution import CommandExecutor
from agentporter.identity import COMPONENT_IDS, INITIAL_PROFILE_NAMES, PRODUCT_ID
from agentporter.models import MarkerV1, WorkersManifest
from agentporter.render import DISTRIBUTION_VERSION
from agentporter.uninstall_application import UninstallerStatus

HERMES = Path("/usr/local/lib/hermes-agent/venv/bin/hermes")
MANIFEST = Path(__file__).parents[1] / "workers.yaml"
RENAMED = ("phase5-renamed-luna", "phase5-renamed-codex")
FORBIDDEN_COMMANDS = frozenset({"chat", "run", "model"})
REAL_RUN_INSTALLER = install_application.run_installer
REAL_RUN_UNINSTALLER = uninstall_entry.run_uninstaller
CREDENTIAL_KEYS = frozenset(
    {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "NOUS_API_KEY"}
)


@pytest.fixture
def isolated_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("phase5-formal")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=False)
        assert not root.exists()


class MetricsRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.profile_install_seconds: list[float] = []
        self.staging_peak_bytes = 0
        self.staging_roots: set[Path] = set()

    @staticmethod
    def tree_bytes(root: Path) -> int:
        if not root.exists():
            return 0
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

    def watch_staging(self, root: Path) -> None:
        self.staging_roots.add(root)
        self.staging_peak_bytes = max(self.staging_peak_bytes, self.tree_bytes(root))

    def __call__(
        self,
        argv: Sequence[str],
        *,
        shell: bool,
        env: Mapping[str, str],
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(argv)
        self.calls.append(normalized)
        assert shell is False
        assert check is False
        assert capture_output is True
        assert text is True
        assert normalized[0] == str(HERMES.resolve(strict=True))
        assert not (set(normalized[1:]) & FORBIDDEN_COMMANDS)
        assert "--auto" not in normalized
        assert not any(env.get(key) for key in CREDENTIAL_KEYS)
        for root in self.staging_roots:
            self.watch_staging(root)
        started = time.perf_counter()
        completed = subprocess.run(
            normalized,
            shell=False,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - started
        if normalized[1:3] == ("profile", "install"):
            self.profile_install_seconds.append(elapsed)
        for root in self.staging_roots:
            self.watch_staging(root)
        return completed


def _environment(root: Path) -> dict[str, str]:
    home = root / "home"
    hermes_home = root / "hermes"
    home.mkdir()
    hermes_home.mkdir()
    return {
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "PATH": f"{HERMES.parent}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONIOENCODING": "utf-8",
    }


def _run_cli(
    runner: MetricsRunner, env: Mapping[str, str], cwd: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    completed = runner((str(HERMES), *args), shell=False, env=env, timeout=30)
    assert completed.returncode == 0, completed.stderr
    return completed


def _profile_names(list_output: str) -> set[str]:
    return {
        line.strip().removeprefix("*").strip().split()[0]
        for line in list_output.splitlines()
        if line.strip() and not line.lower().startswith("available profiles")
    }


def _disk_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _install_formally(
    monkeypatch: pytest.MonkeyPatch,
    env: Mapping[str, str],
    runner: MetricsRunner,
) -> tuple[str, float]:
    output = StringIO()

    def entry_run_installer(
        manifest_path: Path, staging_parent: Path, minimal_env: Mapping[str, str]
    ) -> Any:
        assert manifest_path == MANIFEST
        assert minimal_env == env
        runner.watch_staging(staging_parent)

        def exact_answer(prompt: str) -> str:
            prefix = "Type "
            suffix = " to confirm: "
            assert prompt.startswith(prefix) and prompt.endswith(suffix)
            phrase = prompt[len(prefix) : -len(suffix)]
            assert phrase.startswith("INSTALL AGENTPORTER ")
            return phrase

        return REAL_RUN_INSTALLER(
            manifest_path,
            staging_parent,
            minimal_env,
            input_fn=exact_answer,
            output=output,
            executor_factory=lambda: CommandExecutor(runner=runner, timeout_seconds=30),
        )

    monkeypatch.setattr(agentporter, "run_installer", entry_run_installer)
    started = time.perf_counter()
    agentporter.run_product_installer()
    return output.getvalue(), time.perf_counter() - started


def _uninstall_formally(
    monkeypatch: pytest.MonkeyPatch,
    env: Mapping[str, str],
    runner: MetricsRunner,
) -> tuple[str, float]:
    output = StringIO()

    def entry_run_uninstaller(minimal_env: Mapping[str, str]) -> Any:
        assert minimal_env == env

        def exact_answer(prompt: str) -> str:
            prefix = "Type "
            suffix = " to confirm: "
            assert prompt.startswith(prefix) and prompt.endswith(suffix)
            phrase = prompt[len(prefix) : -len(suffix)]
            assert phrase.startswith("DELETE AGENTPORTER ")
            return phrase

        return REAL_RUN_UNINSTALLER(
            minimal_env,
            input_fn=exact_answer,
            output=output,
            executor_factory=lambda: CommandExecutor(runner=runner, timeout_seconds=30),
        )

    monkeypatch.setattr(uninstall_entry, "run_uninstaller", entry_run_uninstaller)
    started = time.perf_counter()
    uninstall_entry.main()
    return output.getvalue(), time.perf_counter() - started


def _manifest() -> WorkersManifest:
    return WorkersManifest.model_validate(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))


def _assert_exact_static_readback(env: Mapping[str, str], names: Sequence[str]) -> None:
    manifest = _manifest()
    profiles_root = Path(env["HERMES_HOME"]) / "profiles"
    installation_ids: set[str] = set()
    for (portable_id, worker), name in zip(manifest.workers.items(), names, strict=True):
        profile = profiles_root / name
        config = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
        distribution = yaml.safe_load(
            (profile / "distribution.yaml").read_text(encoding="utf-8")
        )
        marker = MarkerV1.model_validate_json(
            (profile / "agentporter-profile.json").read_text(encoding="utf-8")
        )
        expected_model: dict[str, str] = {"default": worker.model}
        if worker.provider is not None:
            expected_model["provider"] = worker.provider
        assert config == {
            "model": expected_model,
            "agent": {"reasoning_effort": worker.reasoning_effort},
        }
        soul_lines = [
            worker.instructions.rstrip(),
            "",
            "AgentPorter delegation boundaries:",
            "- Do not change the delegated objective.",
            "- Do not broaden the delegated scope or file set.",
            "- If required information is missing, stop and report the exact blocker.",
            "- Never invent results in place of real execution and verification.",
        ]
        if worker.tier == "mechanical":
            soul_lines.append(
                "- Accept only work that is simpler and more mechanical than bounded work."
            )
        assert (profile / "SOUL.md").read_text(encoding="utf-8") == "\n".join(soul_lines) + "\n"
        expected_distribution = {
            "name": INITIAL_PROFILE_NAMES[portable_id],
            "version": DISTRIBUTION_VERSION,
            "description": worker.description,
            "license": "MIT",
            "distribution_owned": ["SOUL.md", "config.yaml", "agentporter-profile.json"],
        }
        assert {key: distribution[key] for key in expected_distribution} == expected_distribution
        assert isinstance(distribution["source"], str)
        assert isinstance(distribution["installed_at"], str)
        assert marker.product_id == PRODUCT_ID
        assert marker.component_id == COMPONENT_IDS[portable_id]
        assert marker.distribution_version == DISTRIBUTION_VERSION
        installation_ids.add(marker.installation_id)
    assert len(installation_ids) == 1


def test_formal_entries_real_hermes_cold_hot_acceptance_and_resource_baseline(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert HERMES.is_file()
    original_environment = os.environ.copy()
    original_cwd = Path.cwd()
    cycles: list[dict[str, Any]] = []

    def unexpected_input(_: str) -> str:
        pytest.fail("bound seam must be used")

    try:
        for label in ("cold", "hot"):
            cycle_root = isolated_root / label
            cycle_root.mkdir()
            env = _environment(cycle_root)
            runner = MetricsRunner()
            monkeypatch.setattr(os, "environ", env)
            monkeypatch.setattr(builtins, "input", unexpected_input)
            before_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            disk_before = _disk_bytes(cycle_root)

            install_output, install_seconds = _install_formally(monkeypatch, env, runner)
            assert "Model calls: false" in install_output
            assert len(runner.profile_install_seconds) == 2

            foreign_cwd = cycle_root / "different-project" / "nested"
            foreign_cwd.mkdir(parents=True)
            os.chdir(foreign_cwd)
            listed = _run_cli(runner, env, foreign_cwd, "profile", "list").stdout
            initial_names = tuple(INITIAL_PROFILE_NAMES.values())
            assert set(initial_names) <= _profile_names(listed)
            for name in initial_names:
                info = _run_cli(runner, env, foreign_cwd, "profile", "info", name).stdout
                shown = _run_cli(runner, env, foreign_cwd, "profile", "show", name).stdout
                described = _run_cli(runner, env, foreign_cwd, "profile", "describe", name).stdout
                assert DISTRIBUTION_VERSION in info
                assert name in shown
                assert next(
                    worker.description
                    for key, worker in _manifest().workers.items()
                    if INITIAL_PROFILE_NAMES[key] == name
                ) in described
            _assert_exact_static_readback(env, initial_names)

            # This delegate_task child is forbidden from mutating Kanban. Ground the example in
            # the real v0.20 parser and read-only assignee enumeration without dispatch/model calls.
            kanban_help = _run_cli(runner, env, foreign_cwd, "kanban", "create", "--help").stdout
            assert "--assignee ASSIGNEE" in kanban_help
            assert "--workspace WORKSPACE" in kanban_help
            assert "scratch | worktree | worktree:<path> | dir:<path>" in kanban_help

            for old_name, new_name in zip(initial_names, RENAMED, strict=True):
                _run_cli(runner, env, foreign_cwd, "profile", "rename", old_name, new_name)
            renamed_listing = _run_cli(runner, env, foreign_cwd, "profile", "list").stdout
            assert set(RENAMED) <= _profile_names(renamed_listing)
            assignees = json.loads(
                _run_cli(runner, env, foreign_cwd, "kanban", "assignees", "--json").stdout
            )
            assert set(RENAMED) <= {item["name"] for item in assignees}
            assert all(item["on_disk"] is True for item in assignees if item["name"] in RENAMED)
            _assert_exact_static_readback(env, RENAMED)

            uninstall_output, uninstall_seconds = _uninstall_formally(
                monkeypatch, env, runner
            )
            assert "permanently deleted in its entirety" in uninstall_output
            absent_listing = _run_cli(runner, env, foreign_cwd, "profile", "list").stdout
            assert not (set(RENAMED) & _profile_names(absent_listing))
            profiles_root = Path(env["HERMES_HOME"]) / "profiles"
            assert all(not (profiles_root / name).exists() for name in RENAMED)
            assert REAL_RUN_UNINSTALLER(env).status is UninstallerStatus.ALREADY_ABSENT

            after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            install_profile_seconds = tuple(runner.profile_install_seconds)
            hermes_subprocess_count = len(runner.calls)
            peak_rss_kib = after_usage.ru_maxrss
            child_cpu_seconds = (
                after_usage.ru_utime
                + after_usage.ru_stime
                - before_usage.ru_utime
                - before_usage.ru_stime
            )
            staging_final_bytes = sum(
                runner.tree_bytes(staging_root) for staging_root in runner.staging_roots
            )
            final_disk_delta_bytes = _disk_bytes(cycle_root) - disk_before
            assert install_seconds >= 0
            assert all(value >= 0 for value in install_profile_seconds)
            assert uninstall_seconds >= 0
            assert 2 <= hermes_subprocess_count < 100
            assert peak_rss_kib > 0
            assert child_cpu_seconds >= 0
            assert runner.staging_peak_bytes > 0
            assert staging_final_bytes == 0
            assert final_disk_delta_bytes >= 0
            metrics: dict[str, Any] = {
                "cycle": label,
                "install_total_seconds": install_seconds,
                "install_profile_seconds": install_profile_seconds,
                "uninstall_total_seconds": uninstall_seconds,
                "hermes_subprocess_count": hermes_subprocess_count,
                "peak_rss_kib": peak_rss_kib,
                "child_cpu_seconds": child_cpu_seconds,
                "staging_peak_bytes": runner.staging_peak_bytes,
                "staging_final_bytes": staging_final_bytes,
                "final_disk_delta_bytes": final_disk_delta_bytes,
            }
            cycles.append(metrics)
            os.chdir(original_cwd)
            shutil.rmtree(cycle_root, ignore_errors=False)
            assert not cycle_root.exists()
    finally:
        os.chdir(original_cwd)
        os.environ.clear()
        os.environ.update(original_environment)

    assert [cycle["cycle"] for cycle in cycles] == ["cold", "hot"]
    encoded_evidence = "PHASE5_FORMAL_BASELINE=" + json.dumps(cycles, sort_keys=True)
    print(encoded_evidence)
    evidence = capsys.readouterr().out
    assert encoded_evidence in evidence
    with capsys.disabled():
        print(encoded_evidence)
