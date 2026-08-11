from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Never
from uuid import UUID

import pytest
import yaml

from agentporter import manifest as manifest_module
from agentporter import planning
from agentporter import render as render_module
from agentporter import security as security_module
from agentporter.hermes import HermesCapabilities, HermesDetection, ProfileEntry, ProfileEntryKind
from agentporter.planning import CleanupOutcome, InstallPlan, cleanup_staging, plan_installation
from agentporter.workflow import (
    WorkflowStatus,
    confirm_preflight_plan,
    preflight_and_confirm,
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


def _detection(
    tmp_path: Path, *, profile_entries: tuple[ProfileEntry, ...] = ()
) -> HermesDetection:
    home = tmp_path / "private-hermes-home"
    return HermesDetection(
        executable=tmp_path / "private-bin" / "hermes",
        version="0.20.0",
        hermes_home=home,
        profiles_root=home / "profiles",
        capabilities=HermesCapabilities(REQUIRED, frozenset()),
        profile_entries=profile_entries,
    )


def _plan(tmp_path: Path, *, providers: bool = True) -> InstallPlan:
    return plan_installation(
        _detection(tmp_path),
        _manifest(tmp_path, providers=providers),
        staging_parent=tmp_path / "private-staging-parent",
        installation_id_factory=lambda: INSTALLATION_ID,
    )


def _forbidden(*_args: object, **_kwargs: object) -> Never:
    pytest.fail("forbidden credential/model/Hermes-write boundary was called")


def _confirm(
    plan: InstallPlan,
    tmp_path: Path,
    *,
    answer: str = "no",
    continuation: object = _forbidden,
    output: StringIO | None = None,
    cleanup_fn: object = cleanup_staging,
):
    return confirm_preflight_plan(
        plan,
        current_detection_provider=lambda: _detection(tmp_path),
        continuation=continuation,  # type: ignore[arg-type]
        input_fn=lambda _: answer,
        output=output or StringIO(),
        cleanup_fn=cleanup_fn,  # type: ignore[arg-type]
    )


def test_render_plan_text_is_explicit_privacy_allowlist(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    private_description = "/home/private/manifest description with secret prose"
    unsafe_reason = "/tmp/private-staging/reason copied verbatim"
    worker = replace(plan.workers[0], description=private_description, reason=unsafe_reason)
    projected = replace(plan, workers=(worker, *plan.workers[1:]), reason=unsafe_reason)

    text = render_plan_text(projected)

    assert f"Hermes executable: {plan.hermes.executable}" in text
    assert f"Hermes home: {plan.hermes.home}" in text
    assert f"Hermes profiles root: {plan.hermes.profiles_root}" in text
    assert "Model: " in text and "Provider: static-public-provider" in text
    assert "Copied data: none" in text and "Model calls: false" in text
    assert private_description not in text
    assert unsafe_reason not in text
    assert str(plan.staging_dir) not in text
    assert "private-staging-parent" not in text
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_request_is_canonical_and_binds_artifact_seal(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    request = request_for_plan(plan)

    assert request is not None
    assert request.plan_text == render_plan_text(plan)
    assert request.fingerprint == plan.fingerprint
    assert request.phrase == f"INSTALL AGENTPORTER {plan.fingerprint[:8]}"
    assert plan.staging_dir is not None
    artifact = plan.staging_dir / plan.artifacts[0].relative_path
    artifact.write_bytes(artifact.read_bytes() + b"\n")
    assert request_for_plan(plan) is None
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_configuration_required_plan_is_installable_and_confirmable(tmp_path: Path) -> None:
    plan = _plan(tmp_path, providers=False)

    request = request_for_plan(plan)

    assert plan.installable is True
    assert request is not None
    assert "Run configuration remains required after installation" in request.plan_text
    assert "not selected" in request.plan_text
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


@pytest.mark.parametrize("answer", ["", "no"])
def test_cancel_cleans_staging_with_zero_continuation(tmp_path: Path, answer: str) -> None:
    plan = _plan(tmp_path)
    output = StringIO()

    outcome = _confirm(plan, tmp_path, answer=answer, output=output)

    assert outcome.status is WorkflowStatus.CANCELLED
    assert outcome.cleanup_verified
    assert output.getvalue().count(render_plan_text(plan)) == 1
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_exact_phrase_revalidates_then_continues_once_before_cleanup(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    continued: list[InstallPlan] = []

    def continuation(candidate: InstallPlan) -> None:
        assert candidate.staging_dir is not None and candidate.staging_dir.exists()
        continued.append(candidate)

    outcome = _confirm(
        plan,
        tmp_path,
        answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
        continuation=continuation,
    )

    assert outcome.status is WorkflowStatus.CONFIRMED
    assert outcome.cleanup_verified
    assert continued == [plan]
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_artifact_tamper_after_prompt_rejects_with_zero_continuation(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert plan.staging_dir is not None

    def tamper(_: str) -> str:
        artifact = plan.staging_dir / plan.artifacts[0].relative_path
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
        return f"INSTALL AGENTPORTER {plan.fingerprint[:8]}"

    outcome = confirm_preflight_plan(
        plan,
        current_detection_provider=lambda: _detection(tmp_path),
        continuation=_forbidden,
        input_fn=tamper,
        output=StringIO(),
    )

    assert outcome.status is WorkflowStatus.REJECTED
    assert outcome.cleanup_verified


def test_target_change_after_prompt_rejects_with_zero_continuation(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    detections = iter(
        (
            _detection(tmp_path),
            _detection(
                tmp_path,
                profile_entries=(
                    ProfileEntry(
                        plan.workers[0].profile_name,
                        _detection(tmp_path).profiles_root / plan.workers[0].profile_name,
                        ProfileEntryKind.PROFILE,
                    ),
                ),
            ),
        )
    )

    outcome = confirm_preflight_plan(
        plan,
        current_detection_provider=lambda: next(detections),
        continuation=_forbidden,
        input_fn=lambda _: f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
        output=StringIO(),
    )

    assert outcome.status is WorkflowStatus.REJECTED
    assert outcome.cleanup_verified


def test_continuation_baseexception_cleans_then_propagates_original(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def interrupt(_: InstallPlan) -> Never:
        raise KeyboardInterrupt("stop")

    with pytest.raises(KeyboardInterrupt, match="stop"):
        _confirm(
            plan,
            tmp_path,
            answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
            continuation=interrupt,
        )
    assert plan.staging_dir is not None and not plan.staging_dir.exists()


def test_pending_baseexception_is_not_masked_by_cleanup_failure(tmp_path: Path) -> None:
    plan = _plan(tmp_path)

    def interrupt(_: InstallPlan) -> Never:
        raise KeyboardInterrupt("stop")

    with pytest.raises(KeyboardInterrupt, match="stop") as raised:
        _confirm(
            plan,
            tmp_path,
            answer=f"INSTALL AGENTPORTER {plan.fingerprint[:8]}",
            continuation=interrupt,
            cleanup_fn=lambda _: CleanupOutcome("failed", "synthetic failure"),
        )
    assert any("cleanup" in note for note in raised.value.__notes__)
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


@pytest.mark.parametrize("status", ["refused", "failed"])
def test_cleanup_refused_or_failed_is_explicit_typed_failure(tmp_path: Path, status: str) -> None:
    plan = _plan(tmp_path)

    outcome = _confirm(
        plan,
        tmp_path,
        cleanup_fn=lambda _: CleanupOutcome(status, "private detail"),  # type: ignore[arg-type]
    )

    assert outcome.status is WorkflowStatus.CLEANUP_FAILED
    assert not outcome.cleanup_verified
    assert "private detail" not in outcome.reason
    assert cleanup_staging(plan).status in {"cleaned", "already-absent"}


def test_preflight_and_confirm_is_real_two_detection_composition(tmp_path: Path) -> None:
    calls: list[str] = []
    continued: list[InstallPlan] = []

    def detector() -> HermesDetection:
        calls.append("detect")
        return _detection(tmp_path)

    def continuation(plan: InstallPlan) -> None:
        calls.append("continue")
        continued.append(plan)

    def answer(_: str) -> str:
        calls.append("prompt")
        assert continued == []
        # The phrase is canonical and can be recovered only from the rendered request.
        fingerprint = output.getvalue().split("Plan fingerprint: ", 1)[1].splitlines()[0]
        return f"INSTALL AGENTPORTER {fingerprint[:8]}"

    output = StringIO()
    outcome = preflight_and_confirm(
        detector,
        _manifest(tmp_path),
        staging_parent=tmp_path / "staging",
        continuation=continuation,
        input_fn=answer,
        output=output,
        installation_id_factory=lambda: INSTALLATION_ID,
    )

    assert outcome.status is WorkflowStatus.CONFIRMED
    assert calls == ["detect", "prompt", "detect", "continue"]
    assert len(continued) == 1
    assert continued[0].staging_dir is not None and not continued[0].staging_dir.exists()


def test_real_composition_has_no_credential_model_or_hermes_write_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guard actual module symbols that the production composition could reach.
    monkeypatch.setattr(manifest_module, "credential_reader", _forbidden, raising=False)
    monkeypatch.setattr(manifest_module, "model_caller", _forbidden, raising=False)
    monkeypatch.setattr(render_module, "hermes_profile_installer", _forbidden, raising=False)
    monkeypatch.setattr(security_module, "credential_reader", _forbidden, raising=False)
    monkeypatch.setattr(security_module, "model_caller", _forbidden, raising=False)
    monkeypatch.setattr(planning, "hermes_profile_installer", _forbidden, raising=False)
    assert "credential" not in preflight_and_confirm.__annotations__
    assert "model" not in preflight_and_confirm.__annotations__
    outcome = preflight_and_confirm(
        lambda: _detection(tmp_path),
        _manifest(tmp_path),
        staging_parent=tmp_path / "staging",
        continuation=_forbidden,
        input_fn=lambda _: "cancel",
        output=StringIO(),
    )
    assert outcome.status is WorkflowStatus.CANCELLED
