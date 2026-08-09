# AgentPorter

AgentPorter is an open-source, platform-neutral toolkit for describing AI workers once and safely translating those definitions into native configuration for supported agent platforms.

> **Project status:** design and initial specification only. The generator, installer, CLI, and platform adapters described in this repository are not implemented yet. The documented commands are target interfaces, not currently runnable features.

## Why AgentPorter?

Agent platforms differ in configuration layout, worker discovery, instruction fields, model overrides, and configuration scope. AgentPorter is designed to keep worker responsibilities and safety boundaries in one portable manifest while letting each adapter produce and validate the target platform's native format.

Core goals:

- define worker capabilities, constraints, and model preferences in one place;
- preview exact changes before writing;
- preserve unrelated user configuration;
- validate generated configuration with the installed platform version;
- report unsupported capabilities instead of pretending platforms are equivalent;
- support user, project, and explicitly authorized remote installation scopes.

## Current contents

- `workers.yaml` — an example portable Worker manifest;
- `docs/` — architecture, specification, adapter, verification, and implementation plans.

There is no installable package or executable CLI in the repository yet.

## Documentation

- [Solution overview](docs/00-solution-overview.md)
- [Portable Worker specification](docs/01-portable-worker-spec.md)
- [Platform adapter design](docs/02-platform-adapters.md)
- [Installation and verification design](docs/03-installation-and-verification.md)
- [Implementation plan](docs/04-implementation-plan.md)

The detailed design documents are currently written in Chinese. English user documentation will be expanded alongside the first executable release.

## Planned workflow

The intended interface is:

```text
agentporter doctor
agentporter plan --platform <platform> --scope user
agentporter apply --platform <platform> --scope user
agentporter verify --platform <platform> --scope user
```

These commands are **not implemented yet**. See the [implementation plan](docs/04-implementation-plan.md) for delivery phases and acceptance gates.

## Security and privacy

AgentPorter is intended to operate on sensitive local configuration, so its design is fail-closed and non-destructive:

- remote targets must be explicitly declared;
- credentials and complete home directories must not be copied;
- unrelated agents and settings must remain unchanged;
- generated changes must be previewable and validated;
- uninstall and rollback must only affect AgentPorter-owned content.

Do not commit real credentials, cookies, private hosts, or personal configuration. Report vulnerabilities according to [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Substantial adapter or architecture work should begin with an issue so compatibility and security boundaries can be agreed on first.

## License

AgentPorter is licensed under the [MIT License](LICENSE).
