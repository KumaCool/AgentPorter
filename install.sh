#!/bin/sh
# AgentPorter v0.1.5 release-candidate bootstrap for POSIX systems.
set -eu

VERSION=0.1.5
PREVIOUS_VERSION=0.1.4
RELEASE_BASE_URL=https://github.com/KumaCool/AgentPorter/releases/download/v0.1.5
WHEEL=agentporter-0.1.5-py3-none-any.whl
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
PUBLIC_ENTRIES="${BIN_HOME}/agentporter ${BIN_HOME}/agentporter-activate ${BIN_HOME}/agentporter-uninstall"
UNINSTALL_LINK=${BIN_HOME}/agentporter-uninstall
JOURNAL=${PRODUCT_ROOT}/.0.1.5-upgrade-journal
OLD_QUARANTINE=${PRODUCT_ROOT}/.0.1.4-upgrade-quarantine
INPUT_DEVICE=/dev/tty
if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ]; then
    INPUT_DEVICE=${AGENTPORTER_TEST_INPUT_DEVICE:?test input device is required}
fi

[ -r "$INPUT_DEVICE" ] || fail 'an interactive terminal is required'
[ ! -e "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ] \
    || fail "installation path already exists: ${INSTALL_ROOT}"
UPGRADE=0
if [ -d "$OLD_ROOT" ] && [ ! -L "$OLD_ROOT" ]; then
    OLD_UNINSTALLER=${OLD_ROOT}/venv/bin/agentporter-uninstall
    OLD_RECEIPT=${OLD_ROOT}/bootstrap-install.json
    "$PYTHON" -c 'import json, os, pathlib, sys
receipt, public, private = map(pathlib.Path, sys.argv[1:])
expected = {"schema_version": 1, "product": "agentporter", "version": "0.1.4", "public_entry": str(public)}
if (not receipt.is_file() or receipt.is_symlink() or receipt.stat().st_size > 4096
        or json.loads(receipt.read_bytes()) != expected or not private.is_file()
        or private.is_symlink() or not public.is_symlink()
        or pathlib.Path(os.readlink(public)) != private):
    raise SystemExit(1)' "$OLD_RECEIPT" "$UNINSTALL_LINK" "$OLD_UNINSTALLER" \
        || fail 'existing 0.1.4 installation is not safe to upgrade'
    UPGRADE=1
fi
for public_entry in $PUBLIC_ENTRIES; do
    if [ "$UPGRADE" -eq 1 ] && [ "$public_entry" = "$UNINSTALL_LINK" ]; then
        continue
    fi
    [ ! -e "$public_entry" ] && [ ! -L "$public_entry" ] \
        || fail "public entry path already exists: ${public_entry}"
done

mkdir -p "$PRODUCT_ROOT" "$BIN_HOME" || fail 'could not create installation directories'
[ -d "$PRODUCT_ROOT" ] && [ ! -L "$PRODUCT_ROOT" ] \
    || fail 'product installation parent must be a real directory'
[ -d "$BIN_HOME" ] && [ ! -L "$BIN_HOME" ] \
    || fail 'binary installation parent must be a real directory'

STATE=
COMPENSATING=0
journal_state() {
    STATE=$1
    [ "$UPGRADE" -eq 1 ] || return 0
    tmp=${JOURNAL}.tmp.$$
    "$PYTHON" -c 'import json, os, pathlib, stat, sys
out, journal, state, old_root, old_receipt, old_uninstaller, bin_home, install_root = sys.argv[1:]
def seal(path, target=None):
    try: value = os.lstat(path)
    except OSError: return {"device": None, "inode": None, "type": "absent", "target": target}
    kind = "symlink" if stat.S_ISLNK(value.st_mode) else "directory" if stat.S_ISDIR(value.st_mode) else "file" if stat.S_ISREG(value.st_mode) else "other"
    return {"device": value.st_dev, "inode": value.st_ino, "type": kind, "target": os.readlink(path) if kind == "symlink" else target}
receipt = seal(old_receipt)
try: receipt["sha256"] = __import__("hash"+"lib").sha256(pathlib.Path(old_receipt).read_bytes()).hexdigest()
except OSError: receipt["sha256"] = None
entries = []
for name in ("agentporter", "agentporter-activate", "agentporter-uninstall"):
    expected = str(pathlib.Path(install_root) / "venv" / "bin" / name)
    entries.append({"name": name, **seal(str(pathlib.Path(bin_home) / name), expected)})
previous = {}
try: previous = json.loads(pathlib.Path(journal).read_text(encoding="utf-8"))
except (OSError, ValueError): pass
payload = {"schema_version": 2, "from": "0.1.4", "to": "0.1.5", "state": state,
           "old_root": previous.get("old_root", seal(old_root)),
           "old_receipt": previous.get("old_receipt", receipt),
           "old_uninstaller": previous.get("old_uninstaller", seal(old_uninstaller)),
           "entries": entries}
pathlib.Path(out).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")' \
        "$tmp" "$JOURNAL" "$STATE" "$OLD_ROOT" "$OLD_RECEIPT" "$OLD_UNINSTALLER" \
        "$BIN_HOME" "$INSTALL_ROOT"
    chmod 600 "$tmp"
    mv "$tmp" "$JOURNAL"
    if [ "${AGENTPORTER_BOOTSTRAP_FAIL_AFTER_STATE:-}" = "$STATE" ]; then
        fail "injected failure after upgrade state $STATE"
    fi
    if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ] \
            && [ "${AGENTPORTER_BOOTSTRAP_DRIFT_AFTER_STATE:-}" = "$STATE" ]; then
        case "$STATE" in
            UNINSTALLER_SWITCHED)
                rm "$UNINSTALL_LINK"
                printf 'external-occupant' > "$UNINSTALL_LINK"
                fail "authority drift after upgrade state $STATE"
                ;;
        esac
    fi
}
same_link() { [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]; }
fail_at() {
    if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ] \
            && [ "${AGENTPORTER_BOOTSTRAP_FAIL_AT:-}" = "$1" ]; then
        fail "injected failure at $1"
    fi
}
compensate_upgrade() {
    [ "$UPGRADE" -eq 1 ] || return 0
    [ "$STATE" != COMPLETE ] || return 0
    [ "$COMPENSATING" -eq 0 ] || return 1
    COMPENSATING=1
    safe=1
    new_uninstaller=${INSTALL_ROOT}/venv/bin/agentporter-uninstall
    if ! same_link "$UNINSTALL_LINK" "$new_uninstaller" \
            && ! same_link "$UNINSTALL_LINK" "$OLD_UNINSTALLER"; then safe=0; fi
    for entry in agentporter-activate agentporter; do
        public=${BIN_HOME}/${entry}; expected=${INSTALL_ROOT}/venv/bin/${entry}
        if ! same_link "$public" "$expected" \
                && { [ -e "$public" ] || [ -L "$public" ]; }; then safe=0; fi
    done
    if { [ -e "$OLD_ROOT" ] || [ -L "$OLD_ROOT" ]; } \
            && { [ -e "$OLD_QUARANTINE" ] || [ -L "$OLD_QUARANTINE" ]; }; then safe=0; fi
    if [ -d "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ]; then
        "$PYTHON" -c 'import json,pathlib,sys
r=pathlib.Path(sys.argv[1])/"bootstrap-install.json"
try: d=json.loads(r.read_bytes())
except Exception: raise SystemExit(1)
raise SystemExit(d.get("product")!="agentporter" or d.get("version")!="0.1.5")' \
            "$INSTALL_ROOT" || safe=0
    elif [ -e "$INSTALL_ROOT" ] || [ -L "$INSTALL_ROOT" ]; then safe=0; fi
    if [ "$safe" -eq 0 ]; then
        printf 'AgentPorter bootstrap: partial/mixed upgrade; residue retained: %s %s %s\n' \
            "$OLD_ROOT" "$INSTALL_ROOT" "$JOURNAL" >&2
        return 1
    fi
    if same_link "$UNINSTALL_LINK" "$new_uninstaller"; then
        rm "$UNINSTALL_LINK" && ln -s "$OLD_UNINSTALLER" "$UNINSTALL_LINK"
    fi
    for entry in agentporter-activate agentporter; do
        public=${BIN_HOME}/${entry}; expected=${INSTALL_ROOT}/venv/bin/${entry}
        if same_link "$public" "$expected"; then rm "$public"; fi
    done
    if [ -d "$OLD_QUARANTINE" ] && [ ! -L "$OLD_QUARANTINE" ]; then
        mv "$OLD_QUARANTINE" "$OLD_ROOT"
    fi
    if [ -d "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ]; then rm -rf "$INSTALL_ROOT"; fi
    if same_link "$UNINSTALL_LINK" "$OLD_UNINSTALLER" \
            && [ -d "$OLD_ROOT" ] && [ ! -L "$OLD_ROOT" ]; then
        rm -f "$JOURNAL"
        printf 'AgentPorter bootstrap: upgrade compensated; restored the 0.1.4 installation\n' >&2
    else
        printf 'AgentPorter bootstrap: partial/mixed upgrade; residue retained: %s %s %s\n' \
            "$OLD_ROOT" "$INSTALL_ROOT" "$JOURNAL" >&2
    fi
}

STAGING=
PUBLISHED=0
cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        if [ "$UPGRADE" -eq 1 ]; then
            compensate_upgrade || :
        elif [ "$PUBLISHED" -eq 1 ] && [ "$STATE" != COMPLETE ]; then
            safe=1
            for entry in $ENTRY_POINTS; do
                public=${BIN_HOME}/${entry}; expected=${INSTALL_ROOT}/venv/bin/${entry}
                if { [ -e "$public" ] || [ -L "$public" ]; } \
                        && ! same_link "$public" "$expected"; then safe=0; fi
            done
            if [ "$safe" -eq 1 ]; then
                for entry in $ENTRY_POINTS; do
                    public=${BIN_HOME}/${entry}; expected=${INSTALL_ROOT}/venv/bin/${entry}
                    if same_link "$public" "$expected"; then rm "$public"; fi
                done
                if [ -d "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ]; then
                    rm -rf "$INSTALL_ROOT"
                fi
            else
                printf 'AgentPorter bootstrap: partial/mixed install; residue retained: %s\n' \
                    "$INSTALL_ROOT" >&2
            fi
        fi
    fi
    if [ "$PUBLISHED" -eq 0 ] && [ -n "$STAGING" ] \
            && [ -d "$STAGING" ] && [ ! -L "$STAGING" ]; then
        rm -rf "$STAGING"
    fi
    return "$status"
}
trap cleanup EXIT HUP INT TERM

journal_state PREPARED
STAGING=$(mktemp -d "${PRODUCT_ROOT}/.0.1.5-stage.XXXXXX") \
    || fail 'could not create a private staging directory'
chmod 700 "$STAGING" || fail 'could not secure the staging directory'

printf 'Downloading AgentPorter v%s release artifacts...\n' "$VERSION"
CURL_ENV="env -i PATH=$PATH"
if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ]; then
    CURL_ENV="$CURL_ENV CALL_LOG=${CALL_LOG:?} FAKE_CHECKSUM=${FAKE_CHECKSUM:?}"
fi
# shellcheck disable=SC2086 -- fixed allowlisted environment words.
$CURL_ENV curl --fail --location --proto '=https' --proto-redir '=https' \
    --tlsv1.2 --connect-timeout 15 --retry 3 --retry-delay 2 \
    --silent --show-error \
    -o "$STAGING/$WHEEL" "$RELEASE_BASE_URL/$WHEEL" \
    || fail 'wheel download failed'
# shellcheck disable=SC2086 -- fixed allowlisted environment words.
$CURL_ENV curl --fail --location --proto '=https' --proto-redir '=https' \
    --tlsv1.2 --connect-timeout 15 --retry 3 --retry-delay 2 \
    --silent --show-error \
    -o "$STAGING/$CHECKSUM" "$RELEASE_BASE_URL/$CHECKSUM" \
    || fail 'checksum download failed'

EXPECTED=$(sed -n '1{s/[[:space:]].*$//;p;}' "$STAGING/$CHECKSUM")
LISTED=$(sed -n '1{s/^[^[:space:]]*[[:space:]][[:space:]]*[*]*//;p;}' "$STAGING/$CHECKSUM")
[ "$(wc -l < "$STAGING/$CHECKSUM" | tr -d ' ')" -eq 1 ] \
    || fail 'release checksum must contain exactly one record'
case "$EXPECTED" in
    *[!0-9a-f]*|'') fail 'release checksum has an invalid format' ;;
esac
[ "${#EXPECTED}" -eq 64 ] || fail 'release checksum has an invalid length'
[ "$LISTED" = "$WHEEL" ] || fail 'release checksum names the wrong wheel'
ACTUAL=$(
    "$PYTHON" -c 'import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1], "rb"), "sha256").hexdigest())' \
        "$STAGING/$WHEEL"
) || fail 'could not calculate the wheel checksum'
[ "$ACTUAL" = "$EXPECTED" ] || fail 'wheel checksum verification failed'

VENV=${STAGING}/venv
"$PYTHON" -m venv "$VENV" || fail 'could not create the private virtual environment'
PIP_TEST_ENV=
if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ]; then
    PIP_TEST_ENV="CALL_LOG=${CALL_LOG:?}"
fi
# shellcheck disable=SC2086 -- fixed allowlisted test environment word.
env -i PATH="$PATH" HOME="$HOME" PIP_CONFIG_FILE=/dev/null PIP_REQUIRE_VIRTUALENV=1 $PIP_TEST_ENV \
    "$VENV/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: \
    "$STAGING/$WHEEL" \
    || fail 'package installation failed'
[ -x "$VENV/bin/agentporter" ] || fail 'installed package is missing the AgentPorter entry point'
[ -x "$VENV/bin/agentporter-activate" ] || fail 'installed package is missing the activation entry point'
[ -x "$VENV/bin/agentporter-uninstall" ] || fail 'installed package is missing the uninstaller entry point'
INSTALLED_VERSION=$(
    "$VENV/bin/python" -c 'import agentporter; print(agentporter.__version__)'
) || fail 'could not read back the installed package version'
[ "$INSTALLED_VERSION" = "$VERSION" ] || fail 'installed package version does not match the release'
for resource in $PACKAGED_RESOURCES; do
    "$VENV/bin/python" -c 'from importlib.resources import files; import sys
package, relative = sys.argv[1].split("/", 1)
target = files(package).joinpath(relative)
raise SystemExit(not target.is_file() or not target.read_bytes())' "$resource" \
        || fail 'installed package is missing a required packaged resource'
done
for module in $REQUIRED_MODULES; do
    "$VENV/bin/python" -c 'import importlib, sys; importlib.import_module(sys.argv[1])' "$module" \
        || fail 'installed package is missing a required runtime module'
done
journal_state STAGED_015_VERIFIED

rm -f "$STAGING/$WHEEL" "$STAGING/$CHECKSUM"
FINAL_VENV=${INSTALL_ROOT}/venv
for entry in $ENTRY_POINTS; do
    ENTRY=${VENV}/bin/${entry}
    "$PYTHON" -c 'from pathlib import Path; import sys
path = Path(sys.argv[1])
old = sys.argv[2].encode()
new = sys.argv[3].encode()
data = path.read_bytes()
if not data.startswith(old + b"\n"):
    raise SystemExit(1)
path.write_bytes(new + data[len(old):])' \
        "$ENTRY" "#!${VENV}/bin/python" "#!${FINAL_VENV}/bin/python" \
        || fail 'could not bind package entry points to the final installation path'
done
"$PYTHON" -c 'import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
payload = {
    "schema_version": 2,
    "product": "agentporter",
    "version": sys.argv[2],
    "public_entries": sys.argv[3:],
}
path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
path.chmod(0o600)' \
    "$STAGING/bootstrap-install.json" "$VERSION" $PUBLIC_ENTRIES \
    || fail 'could not write the bootstrap ownership receipt'
journal_state RECEIPT_V2_STAGED
mv "$STAGING" "$INSTALL_ROOT" || fail 'could not publish the verified installation'
PUBLISHED=1
fail_at after-install-root-rename
journal_state AGENTPORTER_PUBLISHED
VENV=${FINAL_VENV}
[ -x "$VENV/bin/agentporter" ] || fail 'published package is missing the AgentPorter entry point'
[ -x "$VENV/bin/agentporter-activate" ] || fail 'published package is missing the activation entry point'
[ -x "$VENV/bin/agentporter-uninstall" ] || fail 'published package is missing the uninstaller entry point'
for entry in $ENTRY_POINTS; do
    if [ "$entry" = agentporter-uninstall ] && [ "$UPGRADE" -eq 1 ]; then
        NEW_LINK=${INSTALL_ROOT}/.agentporter-uninstall.new
        ln -s "$VENV/bin/$entry" "$NEW_LINK" || fail 'could not stage upgraded uninstaller'
        mv "$NEW_LINK" "$BIN_HOME/$entry" || fail 'could not switch upgraded uninstaller'
    else
        ln -s "$VENV/bin/$entry" "$BIN_HOME/$entry" \
            || fail 'package was installed but a public entry point could not be published'
        if [ "$entry" = agentporter ]; then
            journal_state AGENTPORTER_PUBLISHED
        else
            journal_state ACTIVATE_PUBLISHED
        fi
    fi
    fail_at "after-${entry}-link"
done
journal_state UNINSTALLER_SWITCHED
for entry in $ENTRY_POINTS; do
    fail_at "before-${entry}-readback"
    PUBLIC_ENTRY=$BIN_HOME/$entry
    [ -L "$PUBLIC_ENTRY" ] && [ "$(readlink "$PUBLIC_ENTRY")" = "$VENV/bin/$entry" ] \
        && [ -x "$PUBLIC_ENTRY" ] \
        || fail 'published entry-point readback failed'
    READBACK_VERSION=$("$VENV/bin/python" -c 'import agentporter; print(agentporter.__version__)') \
        || fail 'published entry-point version readback failed'
    [ "$READBACK_VERSION" = "$VERSION" ] || fail 'published entry-point version readback failed'
done
journal_state ENTRY_SET_READBACK_PASSED
journal_state RECEIPT_V2_COMMITTED
if [ "$UPGRADE" -eq 1 ]; then
    mv "$OLD_ROOT" "$OLD_QUARANTINE" || fail 'could not quarantine the old package root'
    journal_state OLD_014_QUARANTINED
    rm -rf "$OLD_QUARANTINE" || fail 'upgraded package is active but the old root remains'
fi
journal_state COMPLETE
rm -f "$JOURNAL"

printf '\nPackage installed and checksum verified. Starting the interactive AgentPorter plan.\n'
printf 'No Hermes Profile will be written until you review and confirm that plan.\n\n'
if "$VENV/bin/agentporter" < "$INPUT_DEVICE"; then
    printf '\nconfiguration-required\nNext step:\n  %s\n' "$BIN_HOME/agentporter-activate"
    printf '\nAgentPorter completed. Uninstall later with:\n  %s\n' "$UNINSTALL_LINK"
else
    status=$?
    printf '\nAgentPorter did not complete successfully.\n' >&2
    printf 'The verified package and uninstaller were kept for diagnosis or cleanup:\n  %s\n' \
        "$UNINSTALL_LINK" >&2
    exit "$status"
fi
