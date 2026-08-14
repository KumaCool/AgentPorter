"""Name-independent role projection over the immutable published component UUIDs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .identity import COMPONENT_IDS, ORCHESTRATOR_COMPONENT_ID
from .uninstall_discovery import DiscoveryResult, DiscoveryStatus


class RoleIdentityError(ValueError):
    """A role identity cannot be safely projected."""


_LEGACY_COMPONENTS = tuple(COMPONENT_IDS.values())
CANONICAL_COMPONENT_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bounded_worker": _LEGACY_COMPONENTS[0],
        "mechanical_worker": _LEGACY_COMPONENTS[1],
        "agentporter_orchestrator": ORCHESTRATOR_COMPONENT_ID,
    }
)
LEGACY_PORTABLE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "luna_worker": "bounded_worker",
        "codex_5_3_small_worker": "mechanical_worker",
    }
)
CURRENT_INITIAL_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bounded_worker": "agentporter-bounded-worker",
        "mechanical_worker": "agentporter-mechanical-worker",
        "agentporter_orchestrator": "agentporter-orchestrator",
    }
)
LEGACY_INITIAL_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bounded_worker": "luna_worker",
        "mechanical_worker": "codex-5-3-small-worker",
        "agentporter_orchestrator": "agentporter-orchestrator",
    }
)
_COMPONENT_TO_ROLE: Final = MappingProxyType(
    {component_id: portable_id for portable_id, component_id in CANONICAL_COMPONENT_IDS.items()}
)


@dataclass(frozen=True, slots=True)
class RoleProjection:
    portable_id: str
    component_id: str
    current_profile_name: str
    installation_id: str


def canonical_portable_id(value: str, *, for_write: bool) -> str:
    if value in CANONICAL_COMPONENT_IDS:
        return value
    alias = LEGACY_PORTABLE_ALIASES.get(value)
    if alias is None:
        raise RoleIdentityError("unknown portable role identity")
    if for_write:
        raise RoleIdentityError("legacy portable identity is read-only")
    return alias


def project_discovery_roles(discovery: DiscoveryResult) -> tuple[RoleProjection, ...]:
    if discovery.status is not DiscoveryStatus.READY:
        raise RoleIdentityError("role projection requires one complete installation")
    by_component = {target.component_id: target for target in discovery.targets}
    if len(by_component) != len(discovery.targets):
        raise RoleIdentityError("role projection requires unique components")
    observed = set(by_component)
    required = set(CANONICAL_COMPONENT_IDS.values())
    legacy = set(_LEGACY_COMPONENTS)
    if observed not in (required, legacy):
        raise RoleIdentityError("role projection requires a recognized complete component set")
    installation_ids = {target.installation_id for target in discovery.targets}
    if len(installation_ids) != 1:
        raise RoleIdentityError("role projection requires one installation id")
    return tuple(
        RoleProjection(
            portable_id=_COMPONENT_TO_ROLE[component_id],
            component_id=component_id,
            current_profile_name=by_component[component_id].current_name,
            installation_id=by_component[component_id].installation_id,
        )
        for component_id in CANONICAL_COMPONENT_IDS.values()
        if component_id in by_component
    )
