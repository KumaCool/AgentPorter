from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from agentporter import bootstrap_txn as tx


def _world(
    tmp_path: Path, *, fresh: bool = False
) -> tuple[dict[str, object], Path, dict[str, int]]:
    old = tmp_path / "0.2.0"
    new = tmp_path / "0.2.1"
    if not fresh:
        old.mkdir()
    new.mkdir()
    if not fresh:
        (old / "bootstrap-install.json").write_text('{"version":"0.2.0"}\n')
    (new / "bootstrap-install.json").write_text('{"version":"0.2.1"}\n')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    entries: list[dict[str, str]] = []
    old_inodes: dict[str, int] = {}
    for name in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
        old_target = old / "venv" / "bin" / name
        new_target = new / "venv" / "bin" / name
        if not fresh:
            old_target.parent.mkdir(parents=True, exist_ok=True)
            old_target.write_text(f"old:{name}\n")
        new_target.parent.mkdir(parents=True, exist_ok=True)
        new_target.write_text(f"new:{name}\n")
        public = bindir / name
        if not fresh:
            public.symlink_to(old_target)
            old_inodes[name] = public.lstat().st_ino
        entries.append(
            {
                "name": name,
                "public": str(public),
                "old_target": str(old_target) if not fresh else "",
                "new_target": str(new_target),
            }
        )
    spec: dict[str, object] = {
        "schema": 2,
        "mode": "fresh" if fresh else "upgrade",
        "old_root": str(old),
        "new_root": str(new),
        "old_receipt": str(old / "bootstrap-install.json"),
        "new_receipt": str(new / "bootstrap-install.json"),
        "entries": entries,
        "journal": str(tmp_path / ".0.2.1-entry-transaction.json"),
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    spec_path.chmod(0o600)
    return spec, spec_path, old_inodes


def _run(
    spec_path: Path, operation: str, *, crash_at: int | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if crash_at is not None:
        env["AGENTPORTER_TXN_CRASH_AT"] = str(crash_at)
    return subprocess.run(
        [sys.executable, str(Path(tx.__file__)), operation, str(spec_path)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _assert_old(spec: dict[str, object], inodes: dict[str, int]) -> None:
    for entry in spec["entries"]:  # type: ignore[union-attr]
        item = cast(dict[str, str], entry)  # type: ignore[assignment]
        public = Path(item["public"])
        assert public.is_symlink()
        assert os.readlink(public) == item["old_target"]
        assert public.lstat().st_ino == inodes[item["name"]]
        assert not os.path.lexists(f"{public}.txn-new")
        assert not os.path.lexists(f"{public}.txn-quarantine")


def _assert_new(spec: dict[str, object]) -> None:
    for entry in spec["entries"]:  # type: ignore[union-attr]
        item = cast(dict[str, str], entry)  # type: ignore[assignment]
        public = Path(item["public"])
        assert public.is_symlink()
        assert os.readlink(public) == item["new_target"]
        assert not os.path.lexists(f"{public}.txn-new")
        assert not os.path.lexists(f"{public}.txn-quarantine")


def test_fresh_apply_publishes_exact_three_entries(tmp_path: Path) -> None:
    spec, spec_path, _ = _world(tmp_path, fresh=True)
    result = _run(spec_path, "apply")
    assert result.returncode == 0, result.stderr
    _assert_new(spec)


def test_upgrade_apply_publishes_exact_three_entries(tmp_path: Path) -> None:
    spec, spec_path, _ = _world(tmp_path)
    result = _run(spec_path, "apply")
    assert result.returncode == 0, result.stderr
    _assert_new(spec)


@pytest.mark.parametrize("fresh", [False, True], ids=["upgrade", "fresh"])
def test_sigkill_at_every_checkpoint_recovers_to_one_complete_state(
    tmp_path: Path, fresh: bool
) -> None:
    probe = tmp_path / "probe"
    probe.mkdir()
    _, probe_path, _ = _world(probe, fresh=fresh)
    completed = _run(probe_path, "apply")
    assert completed.returncode == 0, completed.stderr
    checkpoint_count = int(completed.stdout.rsplit("=", 1)[1])
    assert checkpoint_count >= 10

    for crash_at in range(1, checkpoint_count + 1):
        case = tmp_path / f"case-{crash_at}"
        case.mkdir()
        spec, spec_path, inodes = _world(case, fresh=fresh)
        interrupted = _run(spec_path, "apply", crash_at=crash_at)
        assert interrupted.returncode == -signal.SIGKILL, (crash_at, interrupted.stderr)
        journal = Path(str(spec["journal"]))
        committed = (
            journal.exists() and json.loads(journal.read_text())["payload"]["committed"]
        ) or (not journal.exists() and not Path(str(spec["old_root"])).exists())
        if not spec_path.exists():
            assert not journal.exists()
            _assert_new(spec)
            continue
        recovered = _run(spec_path, "recover")
        assert recovered.returncode == 0, (crash_at, recovered.stderr)
        if committed:
            _assert_new(spec)
        elif fresh:
            assert all(
                not os.path.lexists(Path(item["public"]))  # type: ignore[index]
                for item in spec["entries"]  # type: ignore[union-attr]
            )
        else:
            _assert_old(spec, inodes)


def test_same_target_replacement_during_recovery_is_inode_drift_with_zero_writes(
    tmp_path: Path,
) -> None:
    spec, spec_path, _ = _world(tmp_path)
    interrupted = _run(spec_path, "apply", crash_at=9)
    assert interrupted.returncode == -signal.SIGKILL
    public = Path(spec["entries"][0]["public"])  # type: ignore[index]
    target = os.readlink(public)
    preserved = public.with_name("preserved-transaction-link")
    public.rename(preserved)
    public.symlink_to(target)
    journal = Path(str(spec["journal"]))
    before = journal.read_bytes()
    identities = {path: (path.lstat().st_dev, path.lstat().st_ino) for path in (public, preserved)}

    recovered = _run(spec_path, "recover")

    assert recovered.returncode == 3
    assert journal.read_bytes() == before
    assert {path: (path.lstat().st_dev, path.lstat().st_ino) for path in identities} == identities


@pytest.mark.parametrize("drift", ["old-root", "new-root", "old-receipt", "new-receipt"])
def test_root_or_receipt_drift_refuses_apply_before_any_write(tmp_path: Path, drift: str) -> None:
    spec, spec_path, _ = _world(tmp_path)
    plan = tx.build_plan(json.loads(spec_path.read_text()))
    target = Path(str(spec[drift.replace("-", "_")]))
    if drift.endswith("root"):
        moved = target.with_name(f"moved-{target.name}")
        target.rename(moved)
        target.mkdir()
    else:
        target.write_text("drift\n")
    before = sorted((str(path), path.lstat().st_ino) for path in tmp_path.rglob("*"))

    with pytest.raises(tx.DriftError):
        tx.start(plan)

    assert sorted((str(path), path.lstat().st_ino) for path in tmp_path.rglob("*")) == before
    assert not Path(str(spec["journal"])).exists()


def test_apply_owns_committed_old_root_cleanup_and_all_metadata(tmp_path: Path) -> None:
    spec, spec_path, _ = _world(tmp_path)
    result = _run(spec_path, "apply")
    assert result.returncode == 0, result.stderr
    assert not Path(str(spec["old_root"])).exists()
    assert not Path(str(spec["new_root"])).with_name(".0.2.1-txn-quarantine").exists()
    assert not Path(str(spec["journal"])).exists()
    assert not spec_path.exists()


def test_uncommitted_recovery_owns_exact_new_root_cleanup(tmp_path: Path) -> None:
    spec, spec_path, inodes = _world(tmp_path)
    interrupted = _run(spec_path, "apply", crash_at=2)
    assert interrupted.returncode == -signal.SIGKILL
    recovered = _run(spec_path, "recover")
    assert recovered.returncode == 0, recovered.stderr
    _assert_old(spec, inodes)
    assert not Path(str(spec["new_root"])).exists()
    assert not Path(str(spec["new_root"])).with_name(".0.2.1-txn-quarantine").exists()
    assert not Path(str(spec["journal"])).exists()
    assert not spec_path.exists()


@pytest.mark.parametrize("kind", ["extra-key", "mode", "owner", "oversized", "symlink"])
def test_spec_is_strict_private_bounded_and_path_bound(tmp_path: Path, kind: str) -> None:
    spec, spec_path, _ = _world(tmp_path)
    if kind == "extra-key":
        spec["extra"] = True
        spec_path.write_text(json.dumps(spec))
    elif kind == "mode":
        spec_path.chmod(0o640)
    elif kind == "owner":
        try:
            os.chown(spec_path, 65534, 65534)
        except PermissionError:
            pytest.skip("changing file ownership requires root")
    elif kind == "oversized":
        spec_path.write_bytes(b" " * 65537)
    else:
        real = spec_path.with_name("real-spec")
        spec_path.rename(real)
        spec_path.symlink_to(real)
    before = sorted((str(p), p.lstat().st_ino) for p in tmp_path.rglob("*"))
    result = _run(spec_path, "apply")
    assert result.returncode == 3
    assert sorted((str(p), p.lstat().st_ino) for p in tmp_path.rglob("*")) == before


@pytest.mark.parametrize("kind", ["extra-key", "mode", "oversized", "self-rehashed-path"])
def test_journal_tampering_refuses_recovery_with_zero_writes(tmp_path: Path, kind: str) -> None:
    spec, spec_path, _ = _world(tmp_path)
    assert _run(spec_path, "apply", crash_at=2).returncode == -signal.SIGKILL
    journal = Path(str(spec["journal"]))
    if kind == "mode":
        journal.chmod(0o640)
    elif kind == "oversized":
        journal.write_bytes(b" " * 65537)
    else:
        doc = json.loads(journal.read_text())
        if kind == "extra-key":
            doc["extra"] = True
        else:
            doc["payload"]["roots"]["new"]["path"] = str(tmp_path / "attacker")
            encoded = json.dumps(doc["payload"], sort_keys=True, separators=(",", ":")).encode()
            doc["payload_sha256"] = __import__("hashlib").sha256(encoded).hexdigest()
        journal.write_text(json.dumps(doc))
    before = {
        p: (p.lstat().st_ino, p.read_bytes() if p.is_file() else b"") for p in tmp_path.rglob("*")
    }
    result = _run(spec_path, "recover")
    assert result.returncode == 3
    assert {
        p: (p.lstat().st_ino, p.read_bytes() if p.is_file() else b"") for p in tmp_path.rglob("*")
    } == before
