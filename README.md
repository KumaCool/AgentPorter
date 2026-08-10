# AgentPorter

AgentPorter is an open-source installer for reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) Worker profiles.

> **Project status:** Hermes-first one-shot installer design approved; implementation has not started.

## First product goal

AgentPorter is launched once to install the repository's complete Worker set into Hermes. It is not a command suite and exposes no subcommands, platform selectors, upgrade commands, or verification commands.

The first release will install two independent Hermes Profiles:

- `luna_worker` — bounded implementation and analysis after the parent has fixed the goal, scope, constraints, and acceptance checks;
- `codex-5-3-small-worker` — strictly mechanical work that is simpler and narrower than `luna_worker` work.

Each installed Profile owns its Hermes-native `config.yaml`, `SOUL.md`, and routing description. It can be called directly with `hermes -p <profile>`, assigned through Hermes Kanban, and used from any project directory sharing the same Hermes configuration root.

## Why Hermes-first?

Hermes already provides the mature primitives AgentPorter needs:

- isolated Profiles and profile descriptions;
- Profile distributions installed from Git or local directories;
- per-Profile models, providers, instructions, skills, memory, and sessions;
- Kanban assignment and worktree-backed execution;
- distribution installation that excludes credentials and user runtime state.

AgentPorter will orchestrate these primitives rather than reimplementing Profile storage, Git distribution, task queues, or worktree management.

## Installation contract

The planned one-shot flow is:

1. detect the real Hermes executable, version, active `HERMES_HOME`, Profiles, and model/provider readiness;
2. validate every Worker and render both Profile distributions into staging;
3. show a combined plan and capability report;
4. obtain one explicit confirmation for that exact plan;
5. install both Profiles through Hermes' native distribution interface;
6. set and read back the routing descriptions;
7. run Hermes-native static verification for each Profile;
8. compensate Profiles proven to have been created by this transaction if the set cannot be installed consistently, and report uncertain remnants for manual handling.

“One-shot” means one AgentPorter launch performs the complete installation and exits. It does **not** install a resident service, retain a task database, provide ongoing lifecycle management, silently copy credentials, replace existing Profiles, make paid model calls, or claim model access that was not verified.

## Current repository contents

- `workers.yaml` — portable Worker definitions and requested model preferences;
- `docs/` — Hermes-first architecture, Profile mapping, installation contract, acceptance matrix, and implementation plan.

There is currently no runnable AgentPorter installer artifact.

## Codex scope

Codex is not part of the first implementation. The architecture keeps a platform-adapter boundary so a Codex adapter can be researched later, but the project will not generate, install, or claim compatibility with Codex until a real supported Codex version and its native validation path are available.

## Documentation

- [Solution overview](docs/00-solution-overview.md)
- [Portable Worker specification](docs/01-portable-worker-spec.md)
- [Hermes adapter design](docs/02-platform-adapters.md)
- [Installation and verification design](docs/03-installation-and-verification.md)
- [Implementation plan](docs/04-implementation-plan.md)

The detailed design documents are currently written in Chinese.

## Security and privacy

AgentPorter must not publish or copy API keys, tokens, `auth.json`, `.env`, memories, sessions, logs, or private runtime state. Existing Profiles are never overwritten by default. The first release never performs live model calls.

Report vulnerabilities according to [SECURITY.md](SECURITY.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. The first implementation must remain Hermes-first; other platforms require separate evidence and approval.

## License

AgentPorter is licensed under the [MIT License](LICENSE).
