# AgentPorter

English | [简体中文](README.zh-CN.md)

AgentPorter is an open-source deployment kit for a reusable [Hermes Agent](https://hermes-agent.nousresearch.com/) multi-agent Worker team. It installs role-specific Profiles in one run and is evolving toward verified task decomposition and routing through Hermes-native Kanban orchestration. The [role-identity and configurable-binding design](docs/06-role-identities-and-configurable-model-binding-design.md) is published in v0.2.0.

> **Current status:** v0.2.0 is the latest published non-prerelease release. Tag `v0.2.0` points to `be31eb2af67660780593c716d488ca88e508f710`; the GitHub Release and all seven hosted assets passed checksum/verifier, fresh HTTPS clone, isolated wheel import, and public `latest/download/install.sh` byte-readback checks. The corrected current product installs exactly two Worker Profiles, `bounded_worker` and `mechanical_worker`, with explicit sealed model/provider/endpoint selections for both. The main Hermes agent is the orchestrator; no independent orchestrator Profile is current. No credentialed model canary, Gateway change, Kanban mutation, or live routing was performed, so this release is not `operational`.

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

## What the corrected product installs

One launch now installs exactly two Worker Profiles:

- `agentporter-bounded-worker` (`bounded_worker`) — completes well-scoped delegated work only after the main Hermes agent fixes goals, constraints, scope, files, and acceptance; it stops rather than guessing or expanding scope.
- `agentporter-mechanical-worker` (`mechanical_worker`) — handles only simpler mechanical work: trivial operational scripts, large-output reading/filtering/summarization, and exact-rule batch edits; it returns ambiguity instead of exercising broader judgment.

The main Hermes agent owns orchestration, decomposition, routing, and integration. AgentPorter installs no independent orchestrator Profile in the corrected topology. v0.2.0 genuinely shipped and was installed with a third `agentporter-orchestrator`; that was an erroneous legacy topology, now supported only for safe discovery/uninstall and a separately confirmed migration removal. Fresh install, activation, and canary target exactly two bindings and at most two calls.

## Product direction: deploy a team, then route work

The product goal is not merely to copy Profile files. A complete AgentPorter deployment should let a user submit a task, have the main Hermes agent obtain decomposition candidates, validate role and assignee policy before any task write, let Hermes execute approved children in appropriate workspaces, and return verifiable handoffs.

AgentPorter implements this as fail-closed offline contracts; current Hermes v0.20 live probe and mutation acceptance remain unproven. The authority chain is:

- [Plan index and current product status](docs/plan/00-index.md)
- [Multi-agent orchestration and routing plan](docs/plan/02-multi-agent-orchestration.md)

Until a later Hermes seam passes separately authorized live acceptance, use Hermes-native Kanban manually and do not treat installation, `config check`, a running Gateway, or offline tests as proof of automatic routing.


## Runtime state matrix

| Dimension | Current state |
|---|---|
| installation | v0.2.0 is published; its tag, seven hosted assets, release verifier, fresh HTTPS clone, isolated wheel import, and `latest` bootstrap byte readback passed. |
| public entries | `agentporter`, `agentporter-activate`, and `agentporter-uninstall` are published by the bootstrap transaction. |
| binding/credential | Custom-provider binding can inherit a sealed definition into each execution Worker; credential availability remains Profile/operator-owned and must be proven by a live call. |
| canary/live call | No credentialed live canary is claimed for the 0.1.8 release; `config check=0` remains static-only evidence. |
| route proof | The activation path verifies model/provider/api_calls from Hermes usage reports; v0.20 remains `route-proof-incomplete` without tool/fallback telemetry. |
| dispatcher/route | The main Hermes agent is the orchestrator; no separate control-plane Profile is current. Gateway, Kanban mutation, and live routing are unaccepted. |
| continuity | `DispatchReceipt`, task subscription (`notify-list`), observation, and structural-resume contracts remain offline-only; no live notification or continuation is claimed. |

The released v0.2.0 publishes `agentporter-activate`, transactionally writes the selected custom-provider binding, and can run a separately confirmed one-shot. It does not modify Hermes source. A Worker must not be marked dispatchable without current binding-specific evidence; no live credentialed canary or Kanban routing acceptance is claimed by this document.

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

- `src/agentporter/resources/workers.yaml` — the corrected role-only bounded/mechanical definitions; model/provider/endpoint come from explicit sealed operator selections;
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

The detailed design and plan documents are engineering history and contracts, not universal production-readiness claims. AgentPorter v0.2.0 is the latest published release; its role-name/binding implementation passed release and hosted readback gates, but not live model, Gateway, or Kanban acceptance. Legacy model-derived names remain only compatibility and historical vocabulary and do not imply a Codex CLI adapter.

## Development and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for exact offline gates and the separate real-Hermes workflow. Never commit credentials, private runtime state, caches, model output, or personal paths. Report suspected vulnerabilities privately according to [SECURITY.md](SECURITY.md).

AgentPorter is licensed under the [MIT License](LICENSE).

## Current custom-provider install-to-activation flow

AgentPorter 0.1.8 chains activation immediately after a successful Profile installation; there is no extra “enter activation?” prompt. For Hermes v0.20 custom providers, activation does not call unsupported bare-provider `auth add/status`. Instead, it requires an exact provider definition in the main/default Profile, seals that source config, and transactionally copies the complete selected `custom_providers` entry into each Worker before binding and the separately confirmed live canary. This intentionally copies provider configuration, including whichever `api_key` or `key_env` field the operator already placed there; it never prints that definition or stores it in AgentPorter receipts. Missing, duplicate, endpoint-mismatched, or concurrently changed definitions fail closed.

### Truthful canary contract (unreleased correction)

Canary timeout defaults to 30 seconds per Worker and supports an explicit 90-second value. An inherited provider definition with unresolved `key_env` is `credential-required` unless that exact target Worker Profile owns a resolvable `.env`. A sealed concrete custom-provider definition is invoked through canonical provider `custom`; usage provider `custom` maps only to that sealed definition. Exit-zero usage marked `failed` is classified by its closed safe reason, never accepted. Closed failures remain `authentication-failed`, `model-unsupported`, `endpoint-unavailable`, `rate-limited`, `probe-timeout`, `response-contract-failed`, `usage-evidence-invalid`, and `unexpected-runtime-route`.
