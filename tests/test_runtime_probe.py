from pathlib import Path

import pytest

from agentporter.runtime_probe import (
    ProbeFailure,
    ProbeObservation,
    classify_probe_failure,
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
def test_probe_cleans_temporary_evidence_for_all_base_exceptions(raised: BaseException) -> None:
    observed_directory: Path | None = None

    def runner(_nonce: str, directory: Path) -> ProbeObservation:
        nonlocal observed_directory
        observed_directory = directory
        (directory / "usage.json").write_text("private usage", encoding="utf-8")
        (directory / "stdout").write_text("private output", encoding="utf-8")
        (directory / "stderr").write_text("private error", encoding="utf-8")
        raise raised

    with pytest.raises(type(raised)):
        run_runtime_probe(
            expected_model="gpt-5.6-luna",
            expected_provider="custom",
            runner=runner,
        )
    assert observed_directory is not None
    assert not observed_directory.exists()


def test_timeout_result_also_cleans_temporary_evidence() -> None:
    observed_directory: Path | None = None

    def runner(_nonce: str, directory: Path) -> ProbeObservation:
        nonlocal observed_directory
        observed_directory = directory
        (directory / "stdout").write_text("private output", encoding="utf-8")
        return ProbeObservation(timed_out=True)

    result = run_runtime_probe(
        expected_model="gpt-5.6-luna",
        expected_provider="custom",
        runner=runner,
    )
    assert result.status == "probe-timeout"
    assert observed_directory is not None
    assert not observed_directory.exists()
