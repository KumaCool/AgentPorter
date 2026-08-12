"""Dedicated AgentPorter activation console entry."""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable, Mapping
from typing import TextIO

from .activation_application import (
    ActivationBindingInput,
    ActivationResult,
    ActivationStatus,
    apply_activation,
    build_activation_plan,
)
from .hermes import HermesDetection, detect_hermes
from .uninstall_application import minimal_process_environment
from .uninstall_discovery import discover_installation


def _read_endpoint(prompt: str, *, reader: Callable[[str], str] = getpass.getpass) -> str:
    """Read a private endpoint without terminal echo or command-line exposure."""
    return reader(prompt)


def run_activator(
    env: Mapping[str, str],
    *,
    detector: Callable[..., HermesDetection] = detect_hermes,
    input_fn: Callable[[str], str] = input,
    endpoint_reader: Callable[[str], str] = _read_endpoint,
    output: TextIO | None = None,
) -> ActivationResult:
    """Discover the sole installation, collect bindings, and execute one transaction."""
    found = detector(env=env)
    discovery = discover_installation(found.profiles_root)
    inputs: dict[str, ActivationBindingInput] = {}
    for target in discovery.targets:
        provider = input_fn(f"Provider ID for {target.current_name}: ").strip()
        endpoint = endpoint_reader(f"Endpoint for {target.current_name} (hidden): ")
        grant = input_fn("Credential grant (external-secret/profile-auth/profile-env): ").strip()
        state = input_fn("Credential state (unresolved/operator-authorized): ").strip()
        if grant not in {"external-secret", "profile-auth", "profile-env"}:
            raise SystemExit("AgentPorter activation invalid credential grant")
        if state not in {"unresolved", "operator-authorized"}:
            raise SystemExit("AgentPorter activation invalid credential state")
        inputs[target.component_id] = ActivationBindingInput(
            provider,
            endpoint,
            grant,  # type: ignore[arg-type]
            state,  # type: ignore[arg-type]
        )
    plan = build_activation_plan(discovery, found, inputs)
    kwargs: dict[str, object] = {"input_fn": input_fn}
    if output is not None:
        kwargs["output"] = output
    return apply_activation(plan, **kwargs)  # type: ignore[arg-type]


def main() -> None:
    """Run activation with a credential-free process environment."""
    result = run_activator(minimal_process_environment(os.environ))
    if result.status not in (ActivationStatus.ACTIVATED, ActivationStatus.CREDENTIAL_REQUIRED):
        raise SystemExit(f"AgentPorter activation {result.status}")


if __name__ == "__main__":
    main()
