# Installation, troubleshooting, and safe release

English | [简体中文](04-installation-and-troubleshooting.zh-CN.md)

AgentPorter v0.1.4 is released. It installs and reads back three Profiles, but the released bootstrap publishes only `agentporter-uninstall`; the public `agentporter-activate` command is missing and the formal probe remains fixed to unsupported. The two Workers therefore still need a subsequent AgentPorter fix to automate provider/endpoint/Profile-local credentials and the live-call continuation. Hermes v0.20.0 is an **observed version**, not a promised minimum or universal compatibility range.

## One-line POSIX install

Install the latest non-prerelease version without specifying a version:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

GitHub's `latest` endpoint selects the release bootstrap; that bootstrap pins and downloads its exact-version wheel and `.sha256` sidecar. It verifies and installs the wheel in a private sibling staging directory, reads back the installed package version, validates and rewrites the three generated entry-point shebangs to their final virtual-environment path, and only then atomically publishes the versioned installation. It links `agentporter-uninstall` into `${XDG_BIN_HOME:-$HOME/.local/bin}` before launching the normal interactive installer through `/dev/tty`. Existing install or link paths are refused rather than overwritten. If the product installation is cancelled or fails, the verified package and uninstaller remain available for diagnosis or cleanup. After a later successful Profile uninstall, the release-installed entry removes its own exact link and versioned private environment.

The checksum protects against accidental corruption or mismatched hosting; it is not independent of the GitHub release account. The wheel still resolves its declared dependencies through pip, restricted to binary distributions, so the release checksum does not independently authenticate those dependency downloads. For stronger provenance, inspect the script and compare published release attestations/checksums before execution. Add `${XDG_BIN_HOME:-$HOME/.local/bin}` to `PATH` if necessary.

## Prerequisites

- Python 3.11 or newer.
- Hermes Agent already installed and its `hermes` executable discoverable.
- A terminal attached to standard input: installation and uninstall require interactive confirmation.
- A clean backup of any Hermes configuration that matters to you.

Linux has the strongest real-Hermes acceptance evidence. macOS and Windows are covered by the offline CI matrix; this proves portable contracts, not native Hermes acceptance on those hosts.

## Install from a release artifact

To install a downloaded v0.1.4 wheel manually, verify its published checksum and create a disposable environment:

```bash
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install agentporter-0.1.4-py3-none-any.whl
agentporter
```

`agentporter` takes no user-facing flags or subcommands. It detects Hermes, validates the complete manifest and target set, creates a private staging area, displays one exact plan, and requests the confirmation printed on screen. Review every target. Cancellation or an incorrect phrase performs no install writes.

## Release-candidate bootstrap boundary

Before the hosted v0.1.4 wheel, checksum, and `install.sh` assets exist, the source-tree `install.sh` is intentionally **not executable as a user installation path**: it is pinned to the immutable `https://github.com/KumaCool/AgentPorter/releases/download/v0.1.4` assets prepared for publication. Current users must continue to use `https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh`. Publication must upload immutable assets first, then externally read back both the v0.1.4 URLs and the `latest` alias, compare bytes/checksums, and rerun the verifier.

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

AgentPorter v0.1.4 installs two dedicated Worker Profiles and one dedicated orchestrator Profile. Its static orchestrator configuration is installed and read back. It does not overwrite existing profiles, copy provider credentials, invoke a model, install a daemon, or create a task database. Profile-local credentials and runtime data remain managed by Hermes and the user.

Static orchestrator configuration is installed and read back, but auto decomposition remains disabled; AgentPorter does **not** start Gateway, create Kanban tasks, enable live routing, or prove live task routing. Those capabilities are tracked in the [multi-agent orchestration plan](plan/02-multi-agent-orchestration.md).

## Independent uninstall

After installing the wheel, run its dedicated uninstall console entry:

```bash
agentporter-uninstall
```

There are no silent flags. The uninstaller scans read-only for one complete marker-bound installation, shows the current (possibly renamed) profiles and paths, warns that all local profile data and later customization will be deleted, and requires the exact installation-bound phrase shown. It then revalidates the complete set and each target immediately before Hermes-native deletion. After all targets are verified absent, a bootstrap-installed entry verifies its installer-written ownership receipt and exact versioned layout, atomically isolates and revalidates both the installation and published symlink, removes the private environment, and removes the product directory only when empty. It refuses package cleanup if the entry, interpreter, link, or installation identity changed, and never removes another installed version.

When deliberately running from a trusted source checkout instead, use `python uninstall.py`. Source-checkout execution removes Profiles only; it does not delete the checkout or its virtual environment.

If discovery is absent, incomplete, duplicated, conflicting, malformed, changed, symlinked, or path-escaped, uninstall stops without widening scope. If one deletion fails, the result may be partial; do not manually delete unknown paths. Back up needed profile-local data before confirmation.

## Runtime readiness and orchestration status

| Dimension | Current state |
|---|---|
| installation | 0.1.4 is released; fresh/legacy three-Profile lifecycle contracts and target-host installation readback passed. |
| public entries | `agentporter-uninstall` is public; `agentporter-activate` exists only in the private environment until 0.1.5. |
| binding/credential | Both Workers lack provider/endpoint/Profile-local credentials and remain `configuration-required`. |
| canary/live call | Real calls failed with `No inference provider configured`; `config check` remains static-only and is not canary evidence. |
| route proof | Hermes v0.20 usage exposes model/provider/api_calls but not tool/fallback fields; a 0.1.5 success initially has incomplete proof. |
| dispatcher/route | AgentPorter does not start Gateway; Kanban mutation and live routing remain unaccepted. |
| continuity | `DispatchReceipt`, task subscription (`notify-list`), observation, and structural resume remain offline-only; no live notification or continuation is claimed. |

Released 0.1.4 cannot complete activation through a public command. The subsequent [0.1.5 design](05-runtime-activation-and-live-call-design.md) changes AgentPorter only: it publishes all three public entries, orchestrates native Profile auth, and runs a separately authorized real one-shot. It does not modify Hermes source.

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
     --version 0.1.4 \
     --dependency 'pydantic<3,>=2' \
     --dependency 'PyYAML<7,>=6' \
     --entry-point 'agentporter=agentporter:main' \
     --entry-point 'agentporter-activate=agentporter.activation_entry:main' \
     --entry-point 'agentporter-uninstall=agentporter.uninstall_entry:main' \
     --resource 'resources/workers.yaml' \
     --required-module activation_application.py \
     --required-module activation_entry.py \
     --required-module dispatch_application.py \
     --required-module dispatch_planning.py \
     --required-module kanban_runtime.py \
     --required-module runtime_observation.py \
     --required-module runtime_probe.py \
     --bootstrap-checksum <wheel>.sha256 \
     --bootstrap-source-sha256 566e07f77f3f7867b27fdb98e21c2d17f78929c203bd9500431fe82707fa84b6 \
     <wheel> <sdist>
   ```

6. Inspect checksums, commit identity, tag, changelog, license, README, and verifier output before upload. Publish only the exact verified bytes.
7. Download hosted artifacts, recompute checksums, and rerun verification. A tag or successful upload alone is not acceptance.

The example resource path is the v0.1.4 release contract. Hosted release acceptance additionally downloads every published asset, recomputes checksums, reruns this verifier, and checks the public `latest/download/install.sh` endpoint.
