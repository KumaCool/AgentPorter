from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "install.sh"
VERSION = "0.1.5"
PREVIOUS_VERSION = "0.1.4"
WHEEL_NAME = f"agentporter-{VERSION}-py3-none-any.whl"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_tools(
    tmp_path: Path, *, checksum: str, checksum_name: str = WHEEL_NAME
) -> tuple[Path, Path]:
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    _write_executable(
        tools / "curl",
        f"""#!/bin/sh
set -eu
printf 'curl-argv %s\n' "$*" >> "$CALL_LOG"
url=''
out=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift 2 ;;
    http*) url=$1; shift ;;
    *) shift ;;
  esac
done
printf 'curl %s\\n' "$url" >> "$CALL_LOG"
case "$url" in
  *.sha256) printf '%s  {checksum_name}\\n' "$FAKE_CHECKSUM" > "$out" ;;
  *) printf 'wheel-bytes' > "$out" ;;
esac
""",
    )
    _write_executable(
        tools / "mv",
        """#!/bin/sh
set -eu
/bin/mv "$@"
destination=''
for argument in "$@"; do destination=$argument; done
case "${AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE:-}:$destination" in
  install-root:*/0.1.5|old-quarantine:*/.0.1.4-upgrade-quarantine)
    kill -KILL "$PPID"
    ;;
  quarantine-removed:*/.0.1.4-upgrade-quarantine)
    if [ ! -e "$destination" ]; then kill -KILL "$PPID"; fi
    ;;
  prepared:*/.0.1.5-upgrade-journal)
    if grep -q '"state": "PREPARED"' "$destination"; then kill -KILL "$PPID"; fi
    ;;
esac
""",
    )
    _write_executable(
        tools / "rm",
        """#!/bin/sh
set -eu
destination=''
for argument in "$@"; do destination=$argument; done
/bin/rm "$@"
case "${AGENTPORTER_TEST_INTERRUPT_AFTER_REMOVE:-}:$destination" in
  quarantine:*/.0.1.4-upgrade-quarantine) kill -KILL "$PPID" ;;
esac
""",
    )
    real_python = Path(sys.executable)
    _write_executable(
        tools / "python3",
        """#!/bin/sh
set -eu
printf 'python3 %s\n' "$*" >> "$CALL_LOG"
if [ "${1-}" = '-c' ]; then
  case "$2" in
    *hashlib*) printf '%s\n' "$FAKE_ACTUAL_CHECKSUM" ;;
    *"import agentporter"*) printf '{VERSION}\n' ;;
    *) exec {REAL_PYTHON} "$@" ;;
  esac
  exit 0
fi
if [ "${1-}" = '-m' ] && [ "${2-}" = 'venv' ]; then
  mkdir -p "$3/bin"
  cat > "$3/bin/python" <<'EOF'
#!/bin/sh
set -eu
printf 'venv-python %s\n' "$*" >> "$CALL_LOG"
if [ "${1-}" = '-m' ] && [ "${2-}" = 'pip' ]; then
  case " $* " in
    *' --force-reinstall '*)
      venv_bin=$(dirname "$0")
      for entry in agentporter agentporter-activate agentporter-uninstall; do
        body=$(sed -n '2,$p' "$venv_bin/$entry")
        printf '#!%s/python\n%s\n' "$venv_bin" "$body" > "$venv_bin/$entry"
        chmod +x "$venv_bin/$entry"
      done
      ;;
  esac
  exit 0
fi
if [ "${1-}" = '-c' ]; then printf '{VERSION}\n'; exit 0; fi
case "${1-}" in
  */bin/agentporter|*/bin/agentporter-uninstall) exec /usr/bin/python3 "$@" ;;
esac
exit 0
EOF
  chmod +x "$3/bin/python"
  printf '#!%s/bin/python\n' "$3" > "$3/bin/agentporter"
  cat >> "$3/bin/agentporter" <<'EOF'
import os
from pathlib import Path
Path(os.environ["CALL_LOG"]).open("a", encoding="utf-8").write("agentporter \\n")
raise SystemExit(int(os.environ.get("AGENTPORTER_EXIT_CODE", "0")))
EOF
  chmod +x "$3/bin/agentporter"
  printf '#!%s/bin/python\n' "$3" > "$3/bin/agentporter-activate"
  cat >> "$3/bin/agentporter-activate" <<'EOF'
raise SystemExit(0)
EOF
  chmod +x "$3/bin/agentporter-activate"
  printf '#!%s/bin/python\n' "$3" > "$3/bin/agentporter-uninstall"
  cat >> "$3/bin/agentporter-uninstall" <<'EOF'
raise SystemExit(0)
EOF
  chmod +x "$3/bin/agentporter-uninstall"
  exit 0
fi
exit 1
""".replace("{VERSION}", VERSION).replace("{REAL_PYTHON}", str(real_python)),
    )
    return tools, log


def _run(
    tmp_path: Path, *, checksum: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    tools, log = _fake_tools(tmp_path, checksum=checksum)
    input_device = tmp_path / "input"
    input_device.write_text("CONFIRM\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{tools}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_BIN_HOME": str(tmp_path / "bin"),
        "CALL_LOG": str(log),
        "FAKE_CHECKSUM": checksum,
        "FAKE_ACTUAL_CHECKSUM": hashlib.sha256(b"wheel-bytes").hexdigest(),
        "AGENTPORTER_BOOTSTRAP_TESTING": "1",
        "AGENTPORTER_TEST_INPUT_DEVICE": str(input_device),
        **(extra_env or {}),
    }
    return subprocess.run(
        ["/bin/sh", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_bootstrap_downloads_verifies_installs_and_runs(tmp_path: Path) -> None:
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    result = _run(tmp_path, checksum=checksum)

    assert result.returncode == 0, result.stderr
    install_root = tmp_path / "data" / "agentporter" / VERSION
    assert (install_root / "venv" / "bin" / "agentporter").is_file()
    uninstall = tmp_path / "bin" / "agentporter-uninstall"
    for entry in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
        public_entry = tmp_path / "bin" / entry
        assert public_entry.is_symlink()
        assert public_entry.resolve() == install_root / "venv" / "bin" / entry
    receipt = json.loads((install_root / "bootstrap-install.json").read_text(encoding="utf-8"))
    assert receipt == {
        "schema_version": 2,
        "product": "agentporter",
        "version": VERSION,
        "public_entries": [
            str(tmp_path / "bin" / "agentporter"),
            str(tmp_path / "bin" / "agentporter-activate"),
            str(uninstall),
        ],
    }
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert (
        f"https://github.com/KumaCool/AgentPorter/releases/download/v{VERSION}/{WHEEL_NAME}"
        in calls
    )
    assert (
        f"https://github.com/KumaCool/AgentPorter/releases/download/v{VERSION}/{WHEEL_NAME}.sha256"
        in calls
    )
    assert "-m pip install --disable-pip-version-check" in calls
    assert "--force-reinstall" not in calls
    assert calls.count("curl ") == 2
    curl_argv = [line for line in calls.splitlines() if line.startswith("curl-argv ")]
    assert len(curl_argv) == 2
    assert all("--connect-timeout 15" in line for line in curl_argv)
    assert all("--retry 3" in line for line in curl_argv)
    assert all("--retry-delay 2" in line for line in curl_argv)
    assert all("--retry-all-errors" not in line for line in curl_argv)
    assert "agentporter \n" in calls
    for entry in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
        shebang = (
            (install_root / "venv" / "bin" / entry).read_text(encoding="utf-8").splitlines()[0]
        )
        assert shebang == f"#!{install_root}/venv/bin/python"
    assert "configuration-required" in result.stdout
    assert "agentporter-activate" in result.stdout


def test_bootstrap_preflights_all_public_entries_before_writing_any(tmp_path: Path) -> None:
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()
    occupied = tmp_path / "bin" / "agentporter-activate"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("user-owned", encoding="utf-8")

    result = _run(tmp_path, checksum=checksum)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert occupied.read_text(encoding="utf-8") == "user-owned"
    assert not os.path.lexists(tmp_path / "bin" / "agentporter")
    assert not os.path.lexists(tmp_path / "bin" / "agentporter-uninstall")
    assert "curl " not in (tmp_path / "calls.log").read_text(encoding="utf-8")


def test_documentation_uses_unversioned_latest_bootstrap_url() -> None:
    for name in (
        "README.md",
        "README.zh-CN.md",
        "docs/04-installation-and-troubleshooting.md",
        "docs/04-installation-and-troubleshooting.zh-CN.md",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh" in text
        assert "raw.githubusercontent.com/KumaCool/AgentPorter/" not in text


def test_bootstrap_rejects_bad_checksum_before_creating_venv(tmp_path: Path) -> None:
    result = _run(tmp_path, checksum="0" * 64)

    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    assert not (tmp_path / "data" / "agentporter" / VERSION / "venv").exists()


def test_bootstrap_requires_terminal_before_creating_paths(tmp_path: Path) -> None:
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    result = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INPUT_DEVICE": str(tmp_path / "missing")},
    )

    assert result.returncode != 0
    assert "interactive terminal" in result.stderr
    assert not (tmp_path / "data").exists()
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "curl " not in calls


def test_bootstrap_rejects_checksum_for_wrong_wheel_name(tmp_path: Path) -> None:
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()
    tools, log = _fake_tools(tmp_path, checksum=checksum, checksum_name="other.whl")
    input_device = tmp_path / "input"
    input_device.write_text("CONFIRM\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{tools}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_BIN_HOME": str(tmp_path / "bin"),
        "CALL_LOG": str(log),
        "FAKE_CHECKSUM": checksum,
        "FAKE_ACTUAL_CHECKSUM": hashlib.sha256(b"wheel-bytes").hexdigest(),
        "AGENTPORTER_BOOTSTRAP_TESTING": "1",
        "AGENTPORTER_TEST_INPUT_DEVICE": str(input_device),
    }

    result = subprocess.run(
        ["/bin/sh", str(SCRIPT)], env=env, text=True, capture_output=True, check=False
    )

    assert result.returncode != 0
    assert "wrong wheel" in result.stderr
    assert not (tmp_path / "data" / "agentporter" / VERSION / "venv").exists()


def test_bootstrap_refuses_existing_install_without_downloading(tmp_path: Path) -> None:
    existing = tmp_path / "data" / "agentporter" / VERSION
    existing.mkdir(parents=True)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    result = _run(tmp_path, checksum=checksum)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "curl " not in calls


def test_bootstrap_preserves_uninstaller_when_product_install_fails(tmp_path: Path) -> None:
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    result = _run(tmp_path, checksum=checksum, extra_env={"AGENTPORTER_EXIT_CODE": "1"})

    assert result.returncode != 0
    assert (tmp_path / "bin" / "agentporter-uninstall").is_symlink()
    assert "kept for diagnosis" in result.stderr


def test_bootstrap_upgrades_v1_install_and_preserves_external_profile_bytes(tmp_path: Path) -> None:
    old_root = tmp_path / "data" / "agentporter" / PREVIOUS_VERSION
    old_private = old_root / "venv" / "bin" / "agentporter-uninstall"
    old_private.parent.mkdir(parents=True)
    old_private.write_text("old-uninstaller", encoding="utf-8")
    old_public = tmp_path / "bin" / "agentporter-uninstall"
    old_public.parent.mkdir(parents=True)
    old_public.symlink_to(old_private)
    (old_root / "bootstrap-install.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "agentporter",
                "version": PREVIOUS_VERSION,
                "public_entry": str(old_public),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    profile = tmp_path / "home" / ".hermes" / "profiles" / "worker" / "config.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"provider: fixture\n")
    before = (profile.read_bytes(), profile.stat().st_mtime_ns)

    result = _run(tmp_path, checksum=hashlib.sha256(b"wheel-bytes").hexdigest())

    assert result.returncode == 0, result.stderr
    assert not old_root.exists()
    assert profile.read_bytes() == before[0]
    assert profile.stat().st_mtime_ns == before[1]
    for name in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
        assert (tmp_path / "bin" / name).resolve().is_file()


def _seed_v1_upgrade(tmp_path: Path) -> tuple[Path, Path]:
    old_root = tmp_path / "data" / "agentporter" / PREVIOUS_VERSION
    old_private = old_root / "venv" / "bin" / "agentporter-uninstall"
    old_private.parent.mkdir(parents=True)
    old_private.write_text("old-uninstaller", encoding="utf-8")
    old_public = tmp_path / "bin" / "agentporter-uninstall"
    old_public.parent.mkdir(parents=True)
    old_public.symlink_to(old_private)
    (old_root / "bootstrap-install.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "agentporter",
                "version": PREVIOUS_VERSION,
                "public_entry": str(old_public),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return old_root, old_public


@pytest.mark.parametrize(
    "state",
    [
        "PREPARED",
        "STAGED_015_VERIFIED",
        "RECEIPT_V2_STAGED",
        "AGENTPORTER_PUBLISHED",
        "ACTIVATE_PUBLISHED",
        "UNINSTALLER_SWITCHED",
        "ENTRY_SET_READBACK_PASSED",
        "RECEIPT_V2_COMMITTED",
        "OLD_014_QUARANTINED",
    ],
)
def test_upgrade_journal_compensates_each_failure_state(tmp_path: Path, state: str) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)

    result = _run(
        tmp_path,
        checksum=hashlib.sha256(b"wheel-bytes").hexdigest(),
        extra_env={"AGENTPORTER_BOOTSTRAP_FAIL_AFTER_STATE": state},
    )

    assert result.returncode != 0
    assert "compensated" in result.stderr
    assert old_root.is_dir()
    assert old_public.is_symlink()
    assert old_public.resolve() == old_root / "venv" / "bin" / "agentporter-uninstall"
    assert not os.path.lexists(tmp_path / "bin" / "agentporter")
    assert not os.path.lexists(tmp_path / "bin" / "agentporter-activate")
    assert not (tmp_path / "data" / "agentporter" / VERSION).exists()
    assert not (tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal").exists()


def test_upgrade_compensation_preserves_occupied_drift_and_reports_partial(tmp_path: Path) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)

    result = _run(
        tmp_path,
        checksum=hashlib.sha256(b"wheel-bytes").hexdigest(),
        extra_env={"AGENTPORTER_BOOTSTRAP_DRIFT_AFTER_STATE": "UNINSTALLER_SWITCHED"},
    )

    assert result.returncode != 0
    assert "partial/mixed" in result.stderr
    assert old_public.read_text(encoding="utf-8") == "external-occupant"
    assert old_root.is_dir()
    assert (tmp_path / "data" / "agentporter" / VERSION).is_dir()
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "UNINSTALLER_SWITCHED"


@pytest.mark.parametrize(
    "point",
    [
        "after-install-root-rename",
        "after-agentporter-link",
        "after-agentporter-activate-link",
        "after-agentporter-uninstall-link",
        "before-agentporter-readback",
        "before-agentporter-activate-readback",
        "before-agentporter-uninstall-readback",
    ],
)
def test_fresh_install_is_one_compensating_entry_set(tmp_path: Path, point: str) -> None:
    result = _run(
        tmp_path,
        checksum=hashlib.sha256(b"wheel-bytes").hexdigest(),
        extra_env={"AGENTPORTER_BOOTSTRAP_FAIL_AT": point},
    )

    assert result.returncode != 0
    assert not (tmp_path / "data" / "agentporter" / VERSION).exists()
    for name in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
        assert not os.path.lexists(tmp_path / "bin" / name)
    assert not (tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal").exists()


def test_upgrade_journal_seals_authority_and_per_entry_objects(tmp_path: Path) -> None:
    _seed_v1_upgrade(tmp_path)
    result = _run(
        tmp_path,
        checksum=hashlib.sha256(b"wheel-bytes").hexdigest(),
        extra_env={"AGENTPORTER_BOOTSTRAP_DRIFT_AFTER_STATE": "UNINSTALLER_SWITCHED"},
    )

    assert result.returncode != 0
    journal = json.loads(
        (tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal").read_text(encoding="utf-8")
    )
    assert journal["schema_version"] == 2
    assert journal["old_root"]["type"] == "directory"
    assert journal["old_receipt"]["sha256"]
    assert journal["old_uninstaller"]["type"] == "file"
    assert journal["old_uninstaller"]["sha256"]
    assert [item["name"] for item in journal["entries"]] == [
        "agentporter",
        "agentporter-activate",
        "agentporter-uninstall",
    ]
    assert all({"device", "inode", "type", "target"} <= set(item) for item in journal["entries"])


def test_restart_recovers_prepared_upgrade_without_a_published_new_root(tmp_path: Path) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "prepared"},
    )
    assert interrupted.returncode == -9

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode != 0
    assert "recovered interrupted upgrade" in restarted.stderr
    assert old_root.is_dir()
    assert old_public.is_symlink()
    assert not (tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal").exists()


def test_restart_recovers_interrupted_upgrade_before_existing_root_preflight(
    tmp_path: Path,
) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "install-root"},
    )

    assert interrupted.returncode == -9
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "RECEIPT_V2_STAGED"
    assert (tmp_path / "data" / "agentporter" / VERSION).is_dir()

    restarted = _run(tmp_path, checksum="0" * 64)

    assert restarted.returncode != 0
    assert "recovered interrupted upgrade" in restarted.stderr
    assert "installation path already exists" not in restarted.stderr
    assert old_root.is_dir()
    assert old_public.is_symlink()
    assert old_public.resolve() == old_root / "venv" / "bin" / "agentporter-uninstall"
    assert not (tmp_path / "data" / "agentporter" / VERSION).exists()
    assert not journal.exists()


def test_restart_safely_completes_committed_upgrade_interrupted_during_old_quarantine(
    tmp_path: Path,
) -> None:
    old_root, _ = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "old-quarantine"},
    )

    assert interrupted.returncode == -9
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "RECEIPT_V2_COMMITTED"
    assert not old_root.exists()
    quarantine = tmp_path / "data" / "agentporter" / ".0.1.4-upgrade-quarantine"
    assert quarantine.is_dir()
    calls_before = (tmp_path / "calls.log").read_text(encoding="utf-8").count("curl ")

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode == 0, restarted.stderr
    assert "completed interrupted upgrade" in restarted.stderr
    assert not journal.exists()
    assert not quarantine.exists()
    assert (tmp_path / "data" / "agentporter" / VERSION).is_dir()
    assert (tmp_path / "calls.log").read_text(encoding="utf-8").count("curl ") == calls_before


def test_restart_safely_completes_committed_upgrade_after_quarantine_was_removed(
    tmp_path: Path,
) -> None:
    old_root, _ = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()

    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_REMOVE": "quarantine"},
    )

    assert interrupted.returncode == -9
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "OLD_014_QUARANTINED"
    assert not old_root.exists()
    assert not (tmp_path / "data" / "agentporter" / ".0.1.4-upgrade-quarantine").exists()

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode == 0, restarted.stderr
    assert "completed interrupted upgrade" in restarted.stderr
    assert not journal.exists()
    assert (tmp_path / "data" / "agentporter" / VERSION).is_dir()


def test_restart_rejects_mixed_residue_without_changing_any_object(tmp_path: Path) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()
    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "install-root"},
    )
    assert interrupted.returncode == -9
    occupied = tmp_path / "bin" / "agentporter"
    occupied.write_text("external-occupant", encoding="utf-8")
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    journal_before = journal.read_bytes()
    new_root = tmp_path / "data" / "agentporter" / VERSION
    calls_before = (tmp_path / "calls.log").read_text(encoding="utf-8").count("curl ")

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode != 0
    assert "partial/mixed interrupted upgrade" in restarted.stderr
    assert (tmp_path / "calls.log").read_text(encoding="utf-8").count("curl ") == calls_before
    assert occupied.read_text(encoding="utf-8") == "external-occupant"
    assert old_root.is_dir()
    assert old_public.is_symlink()
    assert new_root.is_dir()
    assert journal.read_bytes() == journal_before


def test_restart_does_not_delete_uncommitted_external_install_root_replacement(
    tmp_path: Path,
) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()
    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "install-root"},
    )
    assert interrupted.returncode == -9
    new_root = tmp_path / "data" / "agentporter" / VERSION
    displaced = new_root.with_name("displaced-authorized-root")
    new_root.rename(displaced)
    shutil.copytree(displaced, new_root)
    marker = new_root / "external-replacement"
    marker.write_bytes(b"must survive")
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    journal_before = journal.read_bytes()

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode != 0
    assert "partial/mixed interrupted upgrade" in restarted.stderr
    assert marker.read_bytes() == b"must survive"
    assert old_root.is_dir()
    assert old_public.is_symlink()
    assert journal.read_bytes() == journal_before


@pytest.mark.parametrize(
    "drift",
    ["old-root", "old-receipt", "old-uninstaller", "public-entry", "new-root", "new-receipt"],
)
def test_restart_fails_closed_on_every_sealed_object_drift_without_writes(
    tmp_path: Path, drift: str
) -> None:
    old_root, old_public = _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()
    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "install-root"},
    )
    assert interrupted.returncode == -9
    new_root = tmp_path / "data" / "agentporter" / VERSION
    if drift == "old-root":
        moved = old_root.with_name("moved-old-root")
        old_root.rename(moved)
        shutil.copytree(moved, old_root)
    elif drift == "old-receipt":
        old_root.joinpath("bootstrap-install.json").write_bytes(b"external receipt")
    elif drift == "old-uninstaller":
        old_root.joinpath("venv/bin/agentporter-uninstall").write_bytes(b"external uninstaller")
    elif drift == "public-entry":
        old_public.unlink()
        old_public.write_bytes(b"external entry")
    elif drift == "new-root":
        moved = new_root.with_name("moved-new-root")
        new_root.rename(moved)
        shutil.copytree(moved, new_root)
    else:
        new_root.joinpath("bootstrap-install.json").write_bytes(b"external receipt")
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    journal_before = journal.read_bytes()
    watched = [old_root, old_public, new_root, journal]
    before = {
        path: (path.read_bytes() if path.is_file() and not path.is_symlink() else None)
        for path in watched
    }

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode != 0
    assert "partial/mixed interrupted upgrade" in restarted.stderr
    assert journal.read_bytes() == journal_before
    for path, content in before.items():
        assert os.path.lexists(path)
        if content is not None:
            assert path.read_bytes() == content


def test_committed_restart_rejects_same_target_public_link_replacement(tmp_path: Path) -> None:
    _seed_v1_upgrade(tmp_path)
    checksum = hashlib.sha256(b"wheel-bytes").hexdigest()
    interrupted = _run(
        tmp_path,
        checksum=checksum,
        extra_env={"AGENTPORTER_TEST_INTERRUPT_AFTER_MOVE": "old-quarantine"},
    )
    assert interrupted.returncode != 0
    public = tmp_path / "bin" / "agentporter"
    target = os.readlink(public)
    displaced = public.with_name("displaced-agentporter")
    public.rename(displaced)
    public.symlink_to(target)
    journal = tmp_path / "data" / "agentporter" / ".0.1.5-upgrade-journal"
    before = journal.read_bytes()

    restarted = _run(tmp_path, checksum=checksum)

    assert restarted.returncode != 0
    assert "partial/mixed" in restarted.stderr
    assert public.is_symlink()
    assert displaced.is_symlink()
    assert journal.read_bytes() == before
