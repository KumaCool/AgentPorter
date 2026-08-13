from datetime import UTC, datetime, timedelta

import pytest

from agentporter.delegation_contract import DelegationContract
from agentporter.dispatch_planning import (
    DispatchPlan,
    NotificationRoute,
    TaskSpec,
    WorkspaceBinding,
)
from agentporter.readiness import ReadinessEvidence, RuntimeBinding
from agentporter.runtime_authority import ValidatedReadiness

NOW = datetime(2026, 8, 13, tzinfo=UTC)
SHA = "7cc1dad4e49aecfeadf4eb033802a5a990794c69"


def evidence(*, component: str = "worker-a", profile: str = "worker-a", fresh=True):
    binding = RuntimeBinding(
        portable_id=component,
        component_id=component,
        current_profile_name=profile,
        expected_model="model-a",
        expected_provider="provider-a",
        provider_source_kind="profile-config",
        binding_fingerprint="binding-a",
        config_digest="config-a",
    )
    return ReadinessEvidence(
        status="runtime-ready",
        safe_reason_code="runtime-ready",
        binding=binding,
        hermes_version="0.20.0",
        probe_started_at=NOW - timedelta(seconds=2),
        probe_finished_at=NOW - timedelta(seconds=1),
        actual_model="model-a",
        actual_provider="provider-a",
        api_calls=1,
        response_contract_passed=True,
        tool_calls_observed=0,
        fresh_until=NOW + (timedelta(minutes=5) if fresh else timedelta(seconds=-1)),
    )


def validated(*items: ReadinessEvidence) -> ValidatedReadiness:
    return ValidatedReadiness(items)


def contract():
    return DelegationContract(
        goal="bounded task",
        reads=["src/agentporter/readiness.py"],
        writes=["src/agentporter/new.py"],
        forbidden=[".env"],
        operations=["write", "test"],
        constraints=["offline"],
        acceptance=["pytest tests/test_new.py"],
        expected=["green"],
        base_sha=SHA,
        test_file_names=["tests/test_new.py"],
        shared_owner="worker-a",
    )


def task(**changes):
    values = dict(
        local_id="child-a",
        title="child",
        body="contract body",
        assignee="worker-a",
        component_id="worker-a",
        profile="worker-a",
        model="model-a",
        provider="provider-a",
        config_digest="config-a",
        hermes_version="0.20.0",
        binding_fingerprint="binding-a",
        workspace=WorkspaceBinding("worktree", "/safe/worktree", "phase-e", SHA),
        parents=("root",),
        idempotency_key="phase-e-child-a",
        contract=contract(),
        subscribe=True,
    )
    values.update(changes)
    return TaskSpec(**values)


def route():
    return NotificationRoute(
        platform="telegram",
        chat_id="runtime-chat-secret",
        chat_type="group",
        thread_id="runtime-thread-secret",
        notifier_profile="default",
        delivery_metadata=(("reply_anchor", "runtime-anchor-secret"),),
        source="creator-session",
    )


def test_plan_is_immutable_blocked_and_binds_all_authorities():
    plan = DispatchPlan.create(
        board="agentporter",
        tenant="tenant-a",
        creator_session="creator-session-runtime",
        route=route(),
        tasks=(task(),),
        readiness=validated(evidence()),
        now=NOW,
        expected_base_sha=SHA,
        expected_board_revision="board-rev-1",
        structural_roots=("root",),
    )
    assert plan.tasks[0].initial_status == "blocked"
    assert plan.tasks[0].workspace.base_sha == SHA
    assert plan.route.source == "creator-session"
    assert len(plan.fingerprint) == 64
    with pytest.raises(AttributeError):
        plan.board = "other"  # type: ignore[misc]


def test_plan_rejects_unvalidated_in_memory_evidence():
    with pytest.raises(TypeError, match="validated readiness"):
        DispatchPlan.create(
            board="agentporter",
            tenant="tenant-a",
            creator_session="creator-session-runtime",
            route=route(),
            tasks=(task(),),
            readiness=(evidence(),),  # type: ignore[arg-type]
            now=NOW,
            expected_base_sha=SHA,
            expected_board_revision="board-rev-1",
            structural_roots=("root",),
        )


@pytest.mark.parametrize(
    "task_change,evidence_change,match",
    [
        ({"assignee": "unknown"}, {}, "assignee"),
        ({"profile": "other"}, {}, "profile"),
        ({"model": "other"}, {}, "model"),
        ({"provider": "other"}, {}, "provider"),
        ({"config_digest": "other"}, {}, "config"),
        ({"hermes_version": "0.21.0"}, {}, "Hermes"),
        ({"binding_fingerprint": "other"}, {}, "fingerprint"),
        ({}, {"fresh": False}, "fresh"),
    ],
)
def test_rejects_missing_stale_or_mismatched_assignee_evidence(task_change, evidence_change, match):
    with pytest.raises(ValueError, match=match):
        DispatchPlan.create(
            board="agentporter",
            tenant="tenant-a",
            creator_session="creator-session-runtime",
            route=route(),
            tasks=(task(**task_change),),
            readiness=validated(evidence(**evidence_change)),
            now=NOW,
            expected_base_sha=SHA,
            expected_board_revision="board-rev-1",
            structural_roots=("root",),
        )


def test_rejects_wrong_base_duplicate_keys_and_unbound_parent():
    with pytest.raises(ValueError, match="base SHA"):
        DispatchPlan.create(
            board="agentporter",
            tenant="t",
            creator_session="s",
            route=route(),
            tasks=(task(),),
            readiness=validated(evidence()),
            now=NOW,
            expected_base_sha="0" * 40,
            expected_board_revision="r",
            structural_roots=("root",),
        )
    with pytest.raises(ValueError, match="idempotency"):
        DispatchPlan.create(
            board="agentporter",
            tenant="t",
            creator_session="s",
            route=route(),
            tasks=(task(), task(local_id="other")),
            readiness=validated(evidence()),
            now=NOW,
            expected_base_sha=SHA,
            expected_board_revision="r",
            structural_roots=("root",),
        )
    with pytest.raises(ValueError, match="parent"):
        DispatchPlan.create(
            board="agentporter",
            tenant="t",
            creator_session="s",
            route=route(),
            tasks=(task(parents=("missing",)),),
            readiness=validated(evidence()),
            now=NOW,
            expected_base_sha=SHA,
            expected_board_revision="r",
        )
