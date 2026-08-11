from __future__ import annotations

import os

import pytest


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
