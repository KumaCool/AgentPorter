import pytest
from pydantic import ValidationError

from agentporter.delegation_contract import DelegationContract, validate_delegation_contracts


def contract(**overrides):
    data = {
        "goal": "Implement the bounded feature",
        "reads": ["src/agentporter/models.py"],
        "writes": ["src/agentporter/delegation_contract.py", "tests/test_delegation_contract.py"],
        "forbidden": ["docs/", "src/agentporter/models.py"],
        "operations": ["write code", "run focused tests"],
        "constraints": ["no network"],
        "acceptance": ["pytest tests/test_delegation_contract.py"],
        "expected": ["contract validates"],
        "base_sha": "846a82d" + "0" * 33,
        "test_file_names": ["tests/test_delegation_contract.py"],
        "shared_owner": "main-agent",
    }
    data.update(overrides)
    return data


def test_contract_is_closed_and_normalizes_allowed_writes():
    model = DelegationContract(
        **contract(
            writes=[
                "src/agentporter/./delegation_contract.py",
                "tests/../tests/test_delegation_contract.py",
            ]
        )
    )
    assert model.writes == (
        "src/agentporter/delegation_contract.py",
        "tests/test_delegation_contract.py",
    )
    with pytest.raises(ValidationError):
        DelegationContract(**contract(unexpected="nope"))


def test_rejects_parent_escape_and_intersecting_writes():
    with pytest.raises(ValidationError, match="parent|escape"):
        DelegationContract(**contract(writes=["../../../secrets.txt"]))
    with pytest.raises(ValidationError, match="intersect"):
        validate_delegation_contracts(
            [
                DelegationContract(
                    **contract(writes=["src/agentporter"], test_file_names=["tests/test_one.py"])
                ),
                DelegationContract(
                    **contract(
                        shared_owner="other",
                        writes=["src/agentporter/delegation_contract.py"],
                        test_file_names=["tests/test_two.py"],
                    )
                ),
            ]
        )


def test_shared_documents_and_generated_files_have_one_owner():
    first = DelegationContract(
        **contract(
            writes=["docs/plan/shared.md"],
            shared_owner="owner-a",
            test_file_names=["tests/test_a.py"],
        )
    )
    second = DelegationContract(
        **contract(
            writes=["docs/plan/shared.md"],
            shared_owner="owner-b",
            test_file_names=["tests/test_b.py"],
        )
    )
    with pytest.raises(ValidationError, match="owner"):
        validate_delegation_contracts([first, second])


def test_rejects_duplicate_test_file_names_and_bad_base_sha():
    with pytest.raises(ValidationError, match="test"):
        validate_delegation_contracts(
            [
                DelegationContract(
                    **contract(shared_owner="a", test_file_names=["tests/test_same.py"])
                ),
                DelegationContract(
                    **contract(
                        shared_owner="b",
                        writes=["src/other.py"],
                        test_file_names=["tests/test_same.py"],
                    )
                ),
            ]
        )
    with pytest.raises(ValidationError, match="base_sha"):
        DelegationContract(**contract(base_sha="not-a-commit"))
