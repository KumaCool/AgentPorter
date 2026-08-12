# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project intends to use semantic versioning after its first release.

## [Unreleased]

## [0.1.3] - Release candidate

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

[Unreleased]: https://github.com/KumaCool/AgentPorter/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/KumaCool/AgentPorter/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/KumaCool/AgentPorter/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KumaCool/AgentPorter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KumaCool/AgentPorter/releases/tag/v0.1.0
