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
REQUIRED_MODULES='agentporter.activation_application agentporter.activation_entry agentporter.dispatch_application agentporter.dispatch_planning agentporter.kanban_runtime agentporter.runtime_observation agentporter.runtime_probe'

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

STAGING=$(mktemp -d "${PRODUCT_ROOT}/.0.1.5-stage.XXXXXX") \
    || fail 'could not create a private staging directory'
chmod 700 "$STAGING" || fail 'could not secure the staging directory'
PUBLISHED=0
cleanup() {
    if [ "$PUBLISHED" -eq 0 ] && [ -d "$STAGING" ] && [ ! -L "$STAGING" ]; then
        rm -rf "$STAGING"
    fi
}
trap cleanup EXIT HUP INT TERM

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
mv "$STAGING" "$INSTALL_ROOT" || fail 'could not publish the verified installation'
PUBLISHED=1
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
    fi
done
for entry in $ENTRY_POINTS; do
    PUBLIC_ENTRY=$BIN_HOME/$entry
    [ -L "$PUBLIC_ENTRY" ] && [ "$(readlink "$PUBLIC_ENTRY")" = "$VENV/bin/$entry" ] \
        && [ -x "$PUBLIC_ENTRY" ] \
        || fail 'published entry-point readback failed'
    READBACK_VERSION=$("$VENV/bin/python" -c 'import agentporter; print(agentporter.__version__)') \
        || fail 'published entry-point version readback failed'
    [ "$READBACK_VERSION" = "$VERSION" ] || fail 'published entry-point version readback failed'
done
if [ "$UPGRADE" -eq 1 ]; then
    rm -rf "$OLD_ROOT" || fail 'upgraded package is active but the old root remains'
fi

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
