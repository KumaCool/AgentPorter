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
from .identity import INSTALL_COMPONENT_IDS
from .plan06_role_bindings import CredentialGrantSelection, classify_credential_grant
from .role_name_migration_application import (
    RoleMigrationApplicationStatus,
    run_role_name_migration_gate,
)
from .runtime_binding import RuntimeBindingPlan
from .runtime_probe import ProbeObservation
from .uninstall_application import minimal_process_environment
from .uninstall_discovery import discover_installation


def _default_migration_journal(found: HermesDetection) -> Path:
    """Keep authority outside Hermes Profiles under AgentPorter's private local root."""
    return found.hermes_home.parent / "agentporter" / "role-name-migration.json"


def run_activation_with_role_migration(
    env: Mapping[str, str],
    *,
    detector: Callable[..., HermesDetection] = detect_hermes,
    input_fn: Callable[[str], str] = input,
    endpoint_reader: Callable[[str], str] | None = None,
    output: TextIO | None = None,
    runtime_factory: Callable[[Path], HermesRuntime] = HermesRuntime,
) -> ActivationResult:
    """Public activate composition: independent rename gate before binding/canary gates."""
    found = detector(env=env)
    activation: ActivationResult | None = None

    def binding_gate() -> None:
        nonlocal activation
        activation = _run_binding_activation(
            env,
            detector=detector,
            input_fn=input_fn,
            endpoint_reader=endpoint_reader or _read_endpoint,
            output=output,
            runtime_factory=runtime_factory,
        )

    migration = run_role_name_migration_gate(
        env,
        detector=detector,
        journal_path=_default_migration_journal(found),
        input_fn=input_fn,
        binding_continuation=binding_gate,
    )
    if activation is not None:
        return activation
    status = {
        RoleMigrationApplicationStatus.LEGACY_NAME_MIGRATION_REQUIRED: (
            ActivationStatus.LEGACY_NAME_MIGRATION_REQUIRED
        ),
        RoleMigrationApplicationStatus.MIGRATION_AMBIGUOUS: (
            ActivationStatus.MIGRATION_STATE_AMBIGUOUS
        ),
        RoleMigrationApplicationStatus.NAME_CONFLICT: ActivationStatus.NAME_CONFLICT,
    }.get(migration.status, ActivationStatus.FAILED)
    return ActivationResult(status)


def _read_endpoint(prompt: str, *, reader: Callable[[str], str] = getpass.getpass) -> str:
    """Read a private endpoint without terminal echo or command-line exposure."""
    return reader(prompt)


def _run_binding_activation(
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
    if not set(INSTALL_COMPONENT_IDS.values()) <= set(targets):
        raise SystemExit("AgentPorter activation requires all three components")
    for component_id in INSTALL_COMPONENT_IDS.values():
        target = targets[component_id]
        model = input_fn(f"Model ID for {target.current_name}: ").strip()
        provider = input_fn(f"Provider ID for {target.current_name}: ").strip()
        endpoint = endpoint_reader(f"Endpoint for {target.current_name} (hidden): ")
        raw_grant = input_fn(
            f"Credential grant for {target.current_name} "
            "(existing-profile-definition/explicit-source-inheritance/profile-auth, "
            "blank=configuration-required): "
        ).strip()
        requested = CredentialGrantSelection(raw_grant) if raw_grant else None
        classification = classify_credential_grant(
            portable_id=next(
                portable
                for portable, expected_component in INSTALL_COMPONENT_IDS.items()
                if expected_component == component_id
            ),
            existing_profile_definition=True,
            requested=requested,
            source_profile_kind="main-default"
            if requested is CredentialGrantSelection.EXPLICIT_SOURCE_INHERITANCE
            else None,
        )
        grant_kind = classification
        credential_state = (
            "unresolved" if classification == "configuration-required" else "operator-authorized"
        )
        inputs[target.component_id] = ActivationBindingInput(
            model,
            provider,
            endpoint,
            grant_kind,
            credential_state,
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


def run_activator(
    env: Mapping[str, str],
    *,
    detector: Callable[..., HermesDetection] = detect_hermes,
    input_fn: Callable[[str], str] = input,
    endpoint_reader: Callable[[str], str] = _read_endpoint,
    output: TextIO | None = None,
    runtime_factory: Callable[[Path], HermesRuntime] = HermesRuntime,
) -> ActivationResult:
    """Public activator with the independently authorized role-name migration gate."""
    return run_activation_with_role_migration(
        env,
        detector=detector,
        input_fn=input_fn,
        endpoint_reader=endpoint_reader,
        output=output,
        runtime_factory=runtime_factory,
    )


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
