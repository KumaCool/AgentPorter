from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

PRODUCT_ID: Final = "abf0d29a-122e-4deb-9b86-e0aa8f157c93"
COMPONENT_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "luna_worker": "5c7f978c-a9a6-4cec-98fa-e65bbf8101cd",
        "codex_5_3_small_worker": "7dab98fb-9ac0-44fa-90fb-4a4f30e1470c",
    }
)
INITIAL_PROFILE_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "luna_worker": "luna_worker",
        "codex_5_3_small_worker": "codex-5-3-small-worker",
    }
)
