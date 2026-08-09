# Security Policy

## Supported versions

AgentPorter is currently in a pre-release design and implementation stage. No production-ready or security-supported release exists yet. Once releases are published, this section will list the supported version range.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's **Security → Report a vulnerability** feature for this repository. If private vulnerability reporting is not enabled, contact the maintainers through a private channel listed in the repository hosting profile rather than opening a public issue.

Include only the information needed to reproduce and assess the issue:

- affected version or commit;
- affected adapter or command;
- reproduction steps using sanitized data;
- expected and observed behavior;
- potential impact.

Do **not** attach real API keys, tokens, cookies, private configuration files, personal paths, private hostnames, or third-party data. Revoke exposed credentials immediately; deleting them from a later commit is not sufficient.

## Security boundaries

AgentPorter is intended to modify Agent configuration. Implementations and contributions must therefore preserve these boundaries:

- preview changes before writing by default;
- modify only AgentPorter-owned files or explicitly managed configuration sections;
- preserve unrelated user configuration;
- avoid copying authentication material between machines;
- require explicit remote targets and authorization;
- validate generated configuration with the target platform where possible;
- restore a verified snapshot if application or validation fails;
- redact secret-like values from plans, diffs, logs, and reports.

A successful syntax check does not prove that a model is authorized, that a remote service is trusted, or that a generated Worker is safe for arbitrary tasks.

## Disclosure process

Maintainers will acknowledge a valid private report, investigate impact, prepare a fix and tests, and coordinate disclosure appropriate to the severity. Timelines cannot be guaranteed while the project remains pre-release.
