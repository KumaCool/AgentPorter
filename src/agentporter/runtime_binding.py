"""Secret-safe runtime binding plans and receipts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

CredentialGrantKind = Literal["external-secret", "profile-auth", "profile-env"]
CredentialState = Literal["unresolved", "operator-authorized"]


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def _endpoint_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeBindingReceipt:
    component_id: str
    profile_name: str
    model: str
    provider: str
    endpoint_digest: str
    credential_grant_kind: CredentialGrantKind
    credential_state: CredentialState
    hermes_version: str


@dataclass(frozen=True, slots=True)
class RuntimeBindingPlan:
    portable_id: str
    component_id: str
    current_profile_name: str
    expected_model: str
    provider_id: str
    endpoint_value: str = field(repr=False)
    endpoint_digest: str
    credential_grant_kind: CredentialGrantKind
    credential_state: CredentialState
    hermes_version: str
    fallback_policy: Literal["forbidden"] = "forbidden"

    @classmethod
    def from_values(
        cls,
        *,
        portable_id: str,
        component_id: str,
        current_profile_name: str,
        expected_model: str,
        provider_id: str,
        endpoint_value: str,
        credential_grant_kind: CredentialGrantKind,
        credential_state: CredentialState,
        hermes_version: str,
    ) -> RuntimeBindingPlan:
        endpoint = _required("endpoint_value", endpoint_value)
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("endpoint_value must be an absolute HTTP(S) URL")
        return cls(
            portable_id=_required("portable_id", portable_id),
            component_id=_required("component_id", component_id),
            current_profile_name=_required("current_profile_name", current_profile_name),
            expected_model=_required("expected_model", expected_model),
            provider_id=_required("provider_id", provider_id),
            endpoint_value=endpoint,
            endpoint_digest=_endpoint_digest(endpoint),
            credential_grant_kind=credential_grant_kind,
            credential_state=credential_state,
            hermes_version=_required("hermes_version", hermes_version),
        )

    def __post_init__(self) -> None:
        if self.endpoint_digest != _endpoint_digest(self.endpoint_value):
            raise ValueError("endpoint_digest does not match endpoint_value")
        if self.credential_grant_kind not in {
            "external-secret",
            "profile-auth",
            "profile-env",
        }:
            raise ValueError("invalid credential_grant_kind")
        if self.credential_state not in {"unresolved", "operator-authorized"}:
            raise ValueError("invalid credential_state")
        if self.fallback_policy != "forbidden":
            raise ValueError("fallback policy must be forbidden")

    def safe_receipt(self) -> RuntimeBindingReceipt:
        return RuntimeBindingReceipt(
            component_id=self.component_id,
            profile_name=self.current_profile_name,
            model=self.expected_model,
            provider=self.provider_id,
            endpoint_digest=self.endpoint_digest,
            credential_grant_kind=self.credential_grant_kind,
            credential_state=self.credential_state,
            hermes_version=self.hermes_version,
        )
