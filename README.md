# AgentPorter

English | [简体中文](README.zh-CN.md)

AgentPorter is an open-source, one-shot installer for reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) Worker Profiles.

> **Release candidate status:** v0.1.0 has passed local, adversarial, packaging, artifact, and isolated Hermes v0.20.0 acceptance gates without model calls. Publication remains pending until the candidate passes remote cross-platform CI and the tag, GitHub Release, and hosted-asset readback are complete. Hermes v0.20.0 is an observed acceptance target, not a promised minimum.

## One-line install (POSIX)

After the first supported release is published, Linux and macOS users can install the latest release without specifying a version:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

The `latest` endpoint selects the newest non-prerelease GitHub Release; the downloaded bootstrap itself pins that release's exact version and artifacts. For higher assurance, download and inspect `install.sh` before running it. The bootstrap requires Python 3.11+ and a real terminal, verifies the wheel against its `.sha256` file, installs it into a private virtual environment, publishes the independent `agentporter-uninstall` entry under `${XDG_BIN_HOME:-$HOME/.local/bin}`, and starts AgentPorter's normal interactive plan through `/dev/tty`. It does not bypass confirmation or install Hermes itself.

The endpoint returns 404 until publication is complete. See the [installation guide](docs/04-installation-and-troubleshooting.md) for the inspect-first flow, PATH, trust boundary, and recovery details.

## What it installs

One launch installs the repository's complete two-Profile Worker set:

- `luna_worker` — bounded implementation and analysis after the parent fixes goal, scope, constraints, and acceptance;
- `codex-5-3-small-worker` — narrower, strictly mechanical delegation.

Each Profile contains Hermes-native configuration, instructions, routing description, and a non-secret ownership marker. AgentPorter orchestrates Hermes Profile primitives; it does not replace Hermes storage, queues, worktrees, or provider configuration.

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
- `install.py`, `uninstall.py`, and `src/agentporter/` — one-shot install and guarded independent uninstall;
- `tests/` — unit, filesystem, transaction, stress, and isolated real-Hermes acceptance;
- `scripts/verify_release.py` — fail-closed source/wheel/sdist contract verifier;
- `docs/` — architecture, Worker format, adapter mapping, lifecycle design, plans, and user guides.

Design and evidence:

- [Solution overview](docs/00-solution-overview.md)
- [Portable Worker specification](docs/01-portable-worker-spec.md)
- [Hermes adapter design](docs/02-platform-adapters.md)
- [Install/uninstall design and acceptance matrix](docs/03-installation-and-uninstall-design.md)
- [Implementation plan](docs/plan/01-implementation-plan.md)
- [Post-install Worker validation plan](docs/plan/02-agent-validation-and-benchmark.md)
- [Changelog](CHANGELOG.md)

The detailed design and plan documents are engineering history and contracts, not universal production-readiness claims. “Codex” platform support is outside the first release; the Worker name does not imply a Codex CLI adapter.

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for exact offline gates and the separate real-Hermes workflow. Never commit credentials, private runtime state, caches, model output, or personal paths. Report suspected vulnerabilities privately according to [SECURITY.md](SECURITY.md).

AgentPorter is licensed under the [MIT License](LICENSE).
