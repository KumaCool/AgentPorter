from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentporter.self_cleanup import (
    CleanupPlanStatus,
    build_bootstrap_cleanup_plan,
    execute_cleanup_plan,
)

VERSION = "0.1.5"


def _published_layout(tmp_path: Path, *, schema_version: int = 2) -> tuple[Path, Path, Path, Path]:
    data_home = tmp_path / "data"
    bin_home = tmp_path / "bin"
    install_root = data_home / "agentporter" / VERSION
    interpreter = install_root / "venv" / "bin" / "python"
    entry = install_root / "venv" / "bin" / "agentporter-uninstall"
    entry.parent.mkdir(parents=True)
    base_interpreter = tmp_path / "base-python"
    base_interpreter.write_text("python", encoding="utf-8")
    interpreter.symlink_to(base_interpreter)
    entry.write_text("entry", encoding="utf-8")
    public_entry = bin_home / "agentporter-uninstall"
    public_entry.parent.mkdir(parents=True)
    public_entries: list[Path] = []
    for name in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
        private = entry.parent / name
        if name != "agentporter-uninstall":
            private.write_text(name, encoding="utf-8")
        public = bin_home / name
        public.symlink_to(private)
        public_entries.append(public)
    payload = {
        "schema_version": 2,
        "product": "agentporter",
        "version": VERSION,
        "public_entries": [str(path) for path in public_entries],
    }
    if schema_version == 1:
        payload = {
            "schema_version": 1,
            "product": "agentporter",
            "version": VERSION,
            "public_entry": str(public_entry),
        }
    (install_root / "bootstrap-install.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return install_root, interpreter, entry, public_entry


def test_bootstrap_layout_builds_exact_version_cleanup_plan(tmp_path: Path) -> None:
    install_root, _, _, public_entry = _published_layout(tmp_path)

    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv" / "bin" / "python",
        version=VERSION,
        env={
            "HOME": str(tmp_path / "home"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_BIN_HOME": str(tmp_path / "bin"),
        },
    )

    assert plan.status is CleanupPlanStatus.READY
    assert plan.install_root == install_root
    assert plan.product_root == install_root.parent
    assert plan.public_entry == public_entry
    assert plan.public_entries == tuple(
        tmp_path / "bin" / name
        for name in ("agentporter", "agentporter-activate", "agentporter-uninstall")
    )


def test_bootstrap_layout_accepts_a_standard_venv_interpreter_symlink(tmp_path: Path) -> None:
    install_root, interpreter, _, _ = _published_layout(tmp_path)

    plan = build_bootstrap_cleanup_plan(
        executable=interpreter,
        version=VERSION,
        env={
            "HOME": str(tmp_path / "home"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_BIN_HOME": str(tmp_path / "bin"),
        },
    )

    assert interpreter.is_symlink()
    assert plan.status is CleanupPlanStatus.READY
    assert plan.install_root == install_root


def test_cleanup_plan_rejects_source_checkout_or_arbitrary_environment(tmp_path: Path) -> None:
    executable = tmp_path / "checkout" / ".venv" / "bin" / "agentporter-uninstall"
    executable.parent.mkdir(parents=True)
    executable.write_text("entry", encoding="utf-8")

    plan = build_bootstrap_cleanup_plan(
        executable=executable,
        version=VERSION,
        env={"HOME": str(tmp_path / "home")},
    )

    assert plan.status is CleanupPlanStatus.NOT_BOOTSTRAP_INSTALL


def test_bootstrap_shaped_tree_without_receipt_is_unsafe(tmp_path: Path) -> None:
    install_root, interpreter, _, _ = _published_layout(tmp_path)
    (install_root / "bootstrap-install.json").unlink()

    plan = build_bootstrap_cleanup_plan(
        executable=interpreter,
        version=VERSION,
        env={"HOME": str(tmp_path / "home")},
    )

    assert plan.status is CleanupPlanStatus.UNSAFE
    assert install_root.is_dir()


def test_cleanup_plan_rejects_replaced_public_entry(tmp_path: Path) -> None:
    install_root, _, _, public_entry = _published_layout(tmp_path)
    public_entry.unlink()
    public_entry.write_text("replacement", encoding="utf-8")

    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv" / "bin" / "python",
        version=VERSION,
        env={
            "HOME": str(tmp_path / "home"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_BIN_HOME": str(tmp_path / "bin"),
        },
    )

    assert plan.status is CleanupPlanStatus.UNSAFE


def test_execute_cleanup_removes_only_entry_exact_version_and_empty_product_root(
    tmp_path: Path,
) -> None:
    install_root, _, _, public_entry = _published_layout(tmp_path)
    other_version = install_root.parent / "9.9.9"
    other_version.mkdir()
    (other_version / "keep").write_text("keep", encoding="utf-8")
    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv" / "bin" / "python",
        version=VERSION,
        env={
            "HOME": str(tmp_path / "home"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_BIN_HOME": str(tmp_path / "bin"),
        },
    )

    execute_cleanup_plan(plan)

    assert not os.path.lexists(public_entry)
    assert not os.path.lexists(tmp_path / "bin" / "agentporter")
    assert not os.path.lexists(tmp_path / "bin" / "agentporter-activate")
    assert not install_root.exists()
    assert other_version.is_dir()
    assert install_root.parent.is_dir()


def test_execute_cleanup_refuses_identity_drift_after_plan(tmp_path: Path) -> None:
    install_root, _, _, public_entry = _published_layout(tmp_path)
    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv" / "bin" / "python",
        version=VERSION,
        env={
            "HOME": str(tmp_path / "home"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_BIN_HOME": str(tmp_path / "bin"),
        },
    )
    public_entry.unlink()
    public_entry.write_text("replacement", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed"):
        execute_cleanup_plan(plan)

    assert public_entry.is_file()
    assert install_root.is_dir()


def test_execute_cleanup_revalidates_the_directory_after_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, _, _, _ = _published_layout(tmp_path)
    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv" / "bin" / "python",
        version=VERSION,
        env={"HOME": str(tmp_path / "home")},
    )
    original_rename = Path.rename

    def replace_before_rename(path: Path, target: Path) -> Path:
        if path == install_root:
            moved = install_root.with_name("authorized-original")
            original_rename(path, moved)
            path.mkdir()
            (path / "do-not-delete").write_text("replacement", encoding="utf-8")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", replace_before_rename)

    with pytest.raises(RuntimeError, match="isolated package identity changed"):
        execute_cleanup_plan(plan)

    assert plan.link_quarantine is not None
    isolated_link = install_root.with_name("authorized-original") / plan.link_quarantine.name
    assert isolated_link.is_symlink()
    assert not install_root.exists()
    assert plan.quarantine is not None
    assert (plan.quarantine / "do-not-delete").is_file()


def test_public_entry_replacement_during_isolation_is_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, _, _, public_entry = _published_layout(tmp_path)
    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv" / "bin" / "python",
        version=VERSION,
        env={"HOME": str(tmp_path / "home")},
    )
    authorized_link = public_entry.with_name("authorized-link-moved")
    original_rename = Path.rename

    def replace_before_rename(path: Path, target: Path) -> Path:
        if path == public_entry:
            original_rename(path, authorized_link)
            path.write_text("replacement-victim", encoding="utf-8")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", replace_before_rename)

    with pytest.raises(RuntimeError, match="public uninstall entry changed"):
        execute_cleanup_plan(plan)

    assert public_entry.read_text(encoding="utf-8") == "replacement-victim"
    assert authorized_link.is_symlink()
    assert install_root.is_dir()


def test_cleanup_uses_receipt_when_xdg_environment_drifted(tmp_path: Path) -> None:
    install_root, interpreter, _, public_entry = _published_layout(tmp_path)

    plan = build_bootstrap_cleanup_plan(
        executable=interpreter,
        version=VERSION,
        env={
            "HOME": str(tmp_path / "other-home"),
            "XDG_DATA_HOME": str(tmp_path / "wrong-data"),
            "XDG_BIN_HOME": str(tmp_path / "wrong-bin"),
        },
    )

    assert plan.status is CleanupPlanStatus.READY
    assert plan.install_root == install_root
    assert plan.public_entry == public_entry


def test_v1_receipt_deletes_only_the_declared_legacy_entry(tmp_path: Path) -> None:
    _, interpreter, _, public_entry = _published_layout(tmp_path, schema_version=1)
    plan = build_bootstrap_cleanup_plan(executable=interpreter, version=VERSION, env={})

    assert plan.status is CleanupPlanStatus.READY
    execute_cleanup_plan(plan)

    assert not os.path.lexists(public_entry)
    assert os.path.lexists(tmp_path / "bin" / "agentporter")
    assert os.path.lexists(tmp_path / "bin" / "agentporter-activate")


def test_v2_receipt_rejects_wrong_or_reordered_entry_set(tmp_path: Path) -> None:
    install_root, interpreter, _, _ = _published_layout(tmp_path)
    receipt = install_root / "bootstrap-install.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["public_entries"].reverse()
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    plan = build_bootstrap_cleanup_plan(executable=interpreter, version=VERSION, env={})

    assert plan.status is CleanupPlanStatus.UNSAFE


def test_cleanup_does_not_restore_quarantine_over_rename_and_occupy_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, _, _, _ = _published_layout(tmp_path)
    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv/bin/python", version=VERSION, env={}
    )
    original_rename = Path.rename

    def occupy_after_isolation(path: Path, target: Path) -> Path:
        result = original_rename(path, target)
        if path == install_root:
            install_root.mkdir()
            (install_root / "external").write_text("keep", encoding="utf-8")
            raise RuntimeError("injected")
        return result

    monkeypatch.setattr(Path, "rename", occupy_after_isolation)

    with pytest.raises(RuntimeError, match="injected"):
        execute_cleanup_plan(plan)

    assert (install_root / "external").read_text(encoding="utf-8") == "keep"
    assert plan.quarantine is not None
    assert plan.quarantine.is_dir()


def test_cleanup_does_not_restore_same_target_replacement_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root, _, _, _ = _published_layout(tmp_path)
    plan = build_bootstrap_cleanup_plan(
        executable=install_root / "venv/bin/python", version=VERSION, env={}
    )
    first_public = plan.public_entries[0]
    first_quarantine = plan.link_quarantines[0]
    original_rename = Path.rename

    def replace_quarantine_before_second_move(path: Path, target: Path) -> Path:
        if path == plan.public_entries[1]:
            original_target = os.readlink(first_quarantine)
            first_quarantine.unlink()
            first_quarantine.symlink_to(original_target)
            raise RuntimeError("injected same-target replacement")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", replace_quarantine_before_second_move)

    with pytest.raises(RuntimeError, match="same-target replacement"):
        execute_cleanup_plan(plan)

    assert not os.path.lexists(first_public)
    assert first_quarantine.is_symlink()
    assert install_root.is_dir()
