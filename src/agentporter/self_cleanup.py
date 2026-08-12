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

_RECEIPT = "bootstrap-install.json"


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


def _read_receipt(path: Path, *, version: str) -> tuple[bytes, Path] | None:
    try:
        identity = _identity(path)
        if not stat.S_ISREG(identity.mode) or path.stat().st_size > 4096:
            return None
        data = path.read_bytes()
        payload = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if set(payload) != {"schema_version", "product", "version", "public_entry"}:
        return None
    if payload["schema_version"] != 1 or payload["product"] != "agentporter":
        return None
    if payload["version"] != version or not isinstance(payload["public_entry"], str):
        return None
    public_entry = Path(payload["public_entry"])
    if not public_entry.is_absolute():
        return None
    return data, public_entry


def build_bootstrap_cleanup_plan(
    *, executable: Path, version: str, env: Mapping[str, str]
) -> BootstrapCleanupPlan:
    """Seal the exact bootstrap installation owning the current interpreter."""
    del env  # provenance comes from the installed receipt, not mutable XDG variables
    shape = _bootstrap_shape(executable, version)
    if shape is None:
        return BootstrapCleanupPlan(CleanupPlanStatus.NOT_BOOTSTRAP_INSTALL)
    install_root, product_root = shape
    interpreter = install_root / "venv" / "bin" / "python"
    private_entry = install_root / "venv" / "bin" / "agentporter-uninstall"
    receipt = install_root / _RECEIPT
    quarantine = product_root / f".{version}.uninstalling-{os.getpid()}"

    parsed = _read_receipt(receipt, version=version)
    if parsed is None:
        return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
    receipt_bytes, public_entry = parsed
    link_quarantine = install_root / f".agentporter-uninstall.removing-{os.getpid()}"

    try:
        if executable.absolute() != interpreter:
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not install_root.is_dir() or install_root.is_symlink():
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not interpreter.is_file() or not private_entry.is_file() or private_entry.is_symlink():
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not public_entry.is_symlink() or Path(os.readlink(public_entry)) != private_entry:
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if quarantine.exists() or quarantine.is_symlink():
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if link_quarantine.exists() or link_quarantine.is_symlink():
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        install_identity = _identity(install_root)
        interpreter_identity = _identity(interpreter, follow_symlinks=True)
        entry_identity = _identity(private_entry)
        receipt_identity = _identity(receipt)
        link_identity = _identity(public_entry)
        if not stat.S_ISDIR(install_identity.mode):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not stat.S_ISREG(interpreter_identity.mode) or not stat.S_ISREG(entry_identity.mode):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
        if not stat.S_ISREG(receipt_identity.mode) or not stat.S_ISLNK(link_identity.mode):
            return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)
    except OSError:
        return BootstrapCleanupPlan(CleanupPlanStatus.UNSAFE)

    return BootstrapCleanupPlan(
        CleanupPlanStatus.READY,
        install_root,
        product_root,
        public_entry,
        interpreter,
        private_entry,
        receipt,
        quarantine,
        link_quarantine,
        install_identity,
        interpreter_identity,
        entry_identity,
        receipt_identity,
        link_identity,
        receipt_bytes,
    )


def execute_cleanup_plan(plan: BootstrapCleanupPlan) -> None:
    """Revalidate, atomically isolate, and remove one sealed bootstrap package."""
    if plan.status is not CleanupPlanStatus.READY:
        raise RuntimeError("AgentPorter package cleanup plan is not ready")
    values = tuple(vars(plan).values())[1:]
    if any(value is None for value in values):
        raise RuntimeError("AgentPorter package cleanup plan is incomplete")

    install_root = plan.install_root
    product_root = plan.product_root
    public_entry = plan.public_entry
    interpreter = plan.interpreter
    private_entry = plan.private_entry
    receipt = plan.receipt
    quarantine = plan.quarantine
    link_quarantine = plan.link_quarantine
    assert all(
        path is not None
        for path in (
            install_root,
            product_root,
            public_entry,
            interpreter,
            private_entry,
            receipt,
            quarantine,
            link_quarantine,
        )
    )
    assert install_root and product_root and public_entry and interpreter and private_entry
    assert receipt and quarantine and link_quarantine
    assert plan.install_identity and plan.interpreter_identity and plan.entry_identity
    assert plan.receipt_identity and plan.link_identity and plan.receipt_bytes is not None

    unchanged = (
        _same_identity(install_root, plan.install_identity)
        and _same_identity(interpreter, plan.interpreter_identity, follow_symlinks=True)
        and _same_identity(private_entry, plan.entry_identity)
        and _same_identity(receipt, plan.receipt_identity)
        and receipt.read_bytes() == plan.receipt_bytes
        and _same_identity(public_entry, plan.link_identity)
        and public_entry.is_symlink()
        and Path(os.readlink(public_entry)) == private_entry
        and not os.path.lexists(quarantine)
        and not os.path.lexists(link_quarantine)
    )
    if not unchanged:
        raise RuntimeError("AgentPorter package cleanup authority changed")

    public_entry.rename(link_quarantine)
    try:
        if not (
            _same_identity(link_quarantine, plan.link_identity)
            and link_quarantine.is_symlink()
            and Path(os.readlink(link_quarantine)) == private_entry
        ):
            raise RuntimeError("AgentPorter public uninstall entry changed during isolation")

        install_root.rename(quarantine)
        isolated_interpreter = quarantine / "venv" / "bin" / "python"
        isolated_entry = quarantine / "venv" / "bin" / "agentporter-uninstall"
        isolated_receipt = quarantine / _RECEIPT
        isolated_link = quarantine / link_quarantine.name
        if not (
            _same_identity(quarantine, plan.install_identity)
            and _same_identity(
                isolated_interpreter, plan.interpreter_identity, follow_symlinks=True
            )
            and _same_identity(isolated_entry, plan.entry_identity)
            and _same_identity(isolated_receipt, plan.receipt_identity)
            and isolated_receipt.read_bytes() == plan.receipt_bytes
            and _same_identity(isolated_link, plan.link_identity)
            and isolated_link.is_symlink()
            and Path(os.readlink(isolated_link)) == private_entry
        ):
            raise RuntimeError("AgentPorter isolated package identity changed")

        shutil.rmtree(quarantine)
        with suppress(OSError):
            product_root.rmdir()
    except BaseException:
        if quarantine.exists() and not install_root.exists():
            with suppress(OSError):
                quarantine.rename(install_root)
        if os.path.lexists(link_quarantine) and not os.path.lexists(public_entry):
            with suppress(OSError):
                link_quarantine.rename(public_entry)
        raise
