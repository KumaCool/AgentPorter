"""Installed AgentPorter uninstall console entry."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import __version__
from .self_cleanup import (
    CleanupPlanStatus,
    build_bootstrap_cleanup_plan,
    execute_cleanup_plan,
)
from .uninstall_application import (
    UninstallerStatus,
    minimal_process_environment,
    run_uninstaller,
)


def main() -> None:
    """Run the standalone AgentPorter uninstaller with no silent mode or subcommands."""
    cleanup = build_bootstrap_cleanup_plan(
        executable=Path(sys.executable), version=__version__, env=os.environ
    )
    result = run_uninstaller(minimal_process_environment(os.environ))
    if result.status not in (UninstallerStatus.ALREADY_ABSENT, UninstallerStatus.DELETED):
        raise SystemExit(f"AgentPorter uninstall {result.status}")
    if cleanup.status is CleanupPlanStatus.READY:
        execute_cleanup_plan(cleanup)
    elif cleanup.status is CleanupPlanStatus.UNSAFE:
        raise SystemExit("AgentPorter Profiles were removed but package cleanup was unsafe")
