from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Never
from uuid import UUID

import pytest
import yaml

from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.planning import InstallPlan, cleanup_staging, plan_installation
from agentporter.workflow import (
    WorkflowStatus,
    confirm_preflight_plan,
    render_plan_text,
    request_for_plan,
)

REQUIRED = frozenset({"install", "delete", "describe", "list", "info"})
INSTALLATION_ID = UUID("12345678-1234-4abc-8def-1234567890ab")


def _manifest(tmp_path: Path, *, providers: bool = True) -> Path:
    source = Path(__file__).parents[1] / "workers.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if providers:
        for worker in data["workers"].values():
            worker["provider"] = "static-public-provider"
    path = tmp_path / "workers.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _plan(tmp_path: Path, *, providers: bool = True) -> InstallPlan:
    home = tmp_path / "private-hermes-home"
    detection = HermesDetection(
        executable=tmp_path / "private-bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=(),
    )
    return plan_installation(
        detection,
        _manifest(tmp_path, providers=providers),
        staging_parent=tmp_path / "private-staging-parent",
        installation_id_factory=lambda: INSTALLATION_ID,
    )


def _forbidden(*_args: object, **_kwargs: object) -> Never:
    pytest.fail("install/model/credential/write continuation was called")


def test_render_plan_text_is_complete_and_keeps_staging_private(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    text = render_plan_text(plan)

    assert f"Hermes executable: {plan.hermes.executable}" in text
    assert "Hermes version: 0.20.0" in text
    assert f"Hermes home: {plan.hermes.home}" in text
    assert f"Hermes profiles root: {plan.hermes.profiles_root}" in text
    for worker in plan.workers:
        for value in (
            worker.portable_id,
            worker.component_id,
            worker.profile_name,
            worker.display_name,
            worker.model,
            worker.provider,
            worker.reasoning_effort,
            worker.status,
            worker.reason,
        ):
            assert str(value) in text
    assert "Distribution owned: SOUL.md, config.yaml, agentporter-profile.json" in text
    assert "Copied data: none" in text
    assert "Modified data: none" in text
    assert "Model calls: false" in text
    assert "Runtime validated: false" in text
    assert "Compensation boundary: no-install-attempted" in text
    assert f"Collection status: {plan.status}" in text
    assert f"Collection reason: {plan.reason}" in text
    assert f"Fingerprint: {plan.fingerprint}" in text
    assert str(plan.staging_dir) not in text
    assert "private-staging-parent" not in text
    assert cleanup_staging(plan)


def test_request_for_plan_revalidates_complete_ready_plan(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    request = request_for_plan(plan)

    assert request is not None
    assert request.fingerprint == plan.fingerprint
    assert request.plan_text == render_plan_text(plan)
    tampered_worker = replace(plan.workers[0], model="tampered-model")
    tampered = replace(plan, workers=(tampered_worker, *plan.workers[1:]))
    assert request_for_plan(tampered) is None
    assert cleanup_staging(plan)


def test_request_for_plan_configuration_required_fails_closed_with_actionable_reason(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, providers=False)

    assert request_for_plan(plan) is None
    text = render_plan_text(plan)
    assert "configuration-required" in text
    assert "non-secret provider selection" in text
    assert "regenerate" in text


@pytest.mark.parametrize("answer", ["", "no"])
def test_confirm_preflight_cancel_cleans_staging_without_continuation(
    tmp_path: Path, answer: str
) -> None:
    plan = _plan(tmp_path)
    output = StringIO()

    outcome = confirm_preflight_plan(plan, input_fn=lambda _: answer, output=output)

    assert outcome.status is WorkflowStatus.CANCELLED
    assert outcome.cleanup_verified is True
    assert plan.staging_dir is not None and not plan.staging_dir.exists()
    assert output.getvalue().count(render_plan_text(plan)) == 1


def test_confirm_preflight_exact_phrase_confirms_once_and_only_returns_phase2_result(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        request = request_for_plan(plan)
        assert request is not None
        return request.phrase

    outcome = confirm_preflight_plan(plan, input_fn=read, output=StringIO())

    assert outcome.status is WorkflowStatus.CONFIRMED
    assert outcome.cleanup_verified is True
    assert outcome.reason == "plan confirmed; installation deferred to Phase 3"
    assert len(prompts) == 1
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_confirm_preflight_revalidates_after_prompt_before_continuation(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def tamper_after_display(_: str) -> str:
        object.__setattr__(plan, "reason", "tampered after display")
        return f"INSTALL AGENTPORTER {plan.fingerprint[:8]}"

    outcome = confirm_preflight_plan(plan, input_fn=tamper_after_display, output=StringIO())

    assert outcome.status is WorkflowStatus.REJECTED
    assert outcome.cleanup_verified is True
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_non_ready_plan_is_rejected_without_prompt(tmp_path: Path) -> None:
    plan = _plan(tmp_path, providers=False)
    calls = 0

    def forbidden_prompt(_: str) -> Never:
        nonlocal calls
        calls += 1
        return _forbidden()

    outcome = confirm_preflight_plan(plan, input_fn=forbidden_prompt, output=StringIO())

    assert outcome.status is WorkflowStatus.REJECTED
    assert calls == 0
    assert outcome.cleanup_verified is True


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
def test_input_termination_cancels_and_cleans(tmp_path: Path, error: BaseException) -> None:
    plan = _plan(tmp_path)

    def terminate(_: str) -> Never:
        raise error

    outcome = confirm_preflight_plan(plan, input_fn=terminate, output=StringIO())

    assert outcome.status is WorkflowStatus.CANCELLED
    assert outcome.cleanup_verified is True
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_unexpected_input_exception_cleans_then_propagates(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def fail(_: str) -> Never:
        raise RuntimeError("input failed")

    with pytest.raises(RuntimeError, match="input failed"):
        confirm_preflight_plan(plan, input_fn=fail, output=StringIO())
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_output_exception_cleans_then_propagates(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    class FailingOutput(StringIO):
        def write(self, value: str) -> Never:
            del value
            raise RuntimeError("output failed")

    with pytest.raises(RuntimeError, match="output failed"):
        confirm_preflight_plan(plan, input_fn=_forbidden, output=FailingOutput())
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_cleanup_failure_is_explicit_typed_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    outcome = confirm_preflight_plan(
        plan,
        input_fn=lambda _: "wrong",
        output=StringIO(),
        cleanup_fn=lambda _: False,
    )

    assert outcome.status is WorkflowStatus.CLEANUP_FAILED
    assert outcome.cleanup_verified is False
    assert outcome.reason == "staging cleanup could not be verified"
    assert plan.staging_dir is not None and plan.staging_dir.exists()
    assert cleanup_staging(plan)


def test_cleanup_exception_is_explicit_typed_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def fail_cleanup(_: InstallPlan) -> Never:
        raise OSError("cleanup detail")

    outcome = confirm_preflight_plan(
        plan,
        input_fn=lambda _: "wrong",
        output=StringIO(),
        cleanup_fn=fail_cleanup,
    )

    assert outcome.status is WorkflowStatus.CLEANUP_FAILED
    assert outcome.cleanup_verified is False
    assert "cleanup detail" not in outcome.reason
    assert cleanup_staging(plan)
