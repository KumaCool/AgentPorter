from __future__ import annotations

import pytest


def test_install_entry_remains_blocked_until_phase_3_installation_exists() -> None:
    from agentporter import main

    with pytest.raises(SystemExit, match="not available before Phase 3"):
        main()
