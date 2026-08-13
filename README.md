# AgentPorter

English | [简体中文](README.zh-CN.md)

AgentPorter is an open-source deployment kit for a reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) multi-agent Worker team. It installs role-specific Profiles in one run and is evolving toward verified task decomposition and routing through Hermes-native Kanban orchestration. The next functional version has an approved [role-identity and configurable-binding design](docs/06-role-identities-and-configurable-model-binding-design.md), but it is not implemented yet.

> **Current status:** 0.1.8 is released. The bootstrap publishes all three lifecycle entries, installs the three Profiles, and chains activation after installation. Hermes v0.20 custom-provider binding is implemented with guarded Profile-config inheritance, but a credentialed live canary, full `operational` state, Gateway mutation, and live routing remain separately authorized and unproven. The next functional version's role-name and configurable-model work is documentation-only today.

## One-line install (POSIX)

Linux and macOS users can install the latest release without specifying a version:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

The `latest` endpoint selects the newest non-prerelease GitHub Release; the downloaded bootstrap itself pins that release's exact version and artifacts. For higher assurance, download and inspect `install.sh` before running it. The bootstrap requires Python 3.11+ and a real terminal, verifies the wheel against its `.sha256` file, installs it into a private virtual environment, publishes the independent `agentporter-uninstall` entry under `${XDG_BIN_HOME:-$HOME/.local/bin}`, and starts AgentPorter's normal interactive plan through `/dev/tty`. It does not bypass confirmation or install Hermes itself.

To uninstall after setup, run this directly in a real terminal:

```bash
agentporter-uninstall
```

If the command is not on `PATH`, run:

```bash
"${XDG_BIN_HOME:-$HOME/.local/bin}/agentporter-uninstall"
```

Uninstall deletes the Worker Profiles installed by AgentPorter, including their local data and later customization, so back them up before confirming. After successful Profile deletion (or when they are already absent), a bootstrap-installed uninstaller also removes its exact published entry and versioned private Python environment. A trusted source-checkout `python uninstall.py` removes Profiles only and never deletes the checkout or its virtual environment. See the [installation guide](docs/04-installation-and-troubleshooting.md) for the inspect-first flow, PATH, trust boundary, and complete uninstall details.

## What v0.1.8 installs

One launch installs the current three-Profile foundation:

- `luna_worker` — bounded implementation and analysis after the parent fixes goal, scope, constraints, and acceptance;
- `codex-5-3-small-worker` — narrower, strictly mechanical delegation;
- `agentporter-orchestrator` — dedicated Kanban control-plane owner; it does not execute implementation tasks.

These are the current 0.1.8 names. The next functional version preserves permanent component UUIDs and role boundaries, renames the execution roles to `bounded_worker` / `agentporter-bounded-worker` and `mechanical_worker` / `agentporter-mechanical-worker`, and lets the operator explicitly bind model/provider/endpoint for all three Profiles. User-renamed Profiles remain unchanged. This migration is documented but not implemented.

Each Profile contains Hermes-native configuration, instructions, routing description, and a non-secret ownership marker. AgentPorter composes Hermes primitives instead of replacing Profile storage, the Kanban task database, the decomposer, dispatcher, worktrees, or provider configuration.

## Product direction: deploy a team, then route work

The product goal is not merely to copy Profile files. A complete AgentPorter deployment should let a user submit a task, have a dedicated AgentPorter orchestrator obtain Hermes decomposition candidates, validate role and assignee policy before any task write, let Hermes execute approved children in appropriate workspaces, and return verifiable handoffs.

AgentPorter implements this as fail-closed offline contracts; current Hermes v0.20 live probe and mutation acceptance remain unproven. The authority chain is:

- [Plan index and current product status](docs/plan/00-index.md)
- [Multi-agent orchestration and routing plan](docs/plan/02-multi-agent-orchestration.md)

Until a later Hermes seam passes separately authorized live acceptance, use Hermes-native Kanban manually and do not treat installation, `config check`, a running Gateway, or offline tests as proof of automatic routing.


## Runtime state matrix

| Dimension | Current state |
|---|---|
| installation | 0.1.8 is released; the three Profiles and three public lifecycle entries are covered by release contracts. |
| public entries | `agentporter`, `agentporter-activate`, and `agentporter-uninstall` are published by the bootstrap transaction. |
| binding/credential | Custom-provider binding can inherit a sealed definition into each execution Worker; credential availability remains Profile/operator-owned and must be proven by a live call. |
| canary/live call | No credentialed live canary is claimed for the 0.1.8 release; `config check=0` remains static-only evidence. |
| route proof | The activation path verifies model/provider/api_calls from Hermes usage reports; v0.20 remains `route-proof-incomplete` without tool/fallback telemetry. |
| dispatcher/route | The orchestrator's static configuration is read back; Gateway, Kanban mutation, and live routing are unaccepted. |
| continuity | `DispatchReceipt`, task subscription (`notify-list`), observation, and structural-resume contracts remain offline-only; no live notification or continuation is claimed. |

The released 0.1.8 publishes `agentporter-activate`, transactionally writes the selected custom-provider binding, and can run a separately confirmed one-shot. It does not modify Hermes source. A Worker must not be marked dispatchable without current binding-specific evidence; no live credentialed canary or Kanban routing acceptance is claimed by this document.

## Safety boundary

Installation preflights the entire set, presents one exact plan, requires interactive confirmation, installs through Hermes, reads back results, and performs bounded compensation on failure. It never overwrites existing/default Profiles, copies credentials, calls a model, installs a daemon, or keeps a task database.

The separate `uninstall.py` discovers AgentPorter Profiles even after rename by fixed marker identity, warns that Profile-local data and later customization will be deleted, requires installation-bound confirmation, revalidates against races, and uses Hermes-native deletion. Ambiguous or changed sets fail closed.

## Quick start from source

Requirements: Python 3.11+, an installed/discoverable Hermes executable, and an interactive terminal.

```bash
git clone <verified-repository-url>
cd AgentPorter
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
python install.py
```

There are no user-facing flags or subcommands. Read the plan, then enter the exact confirmation displayed. To remove one complete installation later, run the separate trusted artifact:

```bash
python uninstall.py
```

Back up any Profile-local credentials, memories, sessions, skills, logs, or customization before confirming uninstall.

For wheel installation, result states, recovery, platform-evidence distinctions, and safe release checks, read the complete guides:

- [Installation and troubleshooting — English](docs/04-installation-and-troubleshooting.md)
- [安装与故障排查 — 简体中文](docs/04-installation-and-troubleshooting.zh-CN.md)

## Platform and compatibility evidence

Offline CI runs the complete portable suite and package/release contracts on Linux and macOS with Python 3.11–3.13. Windows checks formatting, lint, Linux-targeted strict typing, and distribution builds; it does not claim native execution of descriptor-bound POSIX lifecycle or archive-mode contracts. Real Hermes acceptance runs separately on Linux against an explicitly selected Hermes version because it needs a native executable and stronger isolation.

## Repository map

- `src/agentporter/resources/workers.yaml` — the 0.1.8 Worker definitions and fixed model requests; the next functional version keeps roles here and moves models to explicit operator bindings;
- `install.py`, `uninstall.py`, and `src/agentporter/` — the current one-shot deployment foundation and guarded independent uninstall;
- `tests/` — unit, filesystem, transaction, stress, and isolated real-Hermes acceptance;
- `scripts/verify_release.py` — fail-closed source/wheel/sdist contract verifier;
- `docs/` — architecture, Worker format, adapter mapping, lifecycle design, plans, and user guides.

Design and evidence:

- [Solution overview](docs/00-solution-overview.md)
- [Portable Worker specification](docs/01-portable-worker-spec.md)
- [Hermes adapter design](docs/02-platform-adapters.md)
- [Install/uninstall design and acceptance matrix](docs/03-installation-and-uninstall-design.md)
- [Plan index](docs/plan/00-index.md)
- [v0.1.0 installation foundation record](docs/plan/01-installation-foundation.md)
- [Multi-agent orchestration and routing plan](docs/plan/02-multi-agent-orchestration.md)
- [Post-orchestration Worker validation plan](docs/plan/03-agent-validation-and-benchmark.md)
- [Role-based Worker identity and configurable inference-binding design](docs/06-role-identities-and-configurable-model-binding-design.md)
- [Role-based identity and configurable-binding implementation plan](docs/plan/06-role-identities-and-configurable-model-binding.md)
- [Changelog](CHANGELOG.md)

The detailed design and plan documents are engineering history and contracts, not universal production-readiness claims. AgentPorter 0.1.8 does not provide a Codex CLI adapter, and its current model-derived Worker name does not imply one. The next functional version removes model semantics from current product names, but the old names remain implementation facts until that version ships.

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for exact offline gates and the separate real-Hermes workflow. Never commit credentials, private runtime state, caches, model output, or personal paths. Report suspected vulnerabilities privately according to [SECURITY.md](SECURITY.md).

AgentPorter is licensed under the [MIT License](LICENSE).

## Current custom-provider install-to-activation flow

AgentPorter 0.1.8 chains activation immediately after a successful Profile installation; there is no extra “enter activation?” prompt. For Hermes v0.20 custom providers, activation does not call unsupported bare-provider `auth add/status`. Instead, it requires an exact provider definition in the main/default Profile, seals that source config, and transactionally copies the complete selected `custom_providers` entry into each Worker before binding and the separately confirmed live canary. This intentionally copies provider configuration, including whichever `api_key` or `key_env` field the operator already placed there; it never prints that definition or stores it in AgentPorter receipts. Missing, duplicate, endpoint-mismatched, or concurrently changed definitions fail closed.
