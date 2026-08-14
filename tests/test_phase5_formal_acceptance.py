from __future__ import annotations

import builtins
import importlib
import json
import os
import resource
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

import agentporter
import agentporter.application as install_application
from agentporter.execution import CommandExecutor
from agentporter.identity import INITIAL_PROFILE_NAMES, INSTALL_COMPONENT_IDS, PRODUCT_ID
from agentporter.models import MarkerV1, WorkersManifest
from agentporter.render import DISTRIBUTION_VERSION
from agentporter.uninstall_application import UninstallerStatus
from tests.plan06_support import runtime_bindings

HERMES = Path("/usr/local/lib/hermes-agent/venv/bin/hermes")
MANIFEST = Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml"
uninstall_entry = importlib.import_module("agentporter.uninstall_entry")
RENAMED = (
    "phase5-renamed-luna",
    "phase5-renamed-codex",
    "phase5-renamed-orchestrator",
)
REAL_RUN_INSTALLER = install_application.run_installer
REAL_RUN_UNINSTALLER = uninstall_entry.run_uninstaller
GNU_TIME = Path("/usr/bin/time")


def _expected_families() -> tuple[str, ...]:
    install_worker = (
        "profile-install",
        "profile-describe-text",
        "profile-info",
        "profile-describe",
    )
    installed_readback = (
        "profile-info",
        "profile-show",
        "profile-describe",
    )
    return (
        *install_worker,
        *install_worker,
        *install_worker,
        "profile-list",
        *installed_readback,
        *installed_readback,
        *installed_readback,
        "kanban-create-help",
        "profile-rename",
        "profile-rename",
        "profile-rename",
        "profile-list",
        "kanban-assignees-json",
        "profile-delete",
        "profile-delete",
        "profile-delete",
        "profile-list",
    )


def _profile_description_pairs() -> set[tuple[str, str]]:
    manifest = _manifest()
    return {
        (INITIAL_PROFILE_NAMES[portable_id], worker.description)
        for portable_id, worker in manifest.workers.items()
    }


def _command_family(argv: tuple[str, ...], staging_roots: set[Path]) -> str:
    """Return the one closed-grammar command family, or fail before execution."""
    assert argv and argv[0] == str(HERMES.resolve(strict=True))
    tail = argv[1:]
    if tail == ("profile", "list"):
        return "profile-list"
    if tail == ("kanban", "assignees", "--json"):
        return "kanban-assignees-json"
    if tail == ("kanban", "create", "--help"):
        return "kanban-create-help"
    if len(tail) == 3 and tail[:2] in {
        ("profile", "info"),
        ("profile", "show"),
        ("profile", "describe"),
    }:
        assert tail[2] in {*INITIAL_PROFILE_NAMES.values(), *RENAMED}
        return "-".join(tail[:2])
    if len(tail) == 5 and tail[:2] == ("profile", "describe") and tail[3] == "--text":
        assert (tail[2], tail[4]) in _profile_description_pairs()
        return "profile-describe-text"
    if len(tail) == 4 and tail[:2] == ("profile", "rename"):
        assert (tail[2], tail[3]) in set(zip(INITIAL_PROFILE_NAMES.values(), RENAMED, strict=True))
        return "profile-rename"
    if len(tail) == 4 and tail[:2] == ("profile", "delete") and tail[3] == "--yes":
        assert tail[2] in RENAMED
        return "profile-delete"
    if len(tail) == 4 and tail[:2] == ("profile", "install") and tail[3] == "--yes":
        source = Path(tail[2])
        assert source.is_absolute()
        assert source.name in INITIAL_PROFILE_NAMES.values()
        assert source.parent.parent in staging_roots
        assert source.parent.name.startswith("agentporter-")
        return "profile-install"
    raise AssertionError(f"argv is outside the closed Phase 5 grammar: {tail!r}")


@pytest.fixture
def isolated_root(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    root = tmp_path_factory.mktemp("phase5-formal")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=False)
        assert not root.exists()


class MetricsRunner:
    def __init__(self, expected_env: Mapping[str, str]) -> None:
        assert GNU_TIME.is_file()
        self.expected_env = dict(expected_env)
        self.calls: list[tuple[str, ...]] = []
        self.families: list[str] = []
        self.per_child_peak_rss_kib: list[int] = []
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
        assert shell is False
        assert check is False
        assert capture_output is True
        assert text is True
        assert dict(env) == self.expected_env
        family = _command_family(normalized, self.staging_roots)
        self.calls.append(normalized)
        self.families.append(family)
        for root in self.staging_roots:
            self.watch_staging(root)
        started = time.perf_counter()
        metric_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="phase5-rss-", delete=False) as metric_file:
                metric_path = Path(metric_file.name)
            completed = subprocess.run(
                (str(GNU_TIME), "--format=%M", f"--output={metric_path}", "--", *normalized),
                shell=False,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            peak_rss_kib = int(metric_path.read_text(encoding="ascii").strip())
            assert peak_rss_kib > 0
            self.per_child_peak_rss_kib.append(peak_rss_kib)
        finally:
            if metric_path is not None:
                metric_path.unlink(missing_ok=True)
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
            binding_selection=runtime_bindings(),
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
        distribution = yaml.safe_load((profile / "distribution.yaml").read_text(encoding="utf-8"))
        marker = MarkerV1.model_validate_json(
            (profile / "agentporter-profile.json").read_text(encoding="utf-8")
        )
        binding = runtime_bindings()[portable_id]
        expected_model: dict[str, str] = {
            "default": binding.model,
            "provider": binding.provider,
            "base_url": binding.endpoint,
        }
        expected_config: dict[str, object] = {
            "model": expected_model,
            "agent": {"reasoning_effort": worker.reasoning_effort},
        }
        if portable_id == "agentporter_orchestrator":
            expected_config.update(
                kanban={
                    "auto_decompose": False,
                    "max_in_progress_per_profile": 1,
                    "dispatch_interval_seconds": 10,
                    "orchestrator_profile": "agentporter-orchestrator",
                    "auto_subscribe_on_create": True,
                },
                platform_toolsets={"cli": ["kanban"]},
            )
        assert config == expected_config
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
        assert marker.component_id == INSTALL_COMPONENT_IDS[portable_id]
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
            runner = MetricsRunner(env)
            monkeypatch.setattr(os, "environ", env)
            monkeypatch.setattr(builtins, "input", unexpected_input)
            before_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            disk_before = _disk_bytes(cycle_root)

            install_output, install_seconds = _install_formally(monkeypatch, env, runner)
            assert "Model calls: false" in install_output
            assert len(runner.profile_install_seconds) == 3

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
                assert (
                    next(
                        worker.description
                        for key, worker in _manifest().workers.items()
                        if INITIAL_PROFILE_NAMES[key] == name
                    )
                    in described
                )
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

            uninstall_output, uninstall_seconds = _uninstall_formally(monkeypatch, env, runner)
            assert "permanently deleted in its entirety" in uninstall_output
            absent_listing = _run_cli(runner, env, foreign_cwd, "profile", "list").stdout
            assert not (set(RENAMED) & _profile_names(absent_listing))
            profiles_root = Path(env["HERMES_HOME"]) / "profiles"
            assert all(not (profiles_root / name).exists() for name in RENAMED)
            assert REAL_RUN_UNINSTALLER(env).status is UninstallerStatus.ALREADY_ABSENT

            assert tuple(runner.families) == _expected_families()
            assert Counter(runner.families) == Counter(_expected_families())
            assert len(runner.per_child_peak_rss_kib) == len(runner.calls)

            after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            install_profile_seconds = tuple(runner.profile_install_seconds)
            hermes_subprocess_count = len(runner.calls)
            # GNU time reports an independent maximum resident set for each exact inner
            # Hermes command.  The cycle metric is the maximum of this cycle's calls only.
            peak_rss_kib = max(runner.per_child_peak_rss_kib)
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
                "peak_rss_definition": "max independent GNU-time %M across Hermes calls in cycle",
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
    assert all(cycle["peak_rss_kib"] > 0 for cycle in cycles)
    encoded_evidence = "PHASE5_FORMAL_BASELINE=" + json.dumps(cycles, sort_keys=True)
    print(encoded_evidence)
    evidence = capsys.readouterr().out
    assert encoded_evidence in evidence
    with capsys.disabled():
        print(encoded_evidence)


@pytest.mark.parametrize(
    "tail",
    [
        ("auth", "login"),
        ("setup",),
        ("config", "set", "model", "unsafe"),
        ("provider", "list"),
        ("profile", "unknown"),
        ("profile", "list", "--json"),
    ],
)
def test_metrics_runner_rejects_every_command_outside_closed_grammar_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tail: tuple[str, ...]
) -> None:
    env = _environment(tmp_path)
    runner = MetricsRunner(env)
    invoked = False

    def forbidden_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal invoked
        invoked = True
        raise AssertionError("subprocess must not be reached")

    monkeypatch.setattr(subprocess, "run", forbidden_run)
    with pytest.raises(AssertionError, match="closed Phase 5 grammar"):
        runner((str(HERMES), *tail), shell=False, env=env)
    assert not invoked
    assert runner.calls == []


def test_metrics_runner_rejects_extra_environment_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _environment(tmp_path)
    runner = MetricsRunner(env)
    invoked = False

    def forbidden_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal invoked
        invoked = True
        raise AssertionError("subprocess must not be reached")

    monkeypatch.setattr(subprocess, "run", forbidden_run)
    with pytest.raises(AssertionError):
        runner(
            (str(HERMES), "profile", "list"),
            shell=False,
            env={**env, "EXTRA": "not-sealed"},
        )
    assert not invoked
    assert runner.calls == []


def test_closed_grammar_rejects_mismatched_description_and_nested_staging_source(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    runner = MetricsRunner(env)
    staging = tmp_path / "staging"
    staging.mkdir()
    runner.watch_staging(staging)
    pairs = sorted(_profile_description_pairs())
    assert len(pairs) == 3

    with pytest.raises(AssertionError):
        _command_family(
            (
                str(HERMES.resolve(strict=True)),
                "profile",
                "describe",
                pairs[0][0],
                "--text",
                pairs[1][1],
            ),
            runner.staging_roots,
        )

    nested = staging / "agentporter-valid-looking" / "extra" / pairs[0][0]
    with pytest.raises(AssertionError):
        _command_family(
            (str(HERMES.resolve(strict=True)), "profile", "install", str(nested), "--yes"),
            runner.staging_roots,
        )


def test_metrics_runner_peak_is_independent_of_lifetime_child_rusage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _environment(tmp_path)
    original_run = subprocess.run
    # Deliberately raise the process-lifetime RUSAGE_CHILDREN high-water mark first.
    original_run(
        ("/usr/bin/python3", "-c", "x = bytearray(64 * 1024 * 1024); print(len(x))"),
        check=True,
        capture_output=True,
        text=True,
    )
    historical_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    assert historical_peak > 123

    def measured_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        metric_argument = next(item for item in argv if item.startswith("--output="))
        Path(metric_argument.removeprefix("--output=")).write_text("123\n", encoding="ascii")
        return subprocess.CompletedProcess(argv, 0, stdout="profiles", stderr="")

    monkeypatch.setattr(subprocess, "run", measured_run)
    runner = MetricsRunner(env)
    runner((str(HERMES), "profile", "list"), shell=False, env=env, timeout=30)
    assert runner.per_child_peak_rss_kib == [123]
    assert runner.per_child_peak_rss_kib[0] < historical_peak
