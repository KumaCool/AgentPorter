# Contributing to AgentPorter

Thanks for considering a contribution. AgentPorter is currently in its design and early implementation stage, so proposals should preserve its safety-first, non-destructive configuration model.

## Before you start

- Check existing issues and discussions before starting substantial work.
- Open an issue before making architectural changes or adding a platform adapter.
- Keep each change focused on one clearly stated problem.
- Do not include credentials, tokens, cookies, private hostnames, personal paths, private configuration, or generated runtime data.

## Development workflow

1. Fork the repository and create a focused branch.
2. Add or update tests for behavioral changes.
3. Keep platform-specific behavior inside its adapter.
4. Use temporary configuration roots in tests; never modify a developer's real Agent configuration.
5. Run the repository's documented checks. Until executable code lands, verify at minimum:

   ```bash
   git diff --check
   ```

6. Update user and design documentation when behavior or interfaces change.
7. Submit a pull request describing the motivation, scope, verification performed, and any compatibility or security impact.

## Adapter requirements

A new platform adapter must include:

- capability detection and a documented compatibility boundary;
- dry-run planning and a readable diff;
- non-destructive merge behavior;
- native syntax or platform validation where available;
- rollback behavior limited to Profiles proven to be created by the current installation transaction;
- tests proving unrelated user configuration remains unchanged.

Do not claim feature parity when a platform cannot preserve a portable Worker requirement. Report the limitation explicitly and fail closed where proceeding would weaken a required invariant.

## Reporting security issues

Do not open a public issue for suspected vulnerabilities or accidental disclosure. Follow [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the repository's [MIT License](LICENSE).
