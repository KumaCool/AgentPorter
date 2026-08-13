from __future__ import annotations

import json
import os
from pathlib import Path
from subprocess import CompletedProcess

from agentporter.hermes_runtime import HermesRuntime
from agentporter.runtime_probe import run_runtime_probe


def test_isolated_hermes_v020_public_cli_shape_is_restricted_without_real_call(
    tmp_path: Path,
) -> None:
    """Controlled v0.20 fixture: no credentials, Gateway, Kanban, or outbound model call."""
    hermes = tmp_path / "fixture-hermes-v0.20.0"
    hermes.write_text("#!/bin/sh\n", encoding="utf-8")
    hermes.chmod(0o700)
    home = tmp_path / "hermes-home"
    home.mkdir()
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> CompletedProcess[str]:
        calls.append(argv)
        if argv[-3:] == ("auth", "status", "fake-provider"):
            return CompletedProcess(argv, 0, "No credentials configured", "")
        usage = Path(argv[argv.index("--usage-file") + 1])
        prompt = argv[argv.index("-z") + 1]
        nonce = prompt.removeprefix("Reply exactly AGENTPORTER_READY:")
        usage.write_text(
            json.dumps(
                {
                    "model": "fixture-model",
                    "provider": "fake-provider",
                    "api_calls": 1,
                    "completed": True,
                    "failed": False,
                }
            ),
            encoding="utf-8",
        )
        return CompletedProcess(argv, 0, f"AGENTPORTER_READY:{nonce}\n", "")

    adapter = HermesRuntime(hermes, command_runner=runner)
    assert (
        adapter.auth_status("worker", "fake-provider", source_env={"HOME": str(home)})
        == "logged-out"
    )
    observation = adapter.oneshot(
        "worker", "fixture-model", "fake-provider", source_env={"HOME": str(home)}
    )
    result = run_runtime_probe(
        expected_model="fixture-model",
        expected_provider="fake-provider",
        runner=lambda nonce, _directory: type(observation)(
            output=f"AGENTPORTER_READY:{nonce}",
            actual_model=observation.actual_model,
            actual_provider=observation.actual_provider,
            api_calls=observation.api_calls,
            tool_calls=observation.tool_calls,
            fallback_used=observation.fallback_used,
        ),
    )
    assert result.status == "route-proof-incomplete"
    assert all(
        "gateway" not in " ".join(argv).lower() and "kanban" not in " ".join(argv).lower()
        for argv in calls
    )
    assert "OPENAI_API_KEY" not in os.environ or all("OPENAI_API_KEY" not in argv for argv in calls)
