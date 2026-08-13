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

from .readiness import ReadinessEvidence, RuntimeBinding
from .runtime_binding import RuntimeBindingReceipt

_MAX_FILE = 1024 * 1024


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
        marker = cast(dict[str, object], marker_obj)
        config = cast(dict[str, object], config_obj)
        receipt = cast(dict[str, object], receipt_obj)
        model_obj = config.get("model")
        if not isinstance(model_obj, dict):
            raise ValueError("current model config is invalid")
        model = cast(dict[str, object], model_obj)
        base = {key: receipt[key] for key in RuntimeBindingReceipt.__dataclass_fields__}
        parsed = RuntimeBindingReceipt.from_dict(base)
        if (
            marker.get("component_id") != parsed.component_id
            or profile_path.name != parsed.profile_name
            or model.get("default") != parsed.model
            or model.get("provider") != parsed.provider
            or _digest(config_bytes) != parsed.config_digest
            or hermes_version != parsed.hermes_version
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
            parsed.profile_name,
            parsed.component_id,
            parsed.profile_name,
            parsed.model,
            parsed.provider,
            "profile-config",
            cast(str, receipt["binding_fingerprint"]),
            parsed.config_digest,
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
