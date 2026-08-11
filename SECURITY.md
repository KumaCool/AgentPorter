# Security Policy

## Supported versions

AgentPorter remains a release candidate. Security support begins only after v0.1.0 is published and its hosted assets pass readback.

| Version | Supported |
| --- | --- |
| 0.1.x candidate | No formal support |
| Unreleased source snapshots | No formal support |

## Reporting a vulnerability

Use GitHub's **Security → Report a vulnerability** feature if private vulnerability reporting is enabled for this repository. If it is unavailable, contact a maintainer through a private channel listed on the repository hosting profile. Do not open a public issue containing exploit details or sensitive data.

Include the affected commit/artifact, sanitized reproduction, expected and observed behavior, and potential impact. Never attach real API keys, tokens, cookies, credentials, private configuration, personal paths, private hostnames, profile runtime data, or third-party data. Revoke exposed credentials immediately; removing them in a later commit does not remove them from history.

## Implemented boundaries

AgentPorter:

- completes preflight and presents one plan before writes;
- refuses to overwrite existing/default Profiles;
- compensates only Profiles proven to have been created by the current transaction;
- never copies credentials and makes no model call during install or uninstall;
- discovers uninstall targets by fixed product/component identity and a random per-installation ID, never by editable names;
- requires an installation-bound confirmation and warns that Profile-local credentials, memories, sessions, logs, skills, and later customizations will be deleted;
- fails closed on malformed, incomplete, duplicated, conflicting, symlinked, escaped, or changed candidates;
- uses Hermes-native deletion and verifies both native absence and path absence; it has no recursive-delete fallback.

The local `agentporter-profile.json` marker is an ownership claim, not a signature or authentication credential. Copying or editing it can block automated uninstall; it cannot authorize broader deletion.

## Safe release boundary

Release candidates must pass offline format, lint, type, test, build, Markdown-link, privacy, and artifact-content checks. Real-Hermes acceptance is a separate Linux test against an explicitly selected version and uses isolated homes with blank provider credentials and no model commands. Passing either gate does not prove compatibility with every Hermes version, platform, provider, or model.

Release artifacts must contain only the expected package modules/resources and distribution metadata. Tests, caches, private directories, credentials, sessions, memories, bytecode, and secret-like content are forbidden. A mismatch blocks publication; it must not be waived by deleting the expected item from the release contract.

Maintainers will acknowledge valid private reports when possible, investigate, add regression coverage, and coordinate disclosure. No fixed response timeline is guaranteed.
