# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project intends to use semantic versioning after its first release.

## [Unreleased]

### Changed

- The POSIX bootstrap now starts `agentporter-activate` immediately after successful Profile installation without an additional opt-in prompt; activation failure keeps the installed retry entry and returns non-zero.
- Hermes v0.20 custom-provider activation no longer calls unsupported bare-provider auth commands. It transactionally inherits the exact selected provider definition from the main/default Profile into each Worker, while keeping that potentially secret definition out of output, argv, fingerprints, and receipts.

## [0.1.6] - 2026-08-13

### Fixed

- Closed release-review gaps in one-shot process-tree cleanup, structured secret scanning, and fail-closed interrupted-upgrade recovery.
- Added a checksum-verified, authority-sealed three-entry bootstrap transaction for fresh 0.1.6 installs and completed 0.1.5 upgrades while preserving the historical 0.1.4 to 0.1.5 recovery contract.

## [0.1.5] - 2026-08-13

### Added

- Implemented the AgentPorter-only 0.1.5 runtime-activation path: three public lifecycle entries, safe 0.1.4 software upgrade, Profile-scoped Hermes authentication orchestration, transactional provider/endpoint binding, authoritative readiness receipts, and separately authorized one-shot evidence.

### Security

- Runtime activation preserves Profile authority, seals the Hermes executable and evidence files, never copies credentials, and reports successful Hermes v0.20 calls as `route-proof-incomplete` unless tool/fallback telemetry is available. Real model calls, Gateway changes, and Kanban mutations remain separately authorized.

## [0.1.4] - 2026-08-13

### Added

- Added a dedicated orchestrator Profile, a worker-only `agentporter-activate` entry point, non-secret runtime-binding receipts, fail-closed probe negotiation, dispatch planning/runtime receipts, and runtime observation/structural-continuity contracts.
- Added verified fresh three-Profile and legacy two-to-three-Profile lifecycle support while preserving existing Worker markers, instance-owned configuration, credentials, and concurrent drift.

### Changed

- Package and release contracts now include activation, dispatch, Kanban runtime, probe, and observation modules plus the activation console entry.
- Documentation now reports installation, binding, credential, canary, dispatcher, route, and continuity independently; `config check` is static-only and an empty `notify-list` is normal before task creation.

### Security

- Hermes v0.20 probe capability is `probe-unsupported` and performs zero model calls because no public seam proves both zero tool calls and disabled fallback.
- Hermes v0.20 Kanban capability is `mutation-unsupported` and performs zero mutation calls because delivery-metadata write and board-revision CAS contracts are unavailable. No live canary, Gateway change, credential use, task creation, or routing acceptance was performed for this candidate.


## [0.1.3] - 2026-08-13

### Changed

- Reframed AgentPorter around one-command deployment of a role-specific multi-agent Worker team; the one-shot installer is the delivery foundation, not the complete product.
- Added the Hermes-native Kanban orchestration and task-routing implementation plan, with truthful separation between installed Profiles, static routing metadata, dispatcher readiness, and live routing acceptance.

### Fixed

- Bootstrap-installed `agentporter-uninstall` now completes uninstall by removing its exact published symlink and versioned private Python environment after Profile deletion is verified. Source-checkout execution and other installed versions remain outside that cleanup boundary.

## [0.1.2] - 2026-08-12

### Fixed

- Added bounded retries and a 15-second connection timeout to both release-asset downloads so transient GitHub connection failures are retried instead of hanging for the operating system's full TCP timeout. Failed downloads still leave no installation or staging residue.

## [0.1.1] - 2026-08-12

### Fixed

- Fixed the POSIX bootstrap moving an installed virtual environment and leaving generated `agentporter` and `agentporter-uninstall` shebangs bound to a deleted staging interpreter. Before atomic publication, the bootstrap now validates and rewrites those generated entry-point shebangs to their final virtual-environment path.

## [0.1.0] - 2026-08-12

### Added

- One-shot, confirmation-gated Hermes Worker Profile installation.
- Independent, marker-based, confirmation-gated uninstall after profile renames.
- Offline cross-platform CI and manually authorized real-Hermes acceptance CI.
- Fail-closed wheel, sdist, metadata, link, privacy, and archive verifier.
- English and Chinese installation, troubleshooting, and safe-release guidance.
- Checksum-verifying `curl | sh` bootstrap for supported POSIX releases.

### Security

- Installation performs all preflight checks before writes and never copies credentials.
- Compensation and uninstall are restricted to marker-proven AgentPorter profiles and use Hermes-native operations.

First supported public release.

[Unreleased]: https://github.com/KumaCool/AgentPorter/compare/v0.1.6...HEAD
[0.1.6]: https://github.com/KumaCool/AgentPorter/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/KumaCool/AgentPorter/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/KumaCool/AgentPorter/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/KumaCool/AgentPorter/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/KumaCool/AgentPorter/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KumaCool/AgentPorter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KumaCool/AgentPorter/releases/tag/v0.1.0
