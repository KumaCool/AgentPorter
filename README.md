# AgentPorter

AgentPorter is an open-source installer for reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) Worker profiles.

> **Project status:** The Hermes-first design and implementation Phases 1–4 are complete: the repository includes runnable one-shot install and independent uninstall entries, automated tests, and isolated Hermes v0.20 install/readback/rename/compensation/uninstall exercises. The complete acceptance campaign (Phase 5) and release packaging (Phase 6) remain unfinished.

## First product goal

AgentPorter is launched once to install the repository's complete Worker set into Hermes. It is not a command suite and exposes no subcommands, platform selectors, upgrade commands, or verification commands. A separate `uninstall.py` script is planned solely to remove the two dedicated Profiles later.

The first release will install two independent Hermes Profiles:

- `luna_worker` — bounded implementation and analysis after the parent has fixed the goal, scope, constraints, and acceptance checks;
- `codex-5-3-small-worker` — strictly mechanical work that is simpler and narrower than `luna_worker` work.

Each installed Profile contains Hermes-native `config.yaml`, `SOUL.md`, a routing description, and a non-secret name-independent AgentPorter marker. It can be called directly with `hermes -p <profile>`, assigned through Hermes Kanban, and used from any project directory sharing the same Hermes configuration root.

## Why Hermes-first?

Hermes already provides the mature primitives AgentPorter needs:

- isolated Profiles and profile descriptions;
- Profile distributions installed from Git or local directories;
- per-Profile models, providers, instructions, skills, memory, and sessions;
- Kanban assignment and worktree-backed execution;
- distribution installation that excludes credentials and user runtime state.

AgentPorter orchestrates these primitives rather than reimplementing Profile storage, Git distribution, task queues, or worktree management.

## Product boundary

One AgentPorter launch preflights, previews, confirms, installs, statically reads back, performs bounded failure compensation, and exits. It does **not** install a resident service, retain a task database, provide ongoing lifecycle management, replace existing Profiles, copy credentials, or call a model.

The standalone uninstaller is a guarded cleanup escape hatch, not a management interface. It discovers renamed Profiles from protocol-fixed product/component IDs plus a per-installation ID; user-editable names never establish identity. The complete transaction and deletion rules live only in the [consolidated design](docs/03-installation-and-uninstall-design.md).

## Current repository contents

- `workers.yaml` — portable Worker definitions and requested model preferences;
- `install.py` and the `agentporter` entry point — the runnable one-shot installer;
- `src/agentporter/` — validation, staging, confirmation, native installation, static readback, and bounded compensation implementation;
- `tests/` — unit, adversarial filesystem, transaction, and isolated real-Hermes tests;
- `docs/` — architecture, Worker format, Adapter mapping, install/uninstall design, acceptance matrix, and implementation plans.

The independent uninstaller is implemented; the project is not yet a release candidate because Phase 5 acceptance and Phase 6 packaging remain open.

## Codex scope

“Codex” in this scope means a **Codex CLI/platform adapter**, not the model ID requested by the Hermes Profile named `codex-5-3-small-worker`. That Worker remains part of the Hermes-first set. A Codex CLI adapter is not part of the first implementation: the project will not generate Codex configuration, install Codex agents, or claim Codex CLI compatibility until a real supported version and native validation path are available.

## Documentation

- [Solution overview](docs/00-solution-overview.md)
- [Portable Worker specification](docs/01-portable-worker-spec.md)
- [Hermes adapter design](docs/02-platform-adapters.md)
- [Installation, uninstall, and acceptance design](docs/03-installation-and-uninstall-design.md)
- [Implementation plan](docs/plan/01-implementation-plan.md)
- [Worker validation and benchmark plan](docs/plan/02-agent-validation-and-benchmark.md)

The detailed design documents are currently written in Chinese.

## Security and privacy

AgentPorter never publishes or copies credentials or private runtime state, never overwrites existing Profiles, and never calls a model during installation. Uninstall requires an installation-bound confirmation and warns that all Profile-local data will be deleted. Local markers are ownership claims, not cryptographic authentication; the [consolidated design](docs/03-installation-and-uninstall-design.md) is authoritative.

Report vulnerabilities according to [SECURITY.md](SECURITY.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. The first implementation must remain Hermes-first; other platforms require separate evidence and approval.

## License

AgentPorter is licensed under the [MIT License](LICENSE).
