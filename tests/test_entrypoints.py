from __future__ import annotations

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
