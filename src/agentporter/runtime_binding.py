"""Secret-safe runtime binding plans, gates, fingerprints, and receipts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Literal
from urllib.parse import urlsplit

CredentialGrantKind = Literal["external-secret", "profile-auth", "profile-env"]
CredentialState = Literal["unresolved", "operator-authorized"]
BindingGateStatus = Literal[
    "configuration-required",
    "credential-required",
    "probe-unsupported",
    "probe-started",
    "canary-required",
]
LifecycleOperation = Literal["activate", "install", "update", "uninstall", "static-readback"]


def _required(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def _valid_endpoint(value: str | None) -> bool:
    if value is None:
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme in {"http", "https"} and parsed.hostname is not None


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
    config_digest: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-ready receipt containing only non-secret values."""
        return asdict(self)


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
    config_digest: str
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
        config_digest: str,
    ) -> RuntimeBindingPlan:
        endpoint = endpoint_value.strip()
        if not _valid_endpoint(endpoint):
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
            config_digest=_required("config_digest", config_digest),
        )

    def __post_init__(self) -> None:
        if self.endpoint_digest != _endpoint_digest(self.endpoint_value):
            raise ValueError("endpoint digest mismatch")
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
            config_digest=self.config_digest,
        )


@dataclass(frozen=True, slots=True)
class BindingGateResult:
    status: BindingGateStatus
    temporary_evidence_created: bool = False


def binding_fingerprint(plan: RuntimeBindingPlan) -> str:
    """Hash a canonical allowlist; never serialize endpoint or credential material."""
    payload = {
        "component_id": plan.component_id,
        "config_digest": plan.config_digest,
        "credential_grant_kind": plan.credential_grant_kind,
        "credential_state": plan.credential_state,
        "endpoint_digest": plan.endpoint_digest,
        "expected_model": plan.expected_model,
        "fallback_policy": plan.fallback_policy,
        "hermes_version": plan.hermes_version,
        "portable_id": plan.portable_id,
        "profile_name": plan.current_profile_name,
        "provider_id": plan.provider_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def evaluate_binding_gate(
    *,
    provider_id: str | None,
    endpoint_value: str | None,
    credential_state: str | None,
    probe_supported: bool,
    runner: Callable[[], object],
    lifecycle_operation: LifecycleOperation = "activate",
) -> BindingGateResult:
    """Enforce config → credential → capability before exactly one probe call."""
    if lifecycle_operation != "activate":
        return BindingGateResult("canary-required")
    if provider_id is None or not provider_id.strip() or not _valid_endpoint(endpoint_value):
        return BindingGateResult("configuration-required")
    if credential_state != "operator-authorized":
        return BindingGateResult("credential-required")
    if not probe_supported:
        return BindingGateResult("probe-unsupported")
    runner()
    return BindingGateResult("probe-started", temporary_evidence_created=True)
