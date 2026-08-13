# AgentPorter

English | [简体中文](README.zh-CN.md)

AgentPorter is an open-source deployment kit for a reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) multi-agent Worker team. It installs role-specific Profiles in one run and is evolving toward verified task decomposition and routing through Hermes-native Kanban orchestration.

> **0.1.4 release candidate:** AgentPorter installs, upgrades, reads back, renames, and uninstalls one three-Profile set (two Workers plus a dedicated orchestrator), and provides offline-verified activation, dispatch, receipt, and continuity contracts. Hermes v0.20 cannot prove the required tool-free/no-fallback probe or revision-safe Kanban mutation seam, so the formal paths return `probe-unsupported` / `mutation-unsupported` before adapters run: zero model calls and zero Kanban mutation calls. This candidate is not published and does not claim `operational` or live routing acceptance.

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

## What v0.1.4 installs

One launch installs the current three-Profile foundation:

- `luna_worker` — bounded implementation and analysis after the parent fixes goal, scope, constraints, and acceptance;
- `codex-5-3-small-worker` — narrower, strictly mechanical delegation;
- `agentporter-orchestrator` — dedicated Kanban control-plane owner; it does not execute implementation tasks.

Each Profile contains Hermes-native configuration, instructions, routing description, and a non-secret ownership marker. AgentPorter composes Hermes primitives instead of replacing Profile storage, the Kanban task database, the decomposer, dispatcher, worktrees, or provider configuration.

## Product direction: deploy a team, then route work

The product goal is not merely to copy Profile files. A complete AgentPorter deployment should let a user submit a task, have a dedicated AgentPorter orchestrator obtain Hermes decomposition candidates, validate role and assignee policy before any task write, let Hermes execute approved children in appropriate workspaces, and return verifiable handoffs.

The 0.1.4 candidate implements this as fail-closed offline contracts; current Hermes v0.20 still blocks real probe and mutation acceptance. The authority chain is:

- [Plan index and current product status](docs/plan/00-index.md)
- [Multi-agent orchestration and routing plan](docs/plan/02-multi-agent-orchestration.md)

Until a later Hermes seam passes separately authorized live acceptance, use Hermes-native Kanban manually and do not treat installation, `config check`, a running Gateway, or offline tests as proof of automatic routing.


## Runtime state matrix

| Dimension | 0.1.4 candidate state |
|---|---|
| installation | Offline and isolated Hermes v0.20 install/update/readback/rename/uninstall passed for fresh three-Profile and legacy two-to-three-Profile paths. |
| binding | `agentporter-activate` transaction is offline verified; it targets only the two Workers and preserves the orchestrator and user-owned drift. |
| credential | Operator authorization is required and remains Hermes/user-owned; AgentPorter never copies or reads secret values. |
| canary | `probe-unsupported` on Hermes v0.20; zero model calls; not `runtime-ready`. |
| dispatcher | Static dedicated-orchestrator configuration is read back; no Gateway is started and dispatcher is not live-accepted. |
| route | `mutation-unsupported` on Hermes v0.20 before adapter invocation; zero Kanban mutation calls. |
| continuity | DispatchReceipt, task subscription, observation, and structural-resume contracts pass offline only; no live notification or continuation is claimed. |

`hermes config check` is a static parse/configuration check only. It is never canary or runtime-readiness evidence. With an installed set, run `agentporter-activate` interactively: it discovers the unique complete set, snapshots typed configuration, accepts non-secret binding choices without printing private endpoint values, previews one plan, confirms once, writes and reads back exact keys, and then negotiates the safe probe seam. On failure it restores only unchanged transaction-owned values (`compare-before-restore`), preserves concurrent user drift, keeps Profiles and credentials, reports bounded residue, and leaves canary required.

An empty `notify-list` is normal before any task exists. After formal task creation, exact task and subscription readback plus a safe `DispatchReceipt` are mandatory before dispatch can unlock; current v0.20 cannot meet that mutation contract, so no formal task is created.

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

- `src/agentporter/resources/workers.yaml` — packaged authoritative Worker definitions and requested model preferences;
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
- [Changelog](CHANGELOG.md)

The detailed design and plan documents are engineering history and contracts, not universal production-readiness claims. “Codex” platform support is outside the first release; the Worker name does not imply a Codex CLI adapter.

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for exact offline gates and the separate real-Hermes workflow. Never commit credentials, private runtime state, caches, model output, or personal paths. Report suspected vulnerabilities privately according to [SECURITY.md](SECURITY.md).

AgentPorter is licensed under the [MIT License](LICENSE).
