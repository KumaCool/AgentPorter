#!/bin/sh
# AgentPorter v0.1.6 release-candidate bootstrap for POSIX systems.
set -eu

VERSION=0.1.6
PREVIOUS_VERSION=0.1.4
RELEASE_BASE_URL=https://github.com/KumaCool/AgentPorter/releases/download/v0.1.6
WHEEL=agentporter-0.1.6-py3-none-any.whl
CHECKSUM=${WHEEL}.sha256
ENTRY_POINTS='agentporter agentporter-activate agentporter-uninstall'
PACKAGED_RESOURCES='agentporter/resources/workers.yaml'
REQUIRED_MODULES='agentporter.activation_application agentporter.activation_entry agentporter.dispatch_application agentporter.dispatch_planning agentporter.hermes_runtime agentporter.kanban_runtime agentporter.readiness agentporter.runtime_authority agentporter.runtime_binding agentporter.runtime_observation agentporter.runtime_probe'

fail() {
    printf 'AgentPorter bootstrap: %s\n' "$*" >&2
    exit 1
}

command -v curl >/dev/null 2>&1 || fail 'curl is required'
command -v python3 >/dev/null 2>&1 || fail 'Python 3.11 or newer is required'
PYTHON=$(command -v python3)
"$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    || fail 'Python 3.11 or newer is required'

DATA_HOME=${XDG_DATA_HOME:-"${HOME:?HOME is required}/.local/share"}
BIN_HOME=${XDG_BIN_HOME:-"${HOME:?HOME is required}/.local/bin"}
PRODUCT_ROOT=${DATA_HOME}/agentporter
INSTALL_ROOT=${PRODUCT_ROOT}/${VERSION}
OLD_ROOT=${PRODUCT_ROOT}/${PREVIOUS_VERSION}
LEGACY_INSTALL_ROOT=${PRODUCT_ROOT}/0.1.5
PUBLIC_ENTRIES="${BIN_HOME}/agentporter ${BIN_HOME}/agentporter-activate ${BIN_HOME}/agentporter-uninstall"
UNINSTALL_LINK=${BIN_HOME}/agentporter-uninstall
JOURNAL=${PRODUCT_ROOT}/.0.1.5-upgrade-journal
OLD_QUARANTINE=${PRODUCT_ROOT}/.0.1.4-upgrade-quarantine
INPUT_DEVICE=/dev/tty
if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ]; then
    INPUT_DEVICE=${AGENTPORTER_TEST_INPUT_DEVICE:?test input device is required}
fi

recover_upgrade() {
    [ -e "$JOURNAL" ] || [ -L "$JOURNAL" ] || return 0
    recovery=$(
        "$PYTHON" -c 'import json, os, pathlib, shutil, stat, sys
journal, old_root, quarantine, install_root, bin_home = map(pathlib.Path, sys.argv[1:])
names = ("agentporter", "agentporter-activate", "agentporter-uninstall")
states = {"PREPARED", "STAGED_015_VERIFIED", "RECEIPT_V2_STAGED", "AGENTPORTER_PUBLISHED", "ACTIVATE_PUBLISHED", "UNINSTALLER_SWITCHED", "ENTRY_SET_READBACK_PASSED", "RECEIPT_V2_COMMITTED", "OLD_014_QUARANTINED"}
def reject(): raise SystemExit(1)
def observed(path):
    try: value = path.lstat()
    except OSError: return {"device": None, "inode": None, "type": "absent", "target": None}
    kind = "symlink" if stat.S_ISLNK(value.st_mode) else "directory" if stat.S_ISDIR(value.st_mode) else "file" if stat.S_ISREG(value.st_mode) else "other"
    return {"device": value.st_dev, "inode": value.st_ino, "type": kind, "target": os.readlink(path) if kind == "symlink" else None}
def sealed_matches(path, seal, *, target=False):
    value = observed(path)
    keys = ("device", "inode", "type") + (("target",) if target else ())
    return all(value[key] == seal[key] for key in keys)
try:
    info = journal.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 16384: reject()
    data = json.loads(journal.read_bytes())
except (OSError, ValueError, TypeError): reject()
if set(data) != {"schema_version", "from", "to", "state", "old_root", "old_receipt", "old_uninstaller", "new_root", "new_receipt", "entries"}: reject()
if data["schema_version"] != 2 or data["from"] != "0.1.4" or data["to"] != "0.1.5" or data["state"] not in states: reject()
for key in ("old_root", "old_receipt", "old_uninstaller", "new_root", "new_receipt"):
    if not isinstance(data[key], dict) or not {"device", "inode", "type", "target"} <= set(data[key]): reject()
if not isinstance(data["old_receipt"].get("sha256"), str) or not isinstance(data["old_uninstaller"].get("sha256"), str) or not isinstance(data["new_receipt"].get("sha256"), (str, type(None))): reject()
entries = data["entries"]
if not isinstance(entries, list) or [item.get("name") for item in entries if isinstance(item, dict)] != list(names): reject()
if any(set(item) != {"name", "device", "inode", "type", "target"} for item in entries): reject()
committed = data["state"] in {"RECEIPT_V2_COMMITTED", "OLD_014_QUARANTINED"}
quarantine_removed = data["state"] == "OLD_014_QUARANTINED" and not quarantine.exists()
legacy = quarantine if committed and quarantine.exists() else old_root
receipt = legacy / "bootstrap-install.json"
uninstaller = legacy / "venv/bin/agentporter-uninstall"
if not quarantine_removed:
    if not sealed_matches(legacy, data["old_root"]) or not sealed_matches(receipt, data["old_receipt"]): reject()
    try:
        if __import__("hash" + "lib").sha256(receipt.read_bytes()).hexdigest() != data["old_receipt"]["sha256"]: reject()
    except OSError: reject()
    if not sealed_matches(uninstaller, data["old_uninstaller"]): reject()
    try:
        if __import__("hash" + "lib").sha256(uninstaller.read_bytes()).hexdigest() != data["old_uninstaller"]["sha256"]: reject()
    except OSError: reject()
expected = {name: install_root / "venv/bin" / name for name in names}
for item in entries:
    public = bin_home / item["name"]
    current = observed(public)
    new = (current["type"] == "symlink"
           and current["target"] == str(expected[item["name"]])
           and (item["type"] != "symlink" or sealed_matches(public, item, target=True)))
    original = sealed_matches(public, item, target=item["type"] == "symlink")
    if committed:
        if not original: reject()
    elif not (new or original): reject()
receipt2 = install_root / "bootstrap-install.json"
install_present = install_root.exists() or install_root.is_symlink()
if install_present:
    if not sealed_matches(install_root, data["new_root"]) or not sealed_matches(receipt2, data["new_receipt"]): reject()
    try:
        receipt2_bytes = receipt2.read_bytes()
        installed = json.loads(receipt2_bytes)
    except (OSError, ValueError, TypeError): reject()
    if __import__("hash" + "lib").sha256(receipt2_bytes).hexdigest() != data["new_receipt"]["sha256"]: reject()
    if installed != {"schema_version": 2, "product": "agentporter", "version": "0.1.5", "public_entries": [str(bin_home / name) for name in names]}: reject()
    if not install_root.is_dir() or install_root.is_symlink(): reject()
if committed and not install_present: reject()
if committed:
    if any(observed(bin_home / name)["target"] != str(expected[name]) for name in names): reject()
    if old_root.exists() or (data["state"] == "RECEIPT_V2_COMMITTED" and legacy != quarantine): reject()
    if quarantine.exists(): shutil.rmtree(quarantine)
    journal.unlink()
    print("completed")
else:
    public_uninstaller = bin_home / "agentporter-uninstall"
    if observed(public_uninstaller)["target"] == str(expected["agentporter-uninstall"]):
        temporary = install_root / ".agentporter-uninstall.recovery"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(uninstaller)
        os.replace(temporary, public_uninstaller)
    for name in ("agentporter", "agentporter-activate"):
        public = bin_home / name
        if observed(public)["target"] == str(expected[name]): public.unlink()
    if install_present: shutil.rmtree(install_root)
    journal.unlink()
    print("recovered")' \
            "$JOURNAL" "$OLD_ROOT" "$OLD_QUARANTINE" "$LEGACY_INSTALL_ROOT" "$BIN_HOME"
    ) || fail 'partial/mixed interrupted upgrade; residue retained'
    case "$recovery" in
        completed)
            printf 'AgentPorter bootstrap: safely completed interrupted upgrade\n' >&2
            exit 0
            ;;
        recovered)
            fail 'recovered interrupted upgrade to 0.1.4; rerun the installer to retry'
            ;;
        *) fail 'partial/mixed interrupted upgrade; residue retained' ;;
    esac
}



# The 0.1.4 -> 0.1.5 journal recovery above intentionally remains unchanged and runs first.
recover_upgrade

# The v0.1.6 transaction helper is also shipped inside the wheel/sdist; the
# standalone checksum-verified copy below is the pre-install bootstrap asset.

PREVIOUS_VERSION=0.1.5
INSTALL_ROOT=${PRODUCT_ROOT}/${VERSION}
OLD_ROOT=${PRODUCT_ROOT}/${PREVIOUS_VERSION}
JOURNAL=${PRODUCT_ROOT}/.0.1.6-entry-transaction.json
SPEC=${PRODUCT_ROOT}/.0.1.6-entry-spec.json
TXN_HELPER=bootstrap_txn.py
TXN_HELPER_CHECKSUM=${TXN_HELPER}.sha256

recover_entry_transaction() {
    [ -e "$JOURNAL" ] || [ -L "$JOURNAL" ] || return 0
    [ -f "$SPEC" ] && [ ! -L "$SPEC" ] || fail 'partial/mixed interrupted 0.1.6 install; residue retained'
    [ -f "$INSTALL_ROOT/$TXN_HELPER" ] && [ ! -L "$INSTALL_ROOT/$TXN_HELPER" ] \
        || fail 'partial/mixed interrupted 0.1.6 install; residue retained'
    "$PYTHON" "$INSTALL_ROOT/$TXN_HELPER" recover "$SPEC" \
        || fail 'partial/mixed interrupted 0.1.6 install; residue retained'
    if [ -e "$JOURNAL" ] || [ -L "$JOURNAL" ]; then
        fail 'partial/mixed interrupted 0.1.6 install; residue retained'
    fi
    printf 'AgentPorter bootstrap: safely recovered interrupted 0.1.6 install\n' >&2
    exit 0
}

recover_entry_transaction

[ -r "$INPUT_DEVICE" ] || fail 'an interactive terminal is required'
[ ! -e "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ] \
    || fail "installation path already exists: ${INSTALL_ROOT}"

UPGRADE=0
if [ -d "$OLD_ROOT" ] && [ ! -L "$OLD_ROOT" ]; then
    "$PYTHON" -c 'import json,os,pathlib,sys
root,bin_home=map(pathlib.Path,sys.argv[1:]); receipt=root/"bootstrap-install.json"
try: data=json.loads(receipt.read_bytes())
except (OSError,ValueError,TypeError): raise SystemExit(1)
names=("agentporter","agentporter-activate","agentporter-uninstall")
expected={"schema_version":2,"product":"agentporter","version":"0.1.5","public_entries":[str(bin_home/name) for name in names]}
if data != expected or receipt.is_symlink() or not root.is_dir() or root.is_symlink(): raise SystemExit(1)
for name in names:
 public=bin_home/name; private=root/"venv/bin"/name
 if not public.is_symlink() or os.readlink(public) != str(private) or not private.is_file(): raise SystemExit(1)' \
        "$OLD_ROOT" "$BIN_HOME" || fail 'existing 0.1.5 installation is not safe to upgrade'
    UPGRADE=1
else
    for public_entry in $PUBLIC_ENTRIES; do
        [ ! -e "$public_entry" ] && [ ! -L "$public_entry" ] \
            || fail "public entry path already exists: ${public_entry}"
    done
fi

mkdir -p "$PRODUCT_ROOT" "$BIN_HOME" || fail 'could not create installation directories'
[ -d "$PRODUCT_ROOT" ] && [ ! -L "$PRODUCT_ROOT" ] || fail 'product installation parent must be a real directory'
[ -d "$BIN_HOME" ] && [ ! -L "$BIN_HOME" ] || fail 'binary installation parent must be a real directory'

STAGING=
PUBLISHED=0
cleanup() {
    status=$?
    if [ "$status" -ne 0 ] && [ "$PUBLISHED" -eq 0 ] && [ -n "$STAGING" ] \
            && [ -d "$STAGING" ] && [ ! -L "$STAGING" ]; then
        rm -rf "$STAGING"
    fi
    return "$status"
}
trap cleanup EXIT HUP INT TERM
STAGING=$(mktemp -d "${PRODUCT_ROOT}/.0.1.6-stage.XXXXXX") || fail 'could not create a private staging directory'
chmod 700 "$STAGING" || fail 'could not secure the staging directory'

printf 'Downloading AgentPorter v%s release artifacts...\n' "$VERSION"
CURL_ENV="env -i PATH=$PATH"
if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ]; then
    CURL_ENV="$CURL_ENV CALL_LOG=${CALL_LOG:?} FAKE_CHECKSUM=${FAKE_CHECKSUM:?} AGENTPORTER_TXN_HELPER_SOURCE=${AGENTPORTER_TXN_HELPER_SOURCE:?} REAL_PYTHON=${REAL_PYTHON:?}"
fi
for asset in "$WHEEL" "$CHECKSUM" "$TXN_HELPER" "$TXN_HELPER_CHECKSUM"; do
    # shellcheck disable=SC2086 -- fixed allowlisted environment words.
    $CURL_ENV curl --fail --location --proto '=https' --proto-redir '=https' \
        --tlsv1.2 --connect-timeout 15 --retry 3 --retry-delay 2 --silent --show-error \
        -o "$STAGING/$asset" "$RELEASE_BASE_URL/$asset" || fail "release asset download failed: $asset"
done

verify_checksum() {
    asset=$1; sidecar=$2
    expected=$(sed -n '1{s/[[:space:]].*$//;p;}' "$sidecar")
    listed=$(sed -n '1{s/^[^[:space:]]*[[:space:]][[:space:]]*[*]*//;p;}' "$sidecar")
    [ "$(wc -l < "$sidecar" | tr -d ' ')" -eq 1 ] || fail 'release checksum must contain exactly one record'
    case "$expected" in *[!0-9a-f]*|'') fail 'release checksum has an invalid format' ;; esac
    [ "${#expected}" -eq 64 ] || fail 'release checksum has an invalid length'
    [ "$listed" = "$(basename "$asset")" ] || fail 'release checksum names the wrong asset'
    actual=$("$PYTHON" -c 'import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1],"rb"),"sha256").hexdigest())' "$asset")
    [ "$actual" = "$expected" ] || fail 'release checksum verification failed'
}
verify_checksum "$STAGING/$WHEEL" "$STAGING/$CHECKSUM"
verify_checksum "$STAGING/$TXN_HELPER" "$STAGING/$TXN_HELPER_CHECKSUM"
chmod 700 "$STAGING/$TXN_HELPER"

VENV=${STAGING}/venv
"$PYTHON" -m venv "$VENV" || fail 'could not create the private virtual environment'
PIP_TEST_ENV=
[ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" != 1 ] || PIP_TEST_ENV="CALL_LOG=${CALL_LOG:?}"
# shellcheck disable=SC2086 -- fixed allowlisted test environment word.
env -i PATH="$PATH" HOME="$HOME" PIP_CONFIG_FILE=/dev/null PIP_REQUIRE_VIRTUALENV=1 $PIP_TEST_ENV \
    "$VENV/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: "$STAGING/$WHEEL" \
    || fail 'package installation failed'
for entry in $ENTRY_POINTS; do [ -x "$VENV/bin/$entry" ] || fail 'installed package is missing an entry point'; done
INSTALLED_VERSION=$("$VENV/bin/python" -c 'import agentporter; print(agentporter.__version__)') || fail 'could not read back installed version'
[ "$INSTALLED_VERSION" = "$VERSION" ] || fail 'installed package version does not match the release'
for resource in $PACKAGED_RESOURCES; do
    "$VENV/bin/python" -c 'from importlib.resources import files; import sys
package,relative=sys.argv[1].split("/",1); target=files(package).joinpath(relative)
raise SystemExit(not target.is_file() or not target.read_bytes())' "$resource" || fail 'installed package is missing a required packaged resource'
done
for module in $REQUIRED_MODULES; do
    "$VENV/bin/python" -c 'import importlib,sys; importlib.import_module(sys.argv[1])' "$module" || fail 'installed package is missing a required runtime module'
done
rm -f "$STAGING/$WHEEL" "$STAGING/$CHECKSUM" "$STAGING/$TXN_HELPER_CHECKSUM"
FINAL_VENV=${INSTALL_ROOT}/venv
for entry in $ENTRY_POINTS; do
    ENTRY=${VENV}/bin/${entry}
    "$PYTHON" -c 'from pathlib import Path; import sys
p=Path(sys.argv[1]); old=sys.argv[2].encode(); new=sys.argv[3].encode(); data=p.read_bytes()
if not data.startswith(old+b"\n"): raise SystemExit(1)
p.write_bytes(new+data[len(old):])' "$ENTRY" "#!${VENV}/bin/python" "#!${FINAL_VENV}/bin/python" \
        || fail 'could not bind package entry points to final path'
done
"$PYTHON" -c 'import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); p.write_text(json.dumps({"schema_version":2,"product":"agentporter","version":sys.argv[2],"public_entries":sys.argv[3:]},sort_keys=True)+"\n"); p.chmod(0o600)' \
    "$STAGING/bootstrap-install.json" "$VERSION" $PUBLIC_ENTRIES || fail 'could not write ownership receipt'
mv "$STAGING" "$INSTALL_ROOT" || fail 'could not publish verified installation root'
PUBLISHED=1

"$PYTHON" -c 'import json,pathlib,sys
out,mode,old_root,new_root,bin_home=map(pathlib.Path,sys.argv[1:])
names=("agentporter","agentporter-activate","agentporter-uninstall")
spec={"schema":2,"mode":str(mode),"old_root":str(old_root),"new_root":str(new_root),"old_receipt":str(old_root/"bootstrap-install.json"),"new_receipt":str(new_root/"bootstrap-install.json"),"journal":str(new_root.parent/".0.1.6-entry-transaction.json"),"entries":[]}
for name in names: spec["entries"].append({"name":name,"public":str(bin_home/name),"old_target":str(old_root/"venv/bin"/name) if str(mode)=="upgrade" else "","new_target":str(new_root/"venv/bin"/name)})
out.write_text(json.dumps(spec,sort_keys=True)+"\n"); out.chmod(0o600)' \
    "$SPEC" "$([ "$UPGRADE" -eq 1 ] && printf upgrade || printf fresh)" "$OLD_ROOT" "$INSTALL_ROOT" "$BIN_HOME"
"$PYTHON" "$INSTALL_ROOT/$TXN_HELPER" apply "$SPEC" || fail 'entry transaction failed; rerun installer for recovery'
for entry in $ENTRY_POINTS; do
    PUBLIC_ENTRY=$BIN_HOME/$entry
    [ -L "$PUBLIC_ENTRY" ] && [ "$(readlink "$PUBLIC_ENTRY")" = "$FINAL_VENV/bin/$entry" ] && [ -x "$PUBLIC_ENTRY" ] \
        || fail 'published entry-point readback failed'
done

printf '\nPackage installed and checksum verified. Starting the interactive AgentPorter plan.\n'
printf 'No Hermes Profile will be written until you review and confirm that plan.\n\n'
if "$FINAL_VENV/bin/python" "$FINAL_VENV/bin/agentporter" < "$INPUT_DEVICE"; then
    printf '\nStarting AgentPorter activation.\n\n'
    if "$FINAL_VENV/bin/python" "$FINAL_VENV/bin/agentporter-activate" < "$INPUT_DEVICE"; then
        printf '\nAgentPorter completed. Uninstall later with:\n  %s\n' "$UNINSTALL_LINK"
    else
        status=$?; printf '\nAgentPorter activation did not complete successfully.\n' >&2
        printf 'The installed Profiles and activation command were kept for retry:\n  %s\n' "$BIN_HOME/agentporter-activate" >&2
        exit "$status"
    fi
else
    status=$?; printf '\nAgentPorter did not complete successfully.\n' >&2
    printf 'The verified package and uninstaller were kept for diagnosis or cleanup:\n  %s\n' "$UNINSTALL_LINK" >&2
    exit "$status"
fi
