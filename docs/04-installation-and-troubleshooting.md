# Installation, troubleshooting, and safe release

English | [简体中文](04-installation-and-troubleshooting.zh-CN.md)

AgentPorter v0.1.8 remains the current published release. The unreleased Plan 06 offline candidate uses `agentporter-bounded-worker`, `agentporter-mechanical-worker`, and `agentporter-orchestrator` for fresh installs and requires explicit sealed model/provider/endpoint selections for all three Profiles before staging. Exact legacy defaults migrate only through separately confirmed, Hermes-native journaled rename in `agentporter-activate`; user-renamed Profiles are preserved. Hermes v0.20.0 is an **observed version**, not a promised minimum or universal compatibility range.

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

To install a downloaded v0.1.8 wheel manually, verify its published checksum and create a disposable environment:

```bash
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install agentporter-0.1.8-py3-none-any.whl
agentporter
```

`agentporter` takes no user-facing flags or subcommands. It detects Hermes, validates the complete manifest and target set, creates a private staging area, displays one exact plan, and requests the confirmation printed on screen. Review every target. Cancellation or an incorrect phrase performs no install writes.

## Release-candidate bootstrap boundary

Before the hosted v0.1.8 wheel, checksum, and `install.sh` assets exist, the source-tree `install.sh` is intentionally **not executable as a user installation path**: it is pinned to the immutable `https://github.com/KumaCool/AgentPorter/releases/download/v0.1.8` assets prepared for publication. Current users must continue to use `https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh`. Publication must upload immutable assets first, then externally read back both the v0.1.8 URLs and the `latest` alias, compare bytes/checksums, and rerun the verifier.

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

The unreleased candidate installs two dedicated Worker Profiles and one dedicated orchestrator Profile under the three role names above. It does not overwrite user-renamed Profiles, invoke a model during install/rename/static readback, install a daemon, or create a task database. Binding configuration and any provider-definition inheritance remain independently confirmed activation work; Profile-local credentials and runtime data remain managed by Hermes and the user.

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
| installation | 0.1.8 is released; the Plan 06 offline candidate uses three role names and remains unpublished. |
| public entries | 0.1.8 publishes all three entries; candidate legacy-name migration is reached only through independently confirmed `agentporter-activate`. |
| binding/credential | Candidate fresh installs require explicit model/provider/endpoint for all three Profiles before staging; credentials remain Profile/operator-owned. |
| canary/live call | Real calls failed with `No inference provider configured`; `config check` remains static-only and is not canary evidence. |
| route proof | Hermes v0.20 usage exposes model/provider/api_calls but not tool/fallback fields; a 0.1.5 success initially has incomplete proof. |
| dispatcher/route | AgentPorter does not start Gateway; Kanban mutation and live routing remain unaccepted. |
| continuity | `DispatchReceipt`, task subscription (`notify-list`), observation, and structural resume remain offline-only; no live notification or continuation is claimed. |

Plan 06 code/offline gates are closed, but no real model canary, Gateway change, Kanban mutation/live routing, push, release, or hosted-artifact readback was executed. Each requires separate authorization; the candidate is not `operational` and does not modify Hermes source.

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
     --version 0.1.8 \
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

The example resource path is the v0.1.8 release contract. Hosted release acceptance additionally downloads every published asset, recomputes checksums, reruns this verifier, and checks the public `latest/download/install.sh` endpoint.

## Historical 0.1.7 activation amendment

The bootstrap now fails before downloading or creating installation paths when `/dev/tty` cannot actually be opened as a terminal; file readability alone is not treated as interactive-terminal authority.

After the interactive install plan succeeds, the bootstrap now starts `agentporter-activate` directly through the same real terminal, without another opt-in prompt. Activation still retains its binding confirmation and separately discloses/confirms live model calls. On Hermes v0.20, custom providers bypass unsupported bare-provider auth commands and inherit the exact selected provider definition from the main/default Profile into each Worker under the existing descriptor-bound config transaction. Both the current keyed `providers.<id>` schema and the compatible list-shaped `custom_providers` schema are supported without converting one into the other. Activation failure leaves the installed Profiles and public retry command in place and returns a non-zero status.
