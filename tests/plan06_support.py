from __future__ import annotations

from agentporter.planning import RuntimeBindingSelection


def runtime_bindings() -> dict[str, RuntimeBindingSelection]:
    """Return a closed, explicit, non-secret two-Worker test binding."""
    return {
        "bounded_worker": RuntimeBindingSelection(
            "bounded-test-model", "test-provider", "https://bounded.invalid/v1"
        ),
        "mechanical_worker": RuntimeBindingSelection(
            "mechanical-test-model", "test-provider", "https://mechanical.invalid/v1"
        ),
    }
