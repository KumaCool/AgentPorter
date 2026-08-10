from __future__ import annotations

import pytest


def test_install_entry_is_an_intentionally_unimplemented_phase_1_skeleton() -> None:
    from agentporter import main

    with pytest.raises(SystemExit, match="not available in Phase 1"):
        main()
