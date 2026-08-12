import os

import pytest

AUTHORIZED = os.environ.get("AGENTPORTER_AUTHORIZE_LIVE_PROBE") == "I_ACCEPT_ONE_CALL_PER_WORKER"
SANDBOXED = os.environ.get("AGENTPORTER_LIVE_SANDBOX") == "provider-only-egress"


@pytest.mark.skipif(not AUTHORIZED, reason="requires explicit live-call and budget authorization")
def test_authorized_live_probe_candidate_requires_provider_only_sandbox() -> None:
    if not SANDBOXED:
        pytest.fail("live authorization requires verified provider-only egress sandbox")
    pytest.skip("candidate only: live runner remains unsupported on Hermes v0.20")
