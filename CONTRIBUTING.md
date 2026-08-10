# Contributing to AgentPorter

Thanks for considering a contribution. AgentPorter is currently in its design stage; executable implementation has not started, so proposals should preserve its safety-first, fail-closed Profile installation and uninstall model.

## Before you start

- Check existing issues and discussions before starting substantial work.
- Open an issue before making architectural changes or adding a platform adapter.
- Keep each change focused on one clearly stated problem.
- Do not include credentials, tokens, cookies, private hostnames, personal paths, private configuration, or generated runtime data.

## Development workflow

1. Fork the repository and create a focused branch.
2. Add or update tests for behavioral changes.
3. Keep Hermes-specific behavior inside `HermesAdapter`; other platforms require separate evidence and approval.
4. Use temporary configuration roots in tests; never modify a developer's real Agent configuration.
5. Run the repository's documented checks. Until executable code lands, verify at minimum:

   ```bash
   git diff --check
   ```

6. Update user and design documentation when behavior or interfaces change.
7. Submit a pull request describing the motivation, scope, verification performed, and any compatibility or security impact.

## Hermes implementation requirements

Hermes changes must preserve the consolidated [install/uninstall design](docs/03-installation-and-uninstall-design.md):

- complete preflight and one readable plan before writes;
- no overwrite of existing/default Profiles;
- compensation limited to Profiles proven to be created by the current installation transaction;
- name-independent product/component/install identity;
- uninstall warning, confirmation, fail-closed discovery, native deletion, and readback;
- tests proving unrelated configuration remains unchanged.

Do not claim model, platform, or security parity without real evidence. Other platform adapters require a separately approved design and native validation path.

Worker behavior and performance evaluation follows the independent [validation and benchmark plan](docs/plan/02-agent-validation-and-benchmark.md). It must remain isolated from installer success, use disposable environments and sanitized fixtures, and never commit raw model output or credential-bearing reports.

## Reporting security issues

Do not open a public issue for suspected vulnerabilities or accidental disclosure. Follow [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the repository's [MIT License](LICENSE).
