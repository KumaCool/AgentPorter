"""Plan 06 role-owned inference binding and responsibility routing candidates.

This module is deliberately independent from the shared identity/manifest/planning
modules so the serial integrator can connect it after the role-key migration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit


class Responsibility(StrEnum):
    BOUNDED = "bounded"
    MECHANICAL = "mechanical"
    ORCHESTRATOR = "orchestrator"


class CredentialGrantSelection(StrEnum):
    EXISTING_PROFILE_DEFINITION = "existing-profile-definition"
    EXPLICIT_SOURCE_INHERITANCE = "explicit-source-inheritance"
    PROFILE_AUTH = "profile-auth"


CredentialGrantClassification = Literal[
    "existing-profile-definition",
    "explicit-source-inheritance",
    "profile-auth",
    "configuration-required",
]


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def _endpoint(value: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("endpoint must not contain credentials")
    return normalized


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BindingSelection:
    portable_id: str
    component_id: str
    profile_name: str
    model: str
    provider: str
    endpoint: str = field(repr=False)
    endpoint_digest: str
    credential_grant: CredentialGrantSelection

    @classmethod
    def create(
        cls,
        *,
        portable_id: str,
        component_id: str,
        profile_name: str,
        model: str,
        provider: str,
        endpoint: str,
        credential_grant: CredentialGrantSelection,
    ) -> BindingSelection:
        sealed_endpoint = _endpoint(endpoint)
        return cls(
            _required("portable_id", portable_id),
            _required("component_id", component_id),
            _required("profile_name", profile_name),
            _required("model", model),
            _required("provider", provider),
            sealed_endpoint,
            _digest(sealed_endpoint),
            credential_grant,
        )

    def __post_init__(self) -> None:
        for name in ("portable_id", "component_id", "profile_name", "model", "provider"):
            _required(name, getattr(self, name))
        if self.endpoint_digest != _digest(_endpoint(self.endpoint)):
            raise ValueError("endpoint digest mismatch")
        if type(self.credential_grant) is not CredentialGrantSelection:
            raise ValueError("credential grant must be explicit")


@dataclass(frozen=True, slots=True)
class RoleBindingSet:
    items: tuple[BindingSelection, ...]
    fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        expected_components: Mapping[str, str],
        selections: Mapping[str, BindingSelection],
    ) -> RoleBindingSet:
        if set(selections) != set(expected_components):
            raise ValueError("binding selection is not closed")
        ordered: list[BindingSelection] = []
        for portable_id, component_id in expected_components.items():
            item = selections[portable_id]
            if item.portable_id != portable_id or item.component_id != component_id:
                raise ValueError("binding selection identity mismatch")
            ordered.append(item)
        if len({item.component_id for item in ordered}) != len(ordered):
            raise ValueError("binding selection contains duplicate components")
        payload = [
            {
                "portable_id": item.portable_id,
                "component_id": item.component_id,
                "profile_name": item.profile_name,
                "model": item.model,
                "provider": item.provider,
                "endpoint_digest": item.endpoint_digest,
                "credential_grant": item.credential_grant.value,
            }
            for item in ordered
        ]
        fingerprint = _digest(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return cls(tuple(ordered), fingerprint)

    def safe_summary(self) -> tuple[Mapping[str, str], ...]:
        return tuple(
            MappingProxyType(
                {
                    "role": item.portable_id,
                    "profile": item.profile_name,
                    "model": item.model,
                    "provider": item.provider,
                    "endpoint": f"sha256:{item.endpoint_digest[:12]}",
                    "credential_grant": item.credential_grant.value,
                }
            )
            for item in self.items
        )


def classify_credential_grant(
    *,
    portable_id: str,
    existing_profile_definition: bool,
    requested: CredentialGrantSelection | None,
    source_profile_kind: Literal["main-default", "worker"] | None = None,
) -> CredentialGrantClassification:
    """Classify grants without reading or returning a provider definition."""
    if requested is None:
        return "configuration-required"
    if requested is CredentialGrantSelection.EXISTING_PROFILE_DEFINITION:
        if not existing_profile_definition:
            raise ValueError("Profile has no own definition to retain")
        return "existing-profile-definition"
    if requested is CredentialGrantSelection.EXPLICIT_SOURCE_INHERITANCE:
        if source_profile_kind != "main-default":
            if portable_id == "agentporter_orchestrator":
                raise ValueError("orchestrator cannot inherit a Worker definition")
            raise ValueError("provider definition source must be main/default")
        return "explicit-source-inheritance"
    if requested is CredentialGrantSelection.PROFILE_AUTH:
        return "profile-auth"
    raise ValueError("unsupported credential grant")


def authorize_responsibility_route(
    *,
    responsibility: Responsibility,
    requested_work: Responsibility,
    model: str,
) -> bool:
    """Authorize solely by fixed responsibility; model is only completeness input."""
    _required("model", model)
    if (
        responsibility is Responsibility.ORCHESTRATOR
        and requested_work is not Responsibility.ORCHESTRATOR
    ):
        raise ValueError("orchestrator cannot execute implementation work")
    if (
        responsibility is Responsibility.MECHANICAL
        and requested_work is not Responsibility.MECHANICAL
    ):
        raise ValueError("requested work exceeds mechanical responsibility")
    if responsibility is Responsibility.BOUNDED and requested_work is Responsibility.ORCHESTRATOR:
        raise ValueError("requested work exceeds bounded responsibility")
    return responsibility is requested_work
