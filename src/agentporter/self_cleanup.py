from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

_RECEIPT = "bootstrap-install.json"
_ENTRY_NAMES = ("agentporter", "agentporter-activate", "agentporter-uninstall")


class CleanupPlanStatus(StrEnum):
    READY = "ready"
    NOT_BOOTSTRAP_INSTALL = "not-bootstrap-install"
    UNSAFE = "unsafe"


@dataclass(frozen=True)
class PathIdentity:
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class BootstrapCleanupPlan:
    status: CleanupPlanStatus
    install_root: Path | None = None
    product_root: Path | None = None
    public_entry: Path | None = None
    interpreter: Path | None = None
    private_entry: Path | None = None
    receipt: Path | None = None
    quarantine: Path | None = None
    link_quarantine: Path | None = None
    install_identity: PathIdentity | None = None
    interpreter_identity: PathIdentity | None = None
    entry_identity: PathIdentity | None = None
    receipt_identity: PathIdentity | None = None
    link_identity: PathIdentity | None = None
    receipt_bytes: bytes | None = None
    public_entries: tuple[Path, ...] = ()
    private_entries: tuple[Path, ...] = ()
    entry_identities: tuple[PathIdentity, ...] = ()
    link_identities: tuple[PathIdentity, ...] = ()
    link_quarantines: tuple[Path, ...] = ()


def _identity(path: Path, *, follow_symlinks: bool = False) -> PathIdentity:
    current = path.stat(follow_symlinks=follow_symlinks)
    return PathIdentity(current.st_dev, current.st_ino, current.st_mode)


def _same_identity(path: Path, expected: PathIdentity, *, follow_symlinks: bool = False) -> bool:
    try:
        return _identity(path, follow_symlinks=follow_symlinks) == expected
    except OSError:
        return False


def _bootstrap_shape(executable: Path, version: str) -> tuple[Path, Path] | None:
    candidate = executable.absolute()
    if candidate.name != "python" or candidate.parent.name != "bin":
        return None
    venv = candidate.parent.parent
    install_root = venv.parent
    product_root = install_root.parent
    if venv.name != "venv" or install_root.name != version or product_root.name != "agentporter":
        return None
    return install_root, product_root


def _read_receipt(path: Path, *, version: str) -> tuple[bytes, tuple[Path, ...]] | None:
    try:
        identity = _identity(path)
        if not stat.S_ISREG(identity.mode) or path.stat().st_size > 4096:
            return None
        data = path.read_bytes()
        decoded: object = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    payload = cast(dict[str, object], decoded)
    if payload.get("product") != "agentporter":
        return None
    if payload.get("version") != version:
        return None
    schema = payload.get("schema_version")
    if schema == 1:
        if set(payload) != {"schema_version", "product", "version", "public_entry"}:
            return None
        legacy_entry = payload["public_entry"]
        if not isinstance(legacy_entry, str):
            return None
        raw: list[str] = [legacy_entry]
    elif schema == 2:
        if set(payload) != {"schema_version", "product", "version", "public_entries"}:
            return None
        raw_value = payload["public_entries"]
        if not isinstance(raw_value, list):
            return None
        raw_objects = cast(list[object], raw_value)
        if len(raw_objects) != 3 or not all(isinstance(value, str) for value in raw_objects):
            return None
        raw = [value for value in raw_objects if isinstance(value, str)]
    else:
        return None
    if not all(Path(value).is_absolute() for value in raw):
        return None
    entries = tuple(Path(value) for value in raw)
    if schema == 2 and tuple(path.name for path in entries) != _ENTRY_NAMES:
        return None
    if len(set(entries)) != len(entries) or len({path.parent for path in entries}) != 1:
        return None
    return data, entries


def build_bootstrap_cleanup_plan(
    *, executable: Path, version: str, env: Mapping[str, str]
) -> BootstrapCleanupPlan:
    """Seal the exact bootstrap installation owning the current interpreter."""
    del env
    shape = _bootstrap_shape(executable, version)
    if shape is None:
        return BootstrapCleanupPlan(CleanupPlanStatus.NOT_BOOTSTRAP_INSTALL)
    install_root, product_root = shape
    interpreter = install_root / "venv" / "bin" / "python"
    receipt = install_root / _RECEIPT
    quarantine = product_root / f".{version}.uninstalling-{os.getpid()}"
    parsed = _read_receipt(receipt, version=version)
    if parsed is None:
        return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
    receipt_bytes, public_entries = parsed
    private_entries = tuple(install_root / "venv" / "bin" / path.name for path in public_entries)
    public_entry = public_entries[-1]
    private_entry = private_entries[-1]
    link_quarantines = tuple(
        install_root / f".{path.name}.removing-{os.getpid()}" for path in public_entries
    )
    try:
        if (
            executable.absolute() != interpreter
            or not install_root.is_dir()
            or install_root.is_symlink()
        ):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not interpreter.is_file() or quarantine.exists() or quarantine.is_symlink():
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        for public, private, link_quarantine in zip(
            public_entries, private_entries, link_quarantines, strict=True
        ):
            if (
                not private.is_file()
                or private.is_symlink()
                or not public.is_symlink()
                or Path(os.readlink(public)) != private
                or link_quarantine.exists()
                or link_quarantine.is_symlink()
            ):
                return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        install_identity = _identity(install_root)
        interpreter_identity = _identity(interpreter, follow_symlinks=True)
        receipt_identity = _identity(receipt)
        entry_identities = tuple(_identity(path) for path in private_entries)
        link_identities = tuple(_identity(path) for path in public_entries)
        if not stat.S_ISDIR(install_identity.mode) or not stat.S_ISREG(interpreter_identity.mode):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not stat.S_ISREG(receipt_identity.mode):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not all(stat.S_ISREG(item.mode) for item in entry_identities):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not all(stat.S_ISLNK(item.mode) for item in link_identities):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
    except OSError:
        return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
    return BootstrapCleanupPlan(
        status=CleanupPlanStatus.READY,
        install_root=install_root,
        product_root=product_root,
        public_entry=public_entry,
        interpreter=interpreter,
        private_entry=private_entry,
        receipt=receipt,
        quarantine=quarantine,
        link_quarantine=link_quarantines[-1],
        install_identity=install_identity,
        interpreter_identity=interpreter_identity,
        entry_identity=entry_identities[-1],
        receipt_identity=receipt_identity,
        link_identity=link_identities[-1],
        receipt_bytes=receipt_bytes,
        public_entries=public_entries,
        private_entries=private_entries,
        entry_identities=entry_identities,
        link_identities=link_identities,
        link_quarantines=link_quarantines,
    )


def _plan_unchanged(plan: BootstrapCleanupPlan) -> bool:
    assert plan.install_root and plan.interpreter and plan.receipt and plan.quarantine
    assert plan.install_identity and plan.interpreter_identity and plan.receipt_identity
    assert plan.receipt_bytes is not None
    if not (
        _same_identity(plan.install_root, plan.install_identity)
        and _same_identity(plan.interpreter, plan.interpreter_identity, follow_symlinks=True)
        and _same_identity(plan.receipt, plan.receipt_identity)
        and plan.receipt.read_bytes() == plan.receipt_bytes
        and not os.path.lexists(plan.quarantine)
    ):
        return False
    for public, private, entry_identity, link_identity, link_quarantine in zip(
        plan.public_entries,
        plan.private_entries,
        plan.entry_identities,
        plan.link_identities,
        plan.link_quarantines,
        strict=True,
    ):
        if not (
            _same_identity(private, entry_identity)
            and _same_identity(public, link_identity)
            and public.is_symlink()
            and Path(os.readlink(public)) == private
            and not os.path.lexists(link_quarantine)
        ):
            return False
    return True


def execute_cleanup_plan(plan: BootstrapCleanupPlan) -> None:
    """Revalidate, isolate all receipt-owned entries, and remove the exact package."""
    if plan.status is not CleanupPlanStatus.READY:
        raise RuntimeError("AgentPorter package cleanup plan is not ready")
    if not plan.public_entries or not _plan_unchanged(plan):
        raise RuntimeError("AgentPorter package cleanup authority changed")
    assert plan.install_root and plan.product_root and plan.quarantine
    assert plan.install_identity and plan.receipt_identity
    moved: list[tuple[Path, Path]] = []
    try:
        for public, private, identity, link_quarantine in zip(
            plan.public_entries,
            plan.private_entries,
            plan.link_identities,
            plan.link_quarantines,
            strict=True,
        ):
            public.rename(link_quarantine)
            if not (
                _same_identity(link_quarantine, identity)
                and link_quarantine.is_symlink()
                and Path(os.readlink(link_quarantine)) == private
            ):
                if os.path.lexists(link_quarantine) and not os.path.lexists(public):
                    link_quarantine.rename(public)
                label = "public uninstall entry" if public == plan.public_entry else "public entry"
                raise RuntimeError(f"AgentPorter {label} changed during isolation")
            moved.append((public, link_quarantine))
        plan.install_root.rename(plan.quarantine)
        if not _same_identity(plan.quarantine, plan.install_identity):
            raise RuntimeError("AgentPorter isolated package identity changed")
        isolated_receipt = plan.quarantine / _RECEIPT
        if not (
            _same_identity(isolated_receipt, plan.receipt_identity)
            and isolated_receipt.read_bytes() == plan.receipt_bytes
        ):
            raise RuntimeError("AgentPorter isolated package identity changed")
        for private, identity, link_quarantine, link_identity in zip(
            plan.private_entries,
            plan.entry_identities,
            plan.link_quarantines,
            plan.link_identities,
            strict=True,
        ):
            relative_private = plan.quarantine / private.relative_to(plan.install_root)
            isolated_link = plan.quarantine / link_quarantine.name
            if not (
                _same_identity(relative_private, identity)
                and _same_identity(isolated_link, link_identity)
                and isolated_link.is_symlink()
                and Path(os.readlink(isolated_link)) == private
            ):
                raise RuntimeError("AgentPorter isolated package identity changed")
        shutil.rmtree(plan.quarantine)
        with suppress(OSError):
            plan.product_root.rmdir()
    except BaseException:
        root_isolated = os.path.lexists(plan.quarantine)
        restore_safe = not os.path.lexists(plan.install_root)
        if root_isolated:
            restore_safe = restore_safe and _same_identity(plan.quarantine, plan.install_identity)
        for public, link_quarantine in moved:
            index = plan.public_entries.index(public)
            restore_safe = restore_safe and (
                not os.path.lexists(public)
                and _same_identity(link_quarantine, plan.link_identities[index])
                and link_quarantine.is_symlink()
                and Path(os.readlink(link_quarantine)) == plan.private_entries[index]
            )
        if restore_safe:
            if root_isolated:
                plan.quarantine.rename(plan.install_root)
            for public, link_quarantine in reversed(moved):
                link_quarantine.rename(public)
        raise
