#!/usr/bin/env python3
"""AgentPorter POSIX bootstrap entry transaction (schema v2).

The caller builds a fully sealed plan before start(). start() performs a
read-only preflight, durably creates the journal, then publishes three links.
Recovery recognizes only transaction-produced inode/target combinations.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import sys
from pathlib import Path
from typing import Any, cast


class DriftError(RuntimeError):
    pass


_counter = 0
MAX_AUTHORITY_FILE = 65536
NAMES = ("agentporter", "agentporter-activate", "agentporter-uninstall")


def checkpoint() -> None:
    global _counter
    _counter += 1
    wanted = os.environ.get("AGENTPORTER_TXN_CRASH_AT")
    if wanted and _counter == int(wanted):
        os.kill(os.getpid(), signal.SIGKILL)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def seal(path: Path, *, symlink: bool = False) -> dict[str, Any]:
    st = os.lstat(path) if symlink else os.stat(path)
    result = {
        "path": str(path),
        "dev": st.st_dev,
        "ino": st.st_ino,
        "mode": stat.S_IFMT(st.st_mode),
        "size": st.st_size,
    }
    if stat.S_ISLNK(st.st_mode):
        result.update(kind="symlink", target=os.readlink(path))
    elif stat.S_ISREG(st.st_mode):
        result.update(kind="file", sha256=digest(path))
    elif stat.S_ISDIR(st.st_mode):
        result.update(kind="directory")
    else:
        result.update(kind="other")
    return result


def matches(s: dict[str, Any], path: Path | None = None) -> bool:
    p = path or Path(s["path"])
    try:
        now = seal(p, symlink=True)
    except FileNotFoundError:
        return False
    keys = ("dev", "ino", "mode", "size", "kind", "target", "sha256")
    return all(k not in s or now.get(k) == s[k] for k in keys)


def assert_absent(path: Path) -> None:
    if os.path.lexists(path):
        raise DriftError(f"expected absent: {path}")


def absent_seal(path: Path) -> dict[str, Any]:
    return {"path": str(path), "kind": "absent"}


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        st = path.lstat()
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o600
            or st.st_size > MAX_AUTHORITY_FILE
        ):
            raise DriftError("authority file must be regular, owner-only, and bounded")
        raw = path.read_bytes()
        if len(raw) != st.st_size:
            raise DriftError("authority file changed while reading")
        value = json.loads(raw)
    except (OSError, ValueError, TypeError) as exc:
        raise DriftError("invalid authority file") from exc
    if not isinstance(value, dict):
        raise DriftError("authority file must contain an object")
    return cast(dict[str, Any], value)


def validate_spec(spec: dict[str, Any]) -> None:
    expected = {
        "schema",
        "mode",
        "old_root",
        "new_root",
        "old_receipt",
        "new_receipt",
        "entries",
        "journal",
    }
    if set(spec) != expected or spec.get("schema") != 2:
        raise DriftError("invalid spec schema")
    raw_entries = spec.get("entries")
    if not isinstance(raw_entries, list):
        raise DriftError("schema v2 requires exactly three entries")
    entries = cast(list[object], raw_entries)
    if len(entries) != 3:
        raise DriftError("schema v2 requires exactly three entries")
    if any(not isinstance(entry, dict) for entry in entries):
        raise DriftError("invalid entry schema")
    typed_entries = cast(list[dict[str, Any]], entries)
    if [entry.get("name") for entry in typed_entries] != list(NAMES):
        raise DriftError("invalid entry set")
    if any(set(entry) != {"name", "public", "old_target", "new_target"} for entry in typed_entries):
        raise DriftError("invalid entry schema")
    old, new = Path(spec["old_root"]), Path(spec["new_root"])
    if (
        Path(spec["old_receipt"]) != old / "bootstrap-install.json"
        or Path(spec["new_receipt"]) != new / "bootstrap-install.json"
    ):
        raise DriftError("receipt path binding failure")
    if Path(spec["journal"]) != new.parent / ".0.2.1-entry-transaction.json":
        raise DriftError("journal path binding failure")
    for entry in typed_entries:
        name = entry["name"]
        if Path(entry["new_target"]) != new / "venv/bin" / name:
            raise DriftError("new target path binding failure")
        if spec["mode"] == "upgrade" and Path(entry["old_target"]) != old / "venv/bin" / name:
            raise DriftError("old target path binding failure")


def build_plan(spec: dict[str, Any], spec_seal: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_spec(spec)
    mode = spec.get("mode", "upgrade")
    if mode not in {"fresh", "upgrade"}:
        raise DriftError("unsupported transaction mode")
    roots = {"new": seal(Path(spec["new_root"]))}
    receipts = {"new": seal(Path(spec["new_receipt"]))}
    if mode == "upgrade":
        roots["old"] = seal(Path(spec["old_root"]))
        receipts["old"] = seal(Path(spec["old_receipt"]))
    else:
        assert_absent(Path(spec["old_root"]))
        assert_absent(Path(spec["old_receipt"]))
        roots["old"] = absent_seal(Path(spec["old_root"]))
        receipts["old"] = absent_seal(Path(spec["old_receipt"]))
    entries: list[dict[str, Any]] = []
    for raw in spec["entries"]:
        public = Path(raw["public"])
        q = Path(str(public) + ".txn-quarantine")
        staging = Path(str(public) + ".txn-new")
        assert_absent(q)
        assert_absent(staging)
        if mode == "upgrade":
            old_link = seal(public, symlink=True)
            if old_link.get("kind") != "symlink" or old_link.get("target") != raw["old_target"]:
                raise DriftError(f"old public link mismatch: {public}")
            old_target = seal(Path(raw["old_target"]))
        else:
            assert_absent(public)
            old_link = absent_seal(public)
            old_target = absent_seal(public)
        new_target = seal(Path(raw["new_target"]))
        entries.append(
            {
                "name": raw["name"],
                "public": str(public),
                "quarantine": str(q),
                "staging": str(staging),
                "old_link": old_link,
                "old_target": old_target,
                "new_target": new_target,
            }
        )
    return {
        "schema": 2,
        "mode": mode,
        "journal": spec["journal"],
        "spec": spec_seal,
        "committed": False,
        "old_root_quarantine": str(Path(spec["old_root"]).with_name(".0.2.0-txn-quarantine")),
        "new_root_quarantine": str(Path(spec["new_root"]).with_name(".0.2.1-txn-quarantine")),
        "old_root_cleanup_authorized": False,
        "new_root_cleanup_authorized": False,
        "roots": roots,
        "receipts": receipts,
        "entries": entries,
    }


def validate_sealed_inputs(plan: dict[str, Any], *, recovery: bool = False) -> None:
    for group in ("roots", "receipts"):
        for s in plan[group].values():
            if s["kind"] == "absent":
                if os.path.lexists(Path(s["path"])):
                    raise DriftError(f"sealed {group} drift: {s['path']}")
            elif not matches(s):
                key = next(key for key, value in plan[group].items() if value is s)
                quarantine = Path(plan[f"{key}_root_quarantine"])
                authorized = bool(plan.get(f"{key}_root_cleanup_authorized"))
                candidate = (
                    quarantine if group == "roots" else quarantine / "bootstrap-install.json"
                )
                if not (
                    recovery
                    and authorized
                    and (not os.path.lexists(candidate) or matches(s, candidate))
                ):
                    raise DriftError(f"sealed {group} drift: {s['path']}")
    if plan.get("spec") is not None and not matches(plan["spec"]):
        raise DriftError("spec drift")
    for e in plan["entries"]:
        old_matches = (
            e["old_target"]["kind"] == "absent"
            or matches(e["old_target"])
            or (recovery and plan.get("old_root_cleanup_authorized"))
        )
        new_matches = matches(e["new_target"]) or (
            recovery and plan.get("new_root_cleanup_authorized")
        )
        if not old_matches or not new_matches:
            raise DriftError(f"entry target drift: {e['name']}")


def validate_pristine(plan: dict[str, Any]) -> None:
    validate_sealed_inputs(plan)
    for e in plan["entries"]:
        if e["old_link"]["kind"] == "absent":
            assert_absent(Path(e["public"]))
        elif not matches(e["old_link"], Path(e["public"])):
            raise DriftError(f"public inode drift: {e['public']}")
        assert_absent(Path(e["quarantine"]))
        assert_absent(Path(e["staging"]))
    assert_absent(Path(plan["journal"]))
    assert_absent(Path(plan["journal"] + ".next"))


def envelope(plan: dict[str, Any]) -> bytes:
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    doc = {"payload": plan, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest()}
    return (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_journal(plan: dict[str, Any]) -> None:
    dst = Path(plan["journal"])
    tmp = Path(str(dst) + ".next")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, envelope(plan))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, dst)
    fsync_dir(dst.parent)
    checkpoint()


def read_journal(path: Path) -> dict[str, Any]:
    doc = read_private_json(path)
    if set(doc) != {"payload", "payload_sha256"} or not isinstance(doc["payload"], dict):
        raise DriftError("invalid journal schema")
    payload = cast(dict[str, Any], doc["payload"])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != doc["payload_sha256"]:
        raise DriftError("journal integrity failure")
    expected = {
        "schema",
        "mode",
        "journal",
        "spec",
        "committed",
        "old_root_quarantine",
        "new_root_quarantine",
        "old_root_cleanup_authorized",
        "new_root_cleanup_authorized",
        "roots",
        "receipts",
        "entries",
    }
    if set(payload) != expected or payload["journal"] != str(path):
        raise DriftError("invalid journal payload schema")
    return payload


def make_symlink(target: str, path: Path) -> None:
    os.symlink(target, path)
    fsync_dir(path.parent)


def rename(src: Path, dst: Path) -> None:
    os.rename(src, dst)
    checkpoint()
    fsync_dir(dst.parent)
    checkpoint()


def unlink(path: Path) -> None:
    os.unlink(path)
    checkpoint()
    fsync_dir(path.parent)
    checkpoint()


def start(plan: dict[str, Any]) -> None:
    # Critical property: every drift check happens before the first write.
    validate_pristine(plan)
    write_journal(plan)
    for e in plan["entries"]:
        public, q, staging = map(Path, (e["public"], e["quarantine"], e["staging"]))
        make_symlink(e["new_target"]["path"], staging)
        e["new_link"] = seal(staging, symlink=True)
        write_journal(plan)
        if plan["mode"] == "upgrade":
            rename(public, q)  # preserve the exact old symlink inode
        rename(staging, public)  # atomic publication
    plan["committed"] = True
    write_journal(plan)  # durable commit record is the sole commit point
    cleanup_committed(plan)
    finish(plan)


def classify(e: dict[str, Any]) -> tuple[str, str, str]:
    def one(path: Path) -> str:
        if not os.path.lexists(path):
            return "absent"
        if e["old_link"]["kind"] != "absent" and matches(e["old_link"], path):
            return "old"
        if "new_link" in e and matches(e["new_link"], path):
            return "new"
        return "drift"

    return one(Path(e["public"])), one(Path(e["quarantine"])), one(Path(e["staging"]))


def validate_recovery(plan: dict[str, Any]) -> None:
    validate_sealed_inputs(plan, recovery=True)
    allowed_pre = {
        ("old", "absent", "absent"),
        ("old", "absent", "new"),
        ("absent", "old", "new"),
        ("new", "old", "absent"),
    }
    if plan["mode"] == "fresh":
        allowed_pre = {
            ("absent", "absent", "absent"),
            ("absent", "absent", "new"),
            ("new", "absent", "absent"),
        }
    allowed_post = {("new", "old", "absent"), ("new", "absent", "absent")}
    allowed = allowed_post if plan["committed"] else allowed_pre
    for e in plan["entries"]:
        state = classify(e)
        if state not in allowed:
            raise DriftError(f"unrecognized recovery state {e['name']}: {state}")


def rollback_uncommitted(plan: dict[str, Any]) -> None:
    for e in reversed(plan["entries"]):
        public, q, staging = map(Path, (e["public"], e["quarantine"], e["staging"]))
        pub, qua, _ = classify(e)
        if pub == "new":
            unlink(public)
        if qua == "old":
            rename(q, public)
        if os.path.lexists(staging):
            unlink(staging)


def cleanup_committed(plan: dict[str, Any]) -> None:
    for e in plan["entries"]:
        q, staging = Path(e["quarantine"]), Path(e["staging"])
        if os.path.lexists(q):
            unlink(q)
        if os.path.lexists(staging):
            unlink(staging)
    if plan["mode"] == "upgrade":
        old = Path(plan["roots"]["old"]["path"])
        qroot = Path(plan["old_root_quarantine"])
        if not plan["old_root_cleanup_authorized"]:
            plan["old_root_cleanup_authorized"] = True
            write_journal(plan)
        if os.path.lexists(old):
            assert_absent(qroot)
            rename(old, qroot)
        if os.path.lexists(qroot):
            if not matches(plan["roots"]["old"], qroot):
                raise DriftError("old root quarantine drift")
            shutil.rmtree(qroot)
            fsync_dir(qroot.parent)
            checkpoint()


def remove_new_root(plan: dict[str, Any]) -> None:
    new = Path(plan["roots"]["new"]["path"])
    qroot = Path(plan["new_root_quarantine"])
    if not plan["new_root_cleanup_authorized"]:
        plan["new_root_cleanup_authorized"] = True
        write_journal(plan)
    if os.path.lexists(new):
        assert_absent(qroot)
        rename(new, qroot)
    if os.path.lexists(qroot):
        if not matches(plan["roots"]["new"], qroot):
            raise DriftError("new root quarantine drift")
        shutil.rmtree(qroot)
        fsync_dir(qroot.parent)
        checkpoint()


def finish(plan: dict[str, Any]) -> None:
    journal = Path(plan["journal"])
    if os.path.lexists(journal):
        unlink(journal)
    spec = plan.get("spec")
    if spec is not None and os.path.lexists(Path(spec["path"])):
        unlink(Path(spec["path"]))


def recover(spec: dict[str, Any]) -> None:
    journal = Path(spec["journal"])
    tmp = Path(str(journal) + ".next")
    if not journal.exists():
        # Initial journal creation did not reach its atomic replace. Old links
        # are untouched; only a private temp journal can exist.
        if tmp.exists():
            unlink(tmp)
        return
    plan = read_journal(journal)
    validate_recovery(plan)  # read-only gate before recovery's first write
    if plan["committed"]:
        cleanup_committed(plan)
    else:
        rollback_uncommitted(plan)
        remove_new_root(plan)
    finish(plan)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"apply", "recover"}:
        print("usage: bootstrap_txn.py apply|recover SPEC.json", file=sys.stderr)
        return 2
    try:
        spec_path = Path(sys.argv[2])
        spec = read_private_json(spec_path)
        if sys.argv[1] == "apply":
            start(build_plan(spec, seal(spec_path)))
        else:
            recover(spec)
            if not Path(str(spec["journal"])).exists() and spec_path.exists():
                unlink(spec_path)
        print(f"ok checkpoints={_counter}")
        return 0
    except DriftError as exc:
        print(f"DRIFT: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
