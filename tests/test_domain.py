from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.manifest import load_manifest
from agentporter.models import (
    HermesProfileName,
    MarkerV1,
    PortableId,
    ResultStatus,
    WorkersManifest,
)


def test_repository_manifest_is_closed_and_typed() -> None:
    manifest = load_manifest(Path(__file__).parents[1] / "src/agentporter/resources/workers.yaml")

    assert isinstance(manifest, WorkersManifest)
    assert manifest.version == 1
    assert manifest.project == "agentporter"
    assert list(manifest.workers) == [
        "luna_worker",
        "codex_5_3_small_worker",
        "agentporter_orchestrator",
    ]
    assert manifest.workers["luna_worker"].tier == "bounded"
    assert manifest.workers["codex_5_3_small_worker"].provider is None


def test_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        WorkersManifest.model_validate(
            {
                "version": 1,
                "project": "agentporter",
                "workers": {
                    "luna_worker": {
                        "display_name": "Luna",
                        "tier": "bounded",
                        "model": "model",
                        "reasoning_effort": "max",
                        "description": "route",
                        "instructions": "stay scoped",
                        "unexpected": True,
                    }
                },
            }
        )


@pytest.mark.parametrize("value", ["worker", "a1_b", "a" * 64])
def test_portable_id_accepts_canonical_values(value: str) -> None:
    assert PortableId(value) == value


@pytest.mark.parametrize("value", ["Worker", "1worker", "worker-name", "a" * 65])
def test_portable_id_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        PortableId(value)


@pytest.mark.parametrize("value", ["worker", "worker-name", "worker_name", "a" * 64])
def test_hermes_profile_name_accepts_native_values(value: str) -> None:
    assert HermesProfileName(value) == value


@pytest.mark.parametrize("value", ["default", "Default", "worker.name", "_worker", "a" * 65])
def test_hermes_profile_name_rejects_reserved_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        HermesProfileName(value)


def test_protocol_registry_has_permanent_distinct_uuid_values() -> None:
    assert str(UUID(PRODUCT_ID)) == PRODUCT_ID
    assert set(COMPONENT_IDS) == {"luna_worker", "codex_5_3_small_worker"}
    assert len({PRODUCT_ID, *COMPONENT_IDS.values()}) == 3
    assert all(str(UUID(value)) == value for value in COMPONENT_IDS.values())


def test_marker_v1_is_exactly_five_fields_and_uses_canonical_uuids() -> None:
    marker = MarkerV1(
        schema_version=1,
        product_id=PRODUCT_ID,
        component_id=COMPONENT_IDS["luna_worker"],
        installation_id="12345678-1234-4abc-8def-1234567890ab",
        distribution_version="0.1.0",
    )

    assert set(marker.model_dump()) == {
        "schema_version",
        "product_id",
        "component_id",
        "installation_id",
        "distribution_version",
    }
    assert not any("name" in key for key in marker.model_dump())


@pytest.mark.parametrize(
    "change",
    [
        {"profile_name": "renamed"},
        {"schema_version": 2},
        {"installation_id": "{12345678-1234-4abc-8def-1234567890ab}"},
        {"product_id": "12345678-1234-4ABC-8def-1234567890ab"},
    ],
)
def test_marker_v1_rejects_extra_unsupported_or_noncanonical_values(
    change: dict[str, object],
) -> None:
    data: dict[str, object] = {
        "schema_version": 1,
        "product_id": PRODUCT_ID,
        "component_id": COMPONENT_IDS["luna_worker"],
        "installation_id": "12345678-1234-4abc-8def-1234567890ab",
        "distribution_version": "0.1.0",
    }
    data.update(change)
    with pytest.raises(ValidationError):
        MarkerV1.model_validate(data)


def test_result_status_model_is_closed() -> None:
    result = ResultStatus(status="ready", detail="static inputs validated")
    assert result.model_dump() == {"status": "ready", "detail": "static inputs validated"}
    with pytest.raises(ValidationError):
        ResultStatus.model_validate({"status": "invented"})
