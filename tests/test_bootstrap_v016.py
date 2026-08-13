from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_bootstrap_installer import _run  # pyright: ignore[reportPrivateUsage]

VERSION = "0.1.6"

PREVIOUS_VERSION = "0.1.5"
NAMES = ("agentporter", "agentporter-activate", "agentporter-uninstall")


def _seed_015(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "agentporter" / PREVIOUS_VERSION
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    public_entries: list[str] = []
    for name in NAMES:
        private = root / "venv" / "bin" / name
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(f"old:{name}\n")
        public = bindir / name
        public.symlink_to(private)
        public_entries.append(str(public))
    (root / "bootstrap-install.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "product": "agentporter",
                "version": PREVIOUS_VERSION,
                "public_entries": public_entries,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return root


def test_v017_rejects_direct_upgrade_from_completed_015_without_mutating_profiles(
    tmp_path: Path,
) -> None:
    old_root = _seed_015(tmp_path)
    profile = tmp_path / "home" / ".hermes" / "profiles" / "worker" / "config.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"provider: untouched\n")
    before = (profile.read_bytes(), profile.stat().st_mtime_ns)

    result = _run(tmp_path, checksum=hashlib.sha256(b"wheel-bytes").hexdigest())

    assert result.returncode == 1
    assert "public entry path already exists" in result.stderr
    assert old_root.exists()
    assert profile.read_bytes() == before[0]
    assert profile.stat().st_mtime_ns == before[1]
    assert not (tmp_path / "data" / "agentporter" / "0.1.7").exists()
