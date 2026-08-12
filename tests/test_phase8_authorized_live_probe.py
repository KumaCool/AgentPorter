import pytest


def test_authorized_live_probe_candidate_requires_provider_only_sandbox() -> None:
    pytest.skip(
        "Hermes v0.20 probe capability is unsupported; environment self-declarations "
        "are not sandbox attestation and cannot turn this acceptance into a pass"
    )
