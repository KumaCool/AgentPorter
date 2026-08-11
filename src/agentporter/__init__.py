"""AgentPorter one-shot product entry."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .application import run_installer
from .transaction import InstallTransactionStatus
from .workflow import WorkflowStatus


def run_product_installer() -> None:
    """Run the one-shot installer against the repository-owned Worker manifest."""
    manifest = Path(__file__).resolve().parents[2] / "workers.yaml"
    with tempfile.TemporaryDirectory(prefix="agentporter-run-") as temporary:
        result = run_installer(
            manifest,
            Path(temporary),
            dict(os.environ),
        )
    if result.workflow.status is WorkflowStatus.CANCELLED:
        raise SystemExit("AgentPorter installation cancelled")
    if result.workflow.status is not WorkflowStatus.CONFIRMED or result.transaction is None:
        raise SystemExit(f"AgentPorter installation failed: {result.workflow.status}")
    if result.transaction.status is not InstallTransactionStatus.INSTALLED:
        raise SystemExit(f"AgentPorter installation failed: {result.transaction.status}")


def main() -> None:
    """Permanent one-shot product entry."""
    run_product_installer()


__all__ = ["main", "run_product_installer"]
