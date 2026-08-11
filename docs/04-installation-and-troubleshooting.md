# Installation, troubleshooting, and safe release

English | [简体中文](04-installation-and-troubleshooting.zh-CN.md)

AgentPorter v0.1.0 is the first supported release of this Hermes-first one-shot installer. The repository has offline contract tests and isolated real-Hermes evidence for v0.20.0; that observed version is **not** a promised minimum or universal compatibility range.

## One-line POSIX install

Install the latest non-prerelease version without specifying a version:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

GitHub's `latest` endpoint selects the release bootstrap; that bootstrap pins and downloads its exact-version wheel and `.sha256` sidecar. It verifies the wheel, builds in a private sibling staging directory, reads back the installed package version, atomically publishes the versioned installation, and links `agentporter-uninstall` into `${XDG_BIN_HOME:-$HOME/.local/bin}` before launching the normal interactive installer through `/dev/tty`. Existing install or link paths are refused rather than overwritten. If the product installation is cancelled or fails, the verified package and uninstaller remain available for diagnosis or cleanup. The uninstaller removes installed Hermes Profiles; it does not remove this private Python environment.

The checksum protects against accidental corruption or mismatched hosting; it is not independent of the GitHub release account. The wheel still resolves its declared dependencies through pip, restricted to binary distributions, so the release checksum does not independently authenticate those dependency downloads. For stronger provenance, inspect the script and compare published release attestations/checksums before execution. Add `${XDG_BIN_HOME:-$HOME/.local/bin}` to `PATH` if necessary.

## Prerequisites

- Python 3.11 or newer.
- Hermes Agent already installed and its `hermes` executable discoverable.
- A terminal attached to standard input: installation and uninstall require interactive confirmation.
- A clean backup of any Hermes configuration that matters to you.

Linux has the strongest real-Hermes acceptance evidence. macOS and Windows are covered by the offline CI matrix; this proves portable contracts, not native Hermes acceptance on those hosts.

## Install from a release artifact

To install a downloaded v0.1.0 wheel manually, verify its published checksum and create a disposable environment:

```bash
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install agentporter-0.1.0-py3-none-any.whl
agentporter
```

`agentporter` takes no user-facing flags or subcommands. It detects Hermes, validates the complete manifest and target set, creates a private staging area, displays one exact plan, and requests the confirmation printed on screen. Review every target. Cancellation or an incorrect phrase performs no install writes.

## Run from source

```bash
git clone <verified-repository-url>
cd AgentPorter
python -m venv .venv
# activate the environment as above
python -m pip install -e .
python install.py
```

The source checkout and artifact must come from a commit you trust. Do not run from a dirty or partially downloaded tree.

## Expected results

Terminal statuses distinguish success, cancellation, preflight failure, install failure with compensation, incomplete compensation, and readback failure. Treat anything other than the explicit success result as not installed or requiring inspection; never infer success from some profile directories being present.

AgentPorter installs two dedicated Worker Profiles. It does not overwrite existing profiles, copy provider credentials, invoke a model, install a daemon, or keep a task database. Profile-local credentials and other runtime data remain managed by Hermes and the user.

## Independent uninstall

After installing the wheel, run its dedicated uninstall console entry:

```bash
agentporter-uninstall
```

There are no silent flags. The uninstaller scans read-only for one complete marker-bound installation, shows the current (possibly renamed) profiles and paths, warns that all local profile data and later customization will be deleted, and requires the exact installation-bound phrase shown. It then revalidates the complete set and each target immediately before Hermes-native deletion.

When deliberately running from a trusted source checkout instead, use `python uninstall.py`.

If discovery is absent, incomplete, duplicated, conflicting, malformed, changed, symlinked, or path-escaped, uninstall stops without widening scope. If one deletion fails, the result may be partial; do not manually delete unknown paths. Back up needed profile-local data before confirmation.

## Troubleshooting

| Symptom | Meaning and recovery |
| --- | --- |
| Hermes not found or unsupported command surface | Install/repair Hermes, ensure the intended executable is on `PATH`, then restart AgentPorter. Do not create target folders manually. |
| Target profile already exists | AgentPorter will not overwrite it. Preserve/rename/remove it through Hermes after confirming ownership, or cancel. |
| Non-interactive input rejected | Run in a real terminal. There is intentionally no `--yes` or automation bypass. |
| Preflight/staging failure | No native install should have started. Correct permissions, free space, or manifest/source integrity and rerun. |
| Install failed, compensation complete | The current transaction's created profiles were removed; fix the reported cause and rerun. |
| Compensation incomplete or readback failed | Stop. Preserve sanitized output and inspect Hermes native profile listing. Do not blindly rerun or recursively delete directories. |
| Uninstall says absent | No complete AgentPorter marker set was found. Verify the Hermes configuration root and release source. |
| Uninstall says ambiguous/conflicting/changed | Zero additional deletion is safest. Restore known-good markers from backup only if provenance is certain; otherwise report the issue privately. |
| Native deletion/verification failed | Some profiles may remain. Use Hermes native listing/readback, preserve data, and retry only after the cause is understood. |

Never post raw config files, marker paths, credentials, sessions, memories, or private hostnames in an issue. Follow [SECURITY.md](../SECURITY.md).

## Maintainer release procedure

1. Start from a clean, reviewed commit and an empty temporary build directory.
2. Run the exact offline gates in [CONTRIBUTING.md](../CONTRIBUTING.md).
3. Run the manual real-Hermes workflow for the explicitly selected observed version; do not add provider secrets.
4. Build exactly one wheel and one sdist with `python -m build --outdir <empty-directory>`.
5. Reconcile the final packaging contract, then run the fail-closed verifier, for example:

   ```bash
   python scripts/verify_release.py \
     --version 0.1.0 \
     --dependency 'pydantic<3,>=2' \
     --dependency 'PyYAML<7,>=6' \
     --entry-point 'agentporter=agentporter:main' \
     --entry-point 'agentporter-uninstall=agentporter.uninstall_entry:main' \
     --resource 'resources/workers.yaml' \
     --bootstrap-checksum <wheel>.sha256 \
     <wheel> <sdist>
   ```

6. Inspect checksums, commit identity, tag, changelog, license, README, and verifier output before upload. Publish only the exact verified bytes.
7. Download hosted artifacts, recompute checksums, and rerun verification. A tag or successful upload alone is not acceptance.

The example resource path is the v0.1.0 release contract. Hosted release acceptance additionally downloads every published asset, recomputes checksums, reruns this verifier, and checks the public `latest/download/install.sh` endpoint.
