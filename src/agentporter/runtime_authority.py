"""Authoritative persisted runtime-readiness reconstruction and invalidation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import yaml

from .identity import PRODUCT_ID, portable_id_for_component
from .models import MarkerV1
from .readiness import ReadinessEvidence, RuntimeBinding
from .runtime_binding import RuntimeBindingPlan, RuntimeBindingReceipt, binding_fingerprint

_MAX_FILE = 1024 * 1024
_CANARY_FIELDS = {
    *RuntimeBindingReceipt.__dataclass_fields__,
    "config_readback_passed",
    "canary_status",
    "canary_reason_code",
    "canary_evidence_digest",
    "probe_started_at",
    "probe_finished_at",
    "fresh_until",
    "binding_fingerprint",
    "actual_model",
    "actual_provider",
    "api_calls",
    "tool_calls_observed",
    "fallback_used",
    "response_contract_passed",
    "nonce_contract_passed",
    "nonce_digest",
}


@dataclass(frozen=True, slots=True)
class ValidatedReadiness:
    """Opaque evidence token minted only after persisted-state validation."""

    evidence: tuple[ReadinessEvidence, ...]


def _read_regular(path: Path) -> bytes:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("authority file is unsafe")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            if total > _MAX_FILE:
                raise ValueError("authority file exceeds size limit")
            chunks.append(chunk)
        rebound = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or (
            rebound.st_dev,
            rebound.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise ValueError("authority file changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_profile_readiness(
    profile_path: Path, *, hermes_version: str, now: datetime
) -> ValidatedReadiness:
    """Rebuild authority from the current marker, config, Hermes version, and receipt."""
    try:
        marker_obj: object = json.loads(_read_regular(profile_path / "agentporter-profile.json"))
        config_bytes = _read_regular(profile_path / "config.yaml")
        config_obj: object = yaml.safe_load(config_bytes)
        receipt_obj: object = json.loads(
            _read_regular(profile_path / "local/agentporter/runtime-binding.json")
        )
        if (
            not isinstance(marker_obj, dict)
            or not isinstance(config_obj, dict)
            or not isinstance(receipt_obj, dict)
        ):
            raise ValueError("authority documents must be mappings")
        marker = MarkerV1.model_validate(marker_obj)
        if marker.product_id != PRODUCT_ID:
            raise ValueError("marker provenance is invalid")
        config = cast(dict[str, object], config_obj)
        receipt = cast(dict[str, object], receipt_obj)
        if set(receipt) != _CANARY_FIELDS:
            raise ValueError("runtime authority receipt schema is invalid")
        model_obj = config.get("model")
        if not isinstance(model_obj, dict):
            raise ValueError("current model config is invalid")
        model = cast(dict[str, object], model_obj)
        base = {key: receipt[key] for key in RuntimeBindingReceipt.__dataclass_fields__}
        parsed = RuntimeBindingReceipt.from_dict(base)
        current_model = model.get("default")
        current_provider = model.get("provider")
        current_endpoint = model.get("base_url")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (current_model, current_provider, current_endpoint)
        ):
            raise ValueError("current binding config is invalid")
        portable_id = portable_id_for_component(marker.component_id)
        current_config_digest = _digest(config_bytes)
        reconstructed = RuntimeBindingPlan.from_values(
            portable_id=portable_id,
            component_id=marker.component_id,
            current_profile_name=profile_path.name,
            expected_model=cast(str, current_model),
            provider_id=cast(str, current_provider),
            endpoint_value=cast(str, current_endpoint),
            credential_grant_kind=parsed.credential_grant_kind,
            credential_state=parsed.credential_state,
            hermes_version=hermes_version,
            config_digest=current_config_digest,
        )
        if (
            marker.component_id != parsed.component_id
            or profile_path.name != parsed.profile_name
            or current_model != parsed.model
            or current_provider != parsed.provider
            or reconstructed.endpoint_digest != parsed.endpoint_digest
            or current_config_digest != parsed.config_digest
            or hermes_version != parsed.hermes_version
            or receipt.get("binding_fingerprint") != binding_fingerprint(reconstructed)
            or receipt.get("config_readback_passed") is not True
            or receipt.get("canary_status") != "passed"
            or receipt.get("canary_reason_code") != "runtime-ready"
            or receipt.get("actual_model") != parsed.model
            or receipt.get("actual_provider") != parsed.provider
            or receipt.get("api_calls") != 1
            or receipt.get("tool_calls_observed") != 0
            or receipt.get("fallback_used") is not False
            or receipt.get("response_contract_passed") is not True
        ):
            raise ValueError("persisted runtime authority does not match current state")
        started = datetime.fromisoformat(cast(str, receipt["probe_started_at"]))
        finished = datetime.fromisoformat(cast(str, receipt["probe_finished_at"]))
        fresh_until = datetime.fromisoformat(cast(str, receipt["fresh_until"]))
        binding = RuntimeBinding(
            portable_id,
            parsed.component_id,
            parsed.profile_name,
            parsed.model,
            parsed.provider,
            "profile-config",
            binding_fingerprint(reconstructed),
            parsed.config_digest,
            parsed.endpoint_digest,
        )
        evidence = ReadinessEvidence(
            "runtime-ready",
            "runtime-ready",
            binding,
            parsed.hermes_version,
            started,
            finished,
            parsed.model,
            parsed.provider,
            1,
            True,
            0,
            fresh_until,
            False,
        )
        if not evidence.is_fresh(now):
            raise ValueError("persisted readiness is stale")
        return ValidatedReadiness((evidence,))
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ):
        return ValidatedReadiness(())


def invalidate_runtime_readiness(profile_path: Path) -> bool:
    """Public lifecycle producer API: remove only AgentPorter's profile-local receipt."""
    receipt = profile_path / "local/agentporter/runtime-binding.json"
    try:
        before = receipt.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            return False
        receipt.unlink()
        return True
    except FileNotFoundError:
        return False
