#!/bin/sh
# AgentPorter v0.1.0 release bootstrap for POSIX systems.
set -eu

VERSION=0.1.0
RELEASE_BASE_URL=https://github.com/KumaCool/AgentPorter/releases/download/v0.1.0
WHEEL=agentporter-0.1.0-py3-none-any.whl
CHECKSUM=${WHEEL}.sha256

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
UNINSTALL_LINK=${BIN_HOME}/agentporter-uninstall
INPUT_DEVICE=/dev/tty
if [ "${AGENTPORTER_BOOTSTRAP_TESTING:-}" = 1 ]; then
    INPUT_DEVICE=${AGENTPORTER_TEST_INPUT_DEVICE:?test input device is required}
fi

[ -r "$INPUT_DEVICE" ] || fail 'an interactive terminal is required'
[ ! -e "$INSTALL_ROOT" ] && [ ! -L "$INSTALL_ROOT" ] \
    || fail "installation path already exists: ${INSTALL_ROOT}"
[ ! -e "$UNINSTALL_LINK" ] && [ ! -L "$UNINSTALL_LINK" ] \
    || fail "uninstaller path already exists: ${UNINSTALL_LINK}"

mkdir -p "$PRODUCT_ROOT" "$BIN_HOME" || fail 'could not create installation directories'
[ -d "$PRODUCT_ROOT" ] && [ ! -L "$PRODUCT_ROOT" ] \
    || fail 'product installation parent must be a real directory'
[ -d "$BIN_HOME" ] && [ ! -L "$BIN_HOME" ] \
    || fail 'binary installation parent must be a real directory'

STAGING=$(mktemp -d "${PRODUCT_ROOT}/.0.1.0-stage.XXXXXX") \
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
    --tlsv1.2 --silent --show-error \
    -o "$STAGING/$WHEEL" "$RELEASE_BASE_URL/$WHEEL" \
    || fail 'wheel download failed'
# shellcheck disable=SC2086 -- fixed allowlisted environment words.
$CURL_ENV curl --fail --location --proto '=https' --proto-redir '=https' \
    --tlsv1.2 --silent --show-error \
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
[ -x "$VENV/bin/agentporter-uninstall" ] || fail 'installed package is missing the uninstaller entry point'
INSTALLED_VERSION=$(
    "$VENV/bin/python" -c 'import agentporter; print(agentporter.__version__)'
) || fail 'could not read back the installed package version'
[ "$INSTALLED_VERSION" = "$VERSION" ] || fail 'installed package version does not match the release'

rm -f "$STAGING/$WHEEL" "$STAGING/$CHECKSUM"
mv "$STAGING" "$INSTALL_ROOT" || fail 'could not publish the verified installation'
PUBLISHED=1
VENV=${INSTALL_ROOT}/venv
ln -s "$VENV/bin/agentporter-uninstall" "$UNINSTALL_LINK" \
    || fail 'package was installed but the uninstaller entry point could not be published'

printf '\nPackage installed and checksum verified. Starting the interactive AgentPorter plan.\n'
printf 'No Hermes Profile will be written until you review and confirm that plan.\n\n'
if "$VENV/bin/agentporter" < "$INPUT_DEVICE"; then
    printf '\nAgentPorter completed. Uninstall later with:\n  %s\n' "$UNINSTALL_LINK"
else
    status=$?
    printf '\nAgentPorter did not complete successfully.\n' >&2
    printf 'The verified package and uninstaller were kept for diagnosis or cleanup:\n  %s\n' \
        "$UNINSTALL_LINK" >&2
    exit "$status"
fi
