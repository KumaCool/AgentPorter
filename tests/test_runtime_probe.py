import multiprocessing
import stat
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentporter.runtime_binding import RuntimeBindingPlan, binding_fingerprint
from agentporter.runtime_probe import (
    ProbeFailure,
    ProbeObservation,
    ProbeResult,
    classify_probe_failure,
    negotiate_hermes_probe,
    probe_readiness_evidence,
    run_runtime_probe,
)


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure_classification(status: int) -> None:
    assert classify_probe_failure(ProbeFailure(http_status=status)) == "authentication-failed"


@pytest.mark.parametrize("status", [404])
def test_model_failure_classification(status: int) -> None:
    assert classify_probe_failure(ProbeFailure(http_status=status)) == "model-unsupported"


def test_rate_limit_classification() -> None:
    assert classify_probe_failure(ProbeFailure(http_status=429)) == "rate-limited"


@pytest.mark.parametrize("status", [502, 503])
def test_endpoint_failure_classification(status: int) -> None:
    assert classify_probe_failure(ProbeFailure(http_status=status)) == "endpoint-unavailable"


def test_timeout_classification() -> None:
    assert classify_probe_failure(ProbeFailure(timed_out=True)) == "probe-timeout"


def observation(nonce: str, **changes: object) -> ProbeObservation:
    values: dict[str, object] = {
        "output": f"AGENTPORTER_READY:{nonce}",
        "actual_model": "gpt-5.6-luna",
        "actual_provider": "custom",
        "api_calls": 1,
        "tool_calls": 0,
        "fallback_used": False,
    }
    values.update(changes)
    return ProbeObservation(**values)  # type: ignore[arg-type]


def test_success_requires_nonce_and_exact_runtime_route() -> None:
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: observation(nonce),
    )
    assert result.status == "runtime-ready"
    assert result.actual_model == "gpt-5.6-luna"
    assert result.actual_provider == "custom"
    assert result.api_calls == 1
    assert result.tool_calls == 0
    assert result.fallback_used is False
    assert result.response_contract_passed is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"actual_model": "gpt-5.6-luna", "actual_provider": "custom", "api_calls": 0},
        {
            "actual_model": "gpt-5.6-luna",
            "actual_provider": "custom",
            "api_calls": 1,
            "response_contract_passed": False,
        },
    ],
)
def test_runtime_ready_probe_result_cannot_be_forged(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ProbeResult("runtime-ready", **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [
        {"output": "wrong nonce"},
        {"api_calls": 0},
        {"api_calls": 2},
        {"tool_calls": 1},
    ],
)
def test_nonce_and_call_contract_failures_are_classified(change: dict[str, object]) -> None:
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: observation(nonce, **change),
    )
    assert result.status == "response-contract-failed"


@pytest.mark.parametrize(
    "change",
    [
        {"actual_model": "fallback-model"},
        {"actual_provider": "other-provider"},
        {"fallback_used": True},
    ],
)
def test_route_or_fallback_mismatch_is_unexpected_runtime_route(
    change: dict[str, object],
) -> None:
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: observation(nonce, **change),
    )
    assert result.status == "unexpected-runtime-route"


@pytest.mark.parametrize(
    "raised", [RuntimeError("cancelled"), KeyboardInterrupt(), BaseException("stop")]
)
def test_probe_cleans_temporary_evidence_for_all_base_exceptions(
    raised: BaseException, tmp_path: Path
) -> None:
    marker = tmp_path / "directory"

    def runner(_nonce: str, directory: Path) -> ProbeObservation:
        marker.write_text(str(directory), encoding="utf-8")
        (directory / "usage.json").write_text("private usage", encoding="utf-8")
        (directory / "stdout").write_text("private output", encoding="utf-8")
        (directory / "stderr").write_text("private error", encoding="utf-8")
        raise raised

    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=runner,
    )
    assert result.status == "response-contract-failed"
    assert not Path(marker.read_text(encoding="utf-8")).exists()


def test_timeout_result_also_cleans_temporary_evidence(tmp_path: Path) -> None:
    marker = tmp_path / "directory"

    def runner(_nonce: str, directory: Path) -> ProbeObservation:
        marker.write_text(str(directory), encoding="utf-8")
        (directory / "stdout").write_text("private output", encoding="utf-8")
        return ProbeObservation(timed_out=True)

    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=runner,
    )
    assert result.status == "probe-timeout"
    assert not Path(marker.read_text(encoding="utf-8")).exists()


def test_hanging_supported_runner_is_killed_by_hard_timeout(tmp_path: Path) -> None:
    marker = tmp_path / "runner-started"

    def runner(_nonce: str, _directory: Path) -> ProbeObservation:
        marker.write_text("started", encoding="utf-8")
        while True:
            time.sleep(1)

    started = time.monotonic()
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=runner,
        timeout_seconds=0.1,
    )
    assert result.status == "probe-timeout"
    assert time.monotonic() - started < 2
    assert marker.read_text(encoding="utf-8") == "started"


def test_default_timeout_is_finite_and_supported_probe_is_always_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float] = []

    def isolated(_runner: object, nonce: str, _directory: Path, timeout: float) -> ProbeObservation:
        observed.append(timeout)
        return observation(nonce)

    monkeypatch.setattr("agentporter.runtime_probe._isolated_observation", isolated)
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: observation(nonce),
    )
    assert result.status == "runtime-ready"
    assert observed == [30.0]


def test_child_base_exception_is_safe_eof_tolerant_and_leaves_no_process(
    capfd: pytest.CaptureFixture[str],
) -> None:
    before = {child.pid for child in multiprocessing.active_children()}

    def interrupt(_nonce: str, _directory: Path) -> ProbeObservation:
        raise KeyboardInterrupt("RAW_CHILD_SECRET")

    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=interrupt,
        timeout_seconds=0.1,
    )
    captured = capfd.readouterr()
    assert result.status == "response-contract-failed"
    assert "RAW_CHILD_SECRET" not in captured.err
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_public_hermes_v020_seam_is_unsupported_without_tool_call_proof() -> None:
    calls: list[object] = []
    capability = negotiate_hermes_probe(
        version="0.20.0",
        help_text="-z PROMPT --usage-file PATH -t TOOLSETS",
        command_runner=lambda argv: calls.append(argv),
    )
    assert capability.supported is False
    assert capability.status == "probe-unsupported"
    assert calls == []


def test_probe_directory_is_private_and_evidence_binds_version_config_and_ttl() -> None:
    binding = RuntimeBindingPlan.from_values(
        portable_id="luna_worker",
        component_id="component-luna",
        current_profile_name="luna",
        expected_model="gpt-5.6-luna",
        provider_id="custom",
        endpoint_value="https://provider.invalid/v1",
        credential_grant_kind="profile-auth",
        credential_state="operator-authorized",
        hermes_version="0.20.0",
        config_digest="config-digest",
    )
    started = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    def runner(nonce: str, directory: Path) -> ProbeObservation:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        return observation(nonce)

    item = probe_readiness_evidence(
        binding=binding,
        runner=runner,
        now=lambda: started,
        freshness=timedelta(minutes=5),
    )
    assert item.status == "runtime-ready"
    assert item.hermes_version == "0.20.0"
    assert item.binding.config_digest == "config-digest"
    assert item.binding.binding_fingerprint == binding_fingerprint(binding)
    assert item.fresh_until == started + timedelta(minutes=5)


def test_probe_result_carries_real_timing_and_nonce_contract_without_nonce() -> None:
    instants = iter(
        [
            datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            datetime(2026, 8, 13, 12, 0, 2, tzinfo=UTC),
        ]
    )
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: observation(nonce),
        now=lambda: next(instants),
        freshness=timedelta(minutes=5),
    )
    assert result.probe_started_at < result.probe_finished_at
    assert result.fresh_until == result.probe_finished_at + timedelta(minutes=5)
    assert result.nonce_contract_passed is True
    assert result.nonce_digest
    assert "AGENTPORTER_READY" not in repr(result)


def test_unsupported_capability_creates_zero_temporary_or_runner_calls() -> None:
    calls: list[str] = []
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: calls.append(nonce) or observation(nonce),
        supported=False,
    )
    assert result == ProbeResult("probe-unsupported")
    assert calls == []


def test_v020_usage_without_tool_or_fallback_telemetry_passes_live_call_only() -> None:
    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=lambda nonce, _directory: ProbeObservation(
            output=f"AGENTPORTER_READY:{nonce}",
            actual_model="gpt-5.6-luna",
            actual_provider="custom",
            api_calls=1,
            tool_calls=None,
            fallback_used=None,
        ),
    )
    assert result.status == "route-proof-incomplete"
    assert result.live_call_passed is True
