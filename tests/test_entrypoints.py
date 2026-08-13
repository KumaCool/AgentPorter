from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _uninstall_module() -> ModuleType:
    return importlib.import_module("agentporter.uninstall_entry")


def test_install_entry_is_connected_to_the_phase_3_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentporter import main

    called: list[bool] = []

    def fake_run() -> None:
        called.append(True)

    monkeypatch.setattr("agentporter.run_product_installer", fake_run)

    main()

    assert called == [True]


def test_product_entry_forwards_only_minimal_noncredential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agentporter

    captured: dict[str, str] = {}
    sentinel = "sentinel-secret-value"
    for key in ("LC_ALL", "LC_CTYPE", "TMP", "TEMP", "TMPDIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setenv("AUDIT_PROVIDER_API_KEY", sentinel)
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("HOME", "/safe/home")
    monkeypatch.setenv("HERMES_HOME", "/safe/hermes")
    monkeypatch.setenv("LANG", "C.UTF-8")

    class _Workflow:
        status = agentporter.WorkflowStatus.CANCELLED

    class _Result:
        workflow = _Workflow()
        transaction = None

    def fake_installer(
        manifest: object,
        staging: object,
        env: dict[str, str],
    ) -> _Result:
        captured.update(env)
        return _Result()

    monkeypatch.setattr(agentporter, "run_installer", fake_installer)

    with pytest.raises(SystemExit, match="cancelled"):
        agentporter.run_product_installer()

    assert captured == {
        "HOME": "/safe/home",
        "HERMES_HOME": "/safe/hermes",
        "LANG": "C.UTF-8",
        "PATH": "/safe/bin",
    }
    assert sentinel not in captured.values()
    assert not any(
        marker in key.upper()
        for key in captured
        for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    )
    assert os.environ["AUDIT_PROVIDER_API_KEY"] == sentinel


def test_uninstall_entry_forwards_only_minimal_noncredential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uninstall = _uninstall_module()
    from agentporter.uninstall_application import UninstallerStatus

    captured: dict[str, str] = {}
    sentinel = "uninstall-sentinel-secret"
    for key in ("LC_ALL", "LC_CTYPE", "TMP", "TEMP", "TMPDIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setenv("AUDIT_PROVIDER_API_KEY", sentinel)
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("HOME", "/safe/home")
    monkeypatch.setenv("HERMES_HOME", "/safe/hermes")
    monkeypatch.setenv("LANG", "C.UTF-8")

    def fake_uninstaller(env: dict[str, str]) -> object:
        captured.update(env)
        return SimpleNamespace(status=UninstallerStatus.ALREADY_ABSENT)

    monkeypatch.setattr(uninstall, "run_uninstaller", fake_uninstaller)

    uninstall.main()

    assert captured == {
        "HOME": "/safe/home",
        "HERMES_HOME": "/safe/hermes",
        "LANG": "C.UTF-8",
        "PATH": "/safe/bin",
    }
    assert sentinel not in captured.values()


@pytest.mark.parametrize(
    ("status", "successful"),
    [
        ("already-absent", True),
        ("deleted", True),
        ("cancelled", False),
        ("ambiguous", False),
        ("stale", False),
        ("failed", False),
        ("partial-delete", False),
    ],
)
def test_uninstall_entry_exit_contract(
    monkeypatch: pytest.MonkeyPatch, status: str, successful: bool
) -> None:
    uninstall = _uninstall_module()
    from agentporter.uninstall_application import UninstallerStatus

    result = SimpleNamespace(status=UninstallerStatus(status))

    def return_result(env: dict[str, str]) -> object:
        return result

    monkeypatch.setattr(uninstall, "run_uninstaller", return_result)

    if successful:
        uninstall.main()
    else:
        with pytest.raises(SystemExit, match=status):
            uninstall.main()


@pytest.mark.parametrize("status", ["already-absent", "deleted"])
def test_successful_bootstrap_uninstall_removes_the_published_package(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    uninstall = _uninstall_module()
    from agentporter.self_cleanup import CleanupPlanStatus
    from agentporter.uninstall_application import UninstallerStatus

    plan = SimpleNamespace(status=CleanupPlanStatus.READY)
    calls: list[object] = []
    monkeypatch.setattr(sys, "executable", "/sealed/agentporter/venv/bin/python")

    def successful_uninstall(env: dict[str, str]) -> object:
        return SimpleNamespace(status=UninstallerStatus(status))

    monkeypatch.setattr(uninstall, "run_uninstaller", successful_uninstall)

    def build(*, executable: Path, version: str, env: dict[str, str]) -> object:
        calls.append((executable, version, env is os.environ))
        return plan

    monkeypatch.setattr(uninstall, "build_bootstrap_cleanup_plan", build)
    monkeypatch.setattr(uninstall, "execute_cleanup_plan", calls.append)

    uninstall.main()

    assert calls == [
        (Path("/sealed/agentporter/venv/bin/python"), "0.1.5", True),
        plan,
    ]


def test_activation_entry_forwards_only_minimal_noncredential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activation = importlib.import_module("agentporter.activation_entry")
    from agentporter.activation_application import ActivationStatus

    captured: dict[str, str] = {}
    sentinel = "activation-sentinel-secret"
    monkeypatch.setenv("AUDIT_PROVIDER_API_KEY", sentinel)
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("HOME", "/safe/home")
    monkeypatch.setenv("HERMES_HOME", "/safe/hermes")
    monkeypatch.setenv("LANG", "C.UTF-8")

    def fake_activator(env: dict[str, str]) -> object:
        captured.update(env)
        return SimpleNamespace(status=ActivationStatus.ACTIVATED)

    monkeypatch.setattr(activation, "run_activator", fake_activator)

    activation.main()

    assert captured == {
        "HOME": "/safe/home",
        "HERMES_HOME": "/safe/hermes",
        "LANG": "C.UTF-8",
        "PATH": "/safe/bin",
    }
    assert sentinel not in captured.values()


@pytest.mark.parametrize(
    ("status", "successful"),
    [
        ("activated", True),
        ("credential-required", True),
        ("cancelled", False),
        ("stale", False),
        ("failed", False),
        ("compensation-incomplete", False),
    ],
)
def test_activation_entry_exit_contract(
    monkeypatch: pytest.MonkeyPatch, status: str, successful: bool
) -> None:
    activation = importlib.import_module("agentporter.activation_entry")
    from agentporter.activation_application import ActivationStatus

    def return_activation(env: dict[str, str]) -> object:
        return SimpleNamespace(status=ActivationStatus(status))

    monkeypatch.setattr(activation, "run_activator", return_activation)

    if successful:
        activation.main()
    else:
        with pytest.raises(SystemExit, match=status):
            activation.main()


def test_failed_profile_uninstall_never_removes_the_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uninstall = _uninstall_module()
    from agentporter.self_cleanup import CleanupPlanStatus
    from agentporter.uninstall_application import UninstallerStatus

    plan = SimpleNamespace(status=CleanupPlanStatus.READY)

    def build(*, executable: Path, version: str, env: dict[str, str]) -> object:
        return plan

    def partial_uninstall(env: dict[str, str]) -> object:
        return SimpleNamespace(status=UninstallerStatus.PARTIAL_DELETE)

    def forbidden_cleanup(cleanup_plan: object) -> None:
        pytest.fail("failed profile uninstall must preserve the package")

    monkeypatch.setattr(uninstall, "build_bootstrap_cleanup_plan", build)
    monkeypatch.setattr(
        uninstall,
        "run_uninstaller",
        partial_uninstall,
    )
    monkeypatch.setattr(uninstall, "execute_cleanup_plan", forbidden_cleanup)

    with pytest.raises(SystemExit, match="partial-delete"):
        uninstall.main()
