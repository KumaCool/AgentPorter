from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "install.sh"
VERSION = "0.1.4"
WHEEL_NAME = f"agentporter-{VERSION}-py3-none-any.whl"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_tools(
    tmp_path: Path, *, checksum: str, checksum_name: str = WHEEL_NAME
) -> tuple[Path, Path]:
    tools = tmp_path / "tools"
    tools.mkdir()
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
        tools / "python3",
        """#!/bin/sh
set -eu
printf 'python3 %s\n' "$*" >> "$CALL_LOG"
if [ "${1-}" = '-c' ]; then
  case "$2" in
    *hashlib*) printf '%s\n' "$FAKE_ACTUAL_CHECKSUM" ;;
    *"import agentporter"*) printf '{VERSION}\n' ;;
    *) exec /usr/bin/python3 "$@" ;;
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
""".replace("{VERSION}", VERSION),
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
    assert uninstall.is_symlink()
    assert uninstall.resolve() == install_root / "venv" / "bin" / "agentporter-uninstall"
    receipt = json.loads((install_root / "bootstrap-install.json").read_text(encoding="utf-8"))
    assert receipt == {
        "schema_version": 1,
        "product": "agentporter",
        "version": VERSION,
        "public_entry": str(uninstall),
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
