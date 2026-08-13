"""Dedicated AgentPorter activation console entry."""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

from .activation_application import (
    ActivationBindingInput,
    ActivationResult,
    ActivationStatus,
    apply_activation,
    build_activation_plan,
)
from .hermes import HermesDetection, detect_hermes
from .hermes_runtime import HermesRuntime
from .identity import COMPONENT_IDS
from .runtime_binding import RuntimeBindingPlan
from .runtime_probe import ProbeObservation
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
    runtime_factory: Callable[[Path], HermesRuntime] = HermesRuntime,
) -> ActivationResult:
    """Discover the sole installation, collect bindings, and execute one transaction."""
    found = detector(env=env)
    discovery = discover_installation(found.profiles_root)
    inputs: dict[str, ActivationBindingInput] = {}
    targets = {target.component_id: target for target in discovery.targets}
    if not set(COMPONENT_IDS.values()) <= set(targets):
        raise SystemExit("AgentPorter activation requires both worker components")
    for component_id in COMPONENT_IDS.values():
        target = targets[component_id]
        provider = input_fn(f"Provider ID for {target.current_name}: ").strip()
        endpoint = endpoint_reader(f"Endpoint for {target.current_name} (hidden): ")
        inputs[target.component_id] = ActivationBindingInput(
            provider,
            endpoint,
            "custom-provider-config",
            "operator-authorized",
        )
    plan = build_activation_plan(discovery, found, inputs)
    runtime = runtime_factory(found.executable)

    def auth_status(binding: RuntimeBindingPlan) -> str:
        return runtime.auth_status(
            binding.current_profile_name, binding.provider_id, source_env=env
        )

    def auth_add(binding: RuntimeBindingPlan) -> None:
        runtime.auth_add(binding.current_profile_name, binding.provider_id, source_env=env)

    def probe(binding: RuntimeBindingPlan, _nonce: str, _directory: Path) -> ProbeObservation:
        return runtime.oneshot(
            binding.current_profile_name,
            binding.expected_model,
            binding.provider_id,
            source_env=env,
            nonce=_nonce,
        )

    kwargs: dict[str, object] = {
        "input_fn": input_fn,
        "auth_status_runner": auth_status,
        "auth_add_runner": auth_add,
        "probe_runner": probe,
        "probe_supported": True,
        "require_runtime_confirmations": True,
    }
    if output is not None:
        kwargs["output"] = output
    return apply_activation(plan, **kwargs)  # type: ignore[arg-type]


def main() -> None:
    """Run activation with a credential-free process environment."""
    result = run_activator(minimal_process_environment(os.environ))
    if result.status not in (
        ActivationStatus.ACTIVATED,
        ActivationStatus.RESTRICTED,
        ActivationStatus.CREDENTIAL_REQUIRED,
    ):
        raise SystemExit(f"AgentPorter activation {result.status}")


if __name__ == "__main__":
    main()
