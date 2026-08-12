from agentporter.runtime_probe import ProbeFailure, classify_probe_failure


def test_probe_failure_classification_is_safe_and_specific() -> None:
    assert classify_probe_failure(ProbeFailure(http_status=401)) == "authentication-failed"
    assert classify_probe_failure(ProbeFailure(http_status=404)) == "model-unsupported"
    assert classify_probe_failure(ProbeFailure(http_status=429)) == "rate-limited"
    assert classify_probe_failure(ProbeFailure(http_status=503)) == "endpoint-unavailable"
    assert classify_probe_failure(ProbeFailure(timed_out=True)) == "probe-timeout"
