from __future__ import annotations

import posixpath
import re
from typing import Annotated, Any, cast

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

_Path = Annotated[str, Field(min_length=1)]
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _normalize_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if not value or value.startswith("/"):
        raise ValueError("paths must be relative")
    depth = 0
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                raise ValueError("path parent escape is forbidden")
        else:
            depth += 1
    normalized = posixpath.normpath(value)
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("path parent escape is forbidden")
    return normalized


def _paths_intersect(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


class DelegationContract(BaseModel):
    """Closed, immutable-ish boundary for one delegated worker task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str = Field(min_length=1)
    reads: tuple[_Path, ...] = Field(validation_alias=AliasChoices("reads", "allowed_reads"))
    writes: tuple[_Path, ...] = Field(validation_alias=AliasChoices("writes", "allowed_writes"))
    forbidden: tuple[_Path, ...] = Field(
        validation_alias=AliasChoices("forbidden", "forbidden_paths")
    )
    operations: tuple[str, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(
        min_length=1, validation_alias=AliasChoices("acceptance", "acceptance_commands")
    )
    expected: tuple[str, ...] = Field(
        min_length=1, validation_alias=AliasChoices("expected", "expected_outputs")
    )
    base_sha: str = Field(min_length=40, max_length=40)
    test_file_names: tuple[_Path, ...] = Field(min_length=1)
    shared_owner: str = Field(
        min_length=1, validation_alias=AliasChoices("shared_owner", "shared_contract_owner")
    )

    @field_validator("goal", "operations", "constraints", "acceptance", "expected", "shared_owner")
    @classmethod
    def nonblank(cls, value: Any) -> Any:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("value must not be blank")
            return value.strip()
        return tuple(item.strip() if isinstance(item, str) else item for item in value)

    @field_validator("reads", "writes", "forbidden", "test_file_names")
    @classmethod
    def normalize_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_path(item) for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate paths are forbidden")
        return normalized

    @field_validator("base_sha")
    @classmethod
    def valid_sha(cls, value: str) -> str:
        if _SHA.fullmatch(value) is None:
            raise ValueError("base_sha must be a 40-character hexadecimal commit SHA")
        return value.lower()

    @property
    def allowed_writes(self) -> tuple[str, ...]:
        return self.writes


def validate_delegation_contracts(
    contracts: list[DelegationContract],
) -> tuple[DelegationContract, ...]:
    """Reject cross-task write overlap, duplicate tests, and conflicting owners."""
    seen_tests: dict[str, str] = {}
    for contract in contracts:
        for test_name in contract.test_file_names:
            previous = seen_tests.get(test_name)
            if previous is not None:
                raise ValidationError.from_exception_data(
                    DelegationContract.__name__,
                    cast(
                        Any,
                        [
                            {
                                "type": "value_error",
                                "loc": ("test_file_names",),
                                "msg": "duplicate test file name",
                                "input": test_name,
                                "ctx": {"error": ValueError("duplicate test file name")},
                            }
                        ],
                    ),
                )
            seen_tests[test_name] = contract.shared_owner
    for index, left in enumerate(contracts):
        for right in contracts[index + 1 :]:
            for left_path in left.writes:
                for right_path in right.writes:
                    if _paths_intersect(left_path, right_path):
                        raise ValidationError.from_exception_data(
                            DelegationContract.__name__,
                            cast(
                                Any,
                                [
                                    {
                                        "type": "value_error",
                                        "loc": ("writes",),
                                        "msg": "write paths intersect; owner conflict",
                                        "input": left_path,
                                        "ctx": {
                                            "error": ValueError(
                                                "write paths intersect; owner conflict"
                                            )
                                        },
                                    }
                                ],
                            ),
                        )
    return tuple(contracts)
