from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

PRODUCT_ID: Final = "abf0d29a-122e-4deb-9b86-e0aa8f157c93"
COMPONENT_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bounded_worker": "5c7f978c-a9a6-4cec-98fa-e65bbf8101cd",
        "mechanical_worker": "7dab98fb-9ac0-44fa-90fb-4a4f30e1470c",
    }
)
ORCHESTRATOR_COMPONENT_ID: Final = "ee21f7f8-5a9d-4cf2-9e57-2508034cadc7"
INSTALL_COMPONENT_IDS: Final[Mapping[str, str]] = MappingProxyType(dict(COMPONENT_IDS))
LEGACY_V020_COMPONENT_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {**COMPONENT_IDS, "agentporter_orchestrator": ORCHESTRATOR_COMPONENT_ID}
)
INITIAL_PROFILE_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bounded_worker": "agentporter-bounded-worker",
        "mechanical_worker": "agentporter-mechanical-worker",
    }
)

LEGACY_PORTABLE_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {"luna_worker": "bounded_worker", "codex_5_3_small_worker": "mechanical_worker"}
)
LEGACY_INITIAL_PROFILE_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bounded_worker": "luna_worker",
        "mechanical_worker": "codex-5-3-small-worker",
        "agentporter_orchestrator": "agentporter-orchestrator",
    }
)
_PORTABLE_ID_BY_COMPONENT: Final[Mapping[str, str]] = MappingProxyType(
    {component_id: portable_id for portable_id, component_id in LEGACY_V020_COMPONENT_IDS.items()}
)


def normalize_portable_id(portable_id: str) -> str:
    current = LEGACY_PORTABLE_IDS.get(portable_id, portable_id)
    if current not in LEGACY_V020_COMPONENT_IDS:
        raise ValueError("unknown Portable ID")
    return current


def portable_id_for_component(component_id: str) -> str:
    try:
        return _PORTABLE_ID_BY_COMPONENT[component_id]
    except KeyError as error:
        raise ValueError("unknown component") from error
