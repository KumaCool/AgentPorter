# AgentPorter

English | [简体中文](README.zh-CN.md)

AgentPorter is an open-source deployment kit for a reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) multi-agent Worker team. It installs role-specific Profiles in one run and is evolving toward verified task decomposition and routing through Hermes-native Kanban orchestration.

> **Release candidate capability:** v0.1.3 is being prepared to safely install and uninstall the two-Profile Worker foundation. It writes routing descriptions and Hermes can enumerate both assignees, but AgentPorter has not yet configured or accepted automatic decomposition, dispatcher execution, or live Worker routing. That is the next implementation plan—not a current release claim.

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

## What v0.1.3 installs

One launch installs the repository's current two-Profile Worker foundation:

- `luna_worker` — bounded implementation and analysis after the parent fixes goal, scope, constraints, and acceptance;
- `codex-5-3-small-worker` — narrower, strictly mechanical delegation.

Each Profile contains Hermes-native configuration, instructions, routing description, and a non-secret ownership marker. AgentPorter composes Hermes primitives instead of replacing Profile storage, the Kanban task database, the decomposer, dispatcher, worktrees, or provider configuration.

## Product direction: deploy a team, then route work

The product goal is not merely to copy Profile files. A complete AgentPorter deployment should let a user submit a task, have a dedicated AgentPorter orchestrator obtain Hermes decomposition candidates, validate role and assignee policy before any task write, let Hermes execute approved children in appropriate workspaces, and return verifiable handoffs.

The current release provides only the safe installation foundation for that flow. The repository now tracks the missing orchestration work explicitly:

- [Plan index and current product status](docs/plan/00-index.md)
- [Multi-agent orchestration and routing plan](docs/plan/02-multi-agent-orchestration.md)

Until that plan passes live acceptance, use Hermes-native Kanban manually and do not treat Profile installation or description readback as proof of automatic routing.

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
