from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HERMES = Path("/usr/local/bin/hermes")


@pytest.mark.skipif(not HERMES.is_file(), reason="system Hermes CLI is not installed")
def test_real_hermes_public_cli_safe_combinations_use_isolated_homes(tmp_path: Path) -> None:
    """No model call, credential mutation, Gateway action, or Kanban action is allowed here."""
    home = tmp_path / "home"
    hermes_home = tmp_path / "hermes-home"
    home.mkdir()
    hermes_home.mkdir()
    env = {
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
    }

    commands = (
        (str(HERMES), "--help"),
        (str(HERMES), "config", "--help"),
        (str(HERMES), "config"),
        (str(HERMES), "auth", "status", "openrouter"),
    )
    results = [
        subprocess.run(command, env=env, text=True, capture_output=True, timeout=30, check=False)
        for command in commands
    ]

    assert results[0].returncode == 0 and "Hermes" in results[0].stdout
    assert results[1].returncode == 0 and "config" in results[1].stdout.lower()
    assert results[2].returncode == 0
    assert results[3].returncode in {0, 1}
    status_text = (results[3].stdout + results[3].stderr).lower()
    assert any(
        term in status_text for term in ("logged out", "not configured", "no credential", "unknown")
    )
    assert not (hermes_home / "auth.json").exists()
    assert not (hermes_home / "state.db").exists()
    assert not (hermes_home / "kanban.db").exists()
    assert not (hermes_home / "gateway.pid").exists()
