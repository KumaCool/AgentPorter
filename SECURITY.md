# Security Policy

## Supported versions

AgentPorter is currently in a pre-release design stage; executable implementation has not started. No production-ready or security-supported release exists yet. Once releases are published, this section will list the supported version range.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's **Security → Report a vulnerability** feature for this repository. If private vulnerability reporting is not enabled, contact the maintainers through a private channel listed in the repository hosting profile rather than opening a public issue.

Include only the information needed to reproduce and assess the issue:

- affected version or commit;
- affected Adapter or installer/uninstaller entry;
- reproduction steps using sanitized data;
- expected and observed behavior;
- potential impact.

Do **not** attach real API keys, tokens, cookies, private configuration files, personal paths, private hostnames, or third-party data. Revoke exposed credentials immediately; deleting them from a later commit is not sufficient.

## Security boundaries

AgentPorter is intended to create and remove dedicated Hermes Profiles. Implementations and contributions must therefore preserve these boundaries:

- complete installation preflight and preview before any write;
- refuse to overwrite pre-existing or default Profiles;
- compensate only current-transaction Profiles with complete creation and identity evidence;
- discover uninstall targets from protocol-fixed product/component fields and a per-installation ID, never user-editable names;
- require installation-bound confirmation and warn that uninstall deletes all Profile-local data;
- fail closed on ambiguous markers, paths, symlinks, or concurrent identity changes;
- use Hermes native deletion without an AgentPorter-owned recursive-directory fallback;
- preserve unrelated Profiles and avoid copying authentication material;
- redact secret-like values from plans, logs, and reports.

The optional post-install Worker benchmark is not part of installation. It must run only after explicit cost authorization in disposable Hermes/Profile and repository environments, discover targets by the AgentPorter marker protocol, reject ambiguous sets before model calls, and keep raw responses and usage artifacts out of Git by default.

The local marker is a non-secret ownership claim, not a signature or user-authentication credential. A malformed, copied, conflicting, or changed marker must make discovery fail closed rather than be treated as cryptographic provenance.

`agentporter-profile.json` is an AgentPorter-reserved protocol filename. Unrelated tools should not create it inside Hermes Profiles; any malformed or conflicting use intentionally blocks automated uninstall rather than being ignored.

A successful syntax check does not prove that a model is authorized, that a remote service is trusted, or that a generated Worker is safe for arbitrary tasks.

## Disclosure process

Maintainers will acknowledge a valid private report, investigate impact, prepare a fix and tests, and coordinate disclosure appropriate to the severity. Timelines cannot be guaranteed while the project remains pre-release.
