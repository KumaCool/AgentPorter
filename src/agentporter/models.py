from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

_PORTABLE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RESERVED_HERMES_PROFILE_NAMES = frozenset({"default"})


class PortableId(str):
    def __new__(cls, value: str) -> PortableId:
        if _PORTABLE_ID.fullmatch(value) is None:
            raise ValueError("invalid Portable ID")
        return str.__new__(cls, value)


class HermesProfileName(str):
    def __new__(cls, value: str) -> HermesProfileName:
        if _PROFILE_NAME.fullmatch(value) is None or value in RESERVED_HERMES_PROFILE_NAMES:
            raise ValueError("invalid or reserved Hermes Profile name")
        return str.__new__(cls, value)


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CanonicalUuid = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkerDefinition(ClosedModel):
    display_name: NonEmptyString
    tier: Literal["bounded", "mechanical"]
    model: NonEmptyString
    provider: NonEmptyString | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
    description: NonEmptyString
    instructions: NonEmptyString


class WorkersManifest(ClosedModel):
    version: Literal[1]
    project: Literal["agentporter"]
    workers: dict[str, WorkerDefinition]

    @field_validator("workers")
    @classmethod
    def validate_ids(cls, value: dict[str, WorkerDefinition]) -> dict[str, WorkerDefinition]:
        if not value:
            raise ValueError("at least one worker is required")
        for portable_id in value:
            PortableId(portable_id)
        return value


class MarkerV1(ClosedModel):
    schema_version: Literal[1]
    product_id: CanonicalUuid
    component_id: CanonicalUuid
    installation_id: CanonicalUuid
    distribution_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]

    @field_validator("product_id", "component_id", "installation_id")
    @classmethod
    def verify_uuid_round_trip(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("UUID is not canonical")
        return value


ResultCode = Literal[
    "ready",
    "configuration-required",
    "unsupported",
    "conflict",
    "invalid",
    "confirmed-created",
    "verified-compensable",
    "uncertain-remnant",
    "compensation-incomplete",
    "already-absent",
    "ambiguous",
    "cancelled",
    "marker-changed",
    "unsafe-path",
    "deleted",
    "delete-failed",
    "verification-failed",
    "partial-delete",
]


class ResultStatus(ClosedModel):
    status: ResultCode
    detail: NonEmptyString | None = None
