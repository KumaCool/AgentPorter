"""AgentPorter one-shot product entry."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from importlib.resources import as_file, files
from pathlib import Path

from .application import run_installer
from .transaction import InstallTransactionStatus
from .workflow import WorkflowStatus

__version__ = "0.1.4"

_ENTRY_ENV_ALLOWLIST = frozenset(
    {
        "HOME",
        "HERMES_HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONIOENCODING",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TMP",
        "TEMP",
        "TMPDIR",
    }
)


def _minimal_install_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Copy only non-credential process state required by Hermes CLI execution."""
    return {key: source[key] for key in _ENTRY_ENV_ALLOWLIST if source.get(key)}


def run_product_installer() -> None:
    """Run the one-shot installer against the packaged Worker manifest."""
    resource = files("agentporter.resources").joinpath("workers.yaml")
    with (
        as_file(resource) as manifest,
        tempfile.TemporaryDirectory(prefix="agentporter-run-") as temporary,
    ):
        result = run_installer(
            manifest,
            Path(temporary),
            _minimal_install_environment(os.environ),
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


__all__ = ["__version__", "main", "run_product_installer"]
