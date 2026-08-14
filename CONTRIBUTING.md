# Contributing to AgentPorter

AgentPorter v0.2.0 is the prepared release candidate for role-based Profile identities and explicit model/provider/endpoint bindings; v0.1.8 remains the published baseline until publication and hosted readback. [Plan 06](docs/plan/06-role-identities-and-configurable-model-binding.md) and its [design](docs/06-role-identities-and-configurable-model-binding-design.md) are the current authority. Contributions must not modify Hermes source or weaken credential, lifecycle, or evidence boundaries.

## Before you start

- Open an issue before changing architecture, the marker protocol, or platform scope.
- Keep changes focused and use test-driven development for behavior changes.
- Never commit credentials, tokens, cookies, private hostnames or paths, runtime state, model output, caches, or generated profile data.
- Other platform adapters require separately approved design and native evidence.

## Development setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e . pytest pyright ruff build
```

## Required local gates

Run exactly these checks before opening a pull request:

```bash
python -m ruff format --check .
python -m ruff check .
python -m pyright
python -m pytest \
  --ignore=tests/test_phase3_real_hermes.py \
  --ignore=tests/test_phase4_real_hermes.py \
  --ignore=tests/test_phase5_formal_acceptance.py \
  --ignore=tests/test_phase5_stress_acceptance.py \
  --ignore=tests/test_phase7_real_hermes_orchestration.py \
  --ignore=tests/test_phase8_authorized_live_probe.py
python -m build
```

The multiline `pytest` form above is for POSIX shells. The default GitHub Actions matrix runs the complete portable offline suite and package/release contracts on Linux and macOS with Python 3.11–3.13. Windows runs format, lint, Linux-targeted strict typing, and distribution builds; it does not claim native execution of descriptor-bound POSIX lifecycle or archive-mode contracts. The resource-backed Phase 5 stress suite is Linux-only and remains covered by the Linux release gate.

Real-Hermes tests are deliberately separate because they need a known Hermes executable at `/usr/local/lib/hermes-agent/venv/bin/hermes`. A maintainer may run the manual **Real Hermes acceptance** workflow with the observed Hermes version. Static/lifecycle tests make no model calls and require no provider credentials. Plan 05 may use Hermes v0.20 public one-shot and usage reports only after explicit authorization; missing tool/fallback telemetry must remain `route-proof-incomplete`, never be promoted to strict runtime readiness. Kanban mutation acceptance remains separately unsupported and must make zero adapter calls by default.

After packaging is reconciled, build into an empty temporary directory and run `scripts/verify_release.py` with the exact package version, dependency, entry-point, and resource contract documented by the release commit. Do not weaken the verifier to make an unexpected artifact pass.

## Safety invariants

Changes must preserve the [install/uninstall design](docs/03-installation-and-uninstall-design.md) and the [multi-agent orchestration plan](docs/plan/02-multi-agent-orchestration.md): complete preflight and preview before writes; no overwrite; current-transaction-only compensation; name-independent marker identity; explicit uninstall warning and confirmation; collection and per-target revalidation; native deletion; unrelated configuration preservation.

Update user, security, design, and changelog documentation when behavior or release contracts change. Pull requests must state scope, test evidence, compatibility impact, security impact, and whether real-Hermes acceptance was performed.

Report vulnerabilities privately according to [SECURITY.md](SECURITY.md). Contributions are licensed under the [MIT License](LICENSE).

v0.2.0 release candidate

The candidate chains activation after install and supports Hermes v0.20 custom providers by transactionally inheriting one exact main/default Profile provider definition. Tests must prove no `auth add/status` calls, source-config CAS/revalidation, preservation of unrelated Worker providers, no provider-definition disclosure in output/receipts/argv, and retained retryability after activation failure. No real model call belongs in the portable gate.
