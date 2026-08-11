from __future__ import annotations

import os

from agentporter.uninstall_application import (
    UninstallerStatus,
    minimal_process_environment,
    run_uninstaller,
)


def main() -> None:
    """Run the standalone AgentPorter uninstaller with no silent mode or subcommands."""
    result = run_uninstaller(minimal_process_environment(os.environ))
    if result.status not in (UninstallerStatus.ALREADY_ABSENT, UninstallerStatus.DELETED):
        raise SystemExit(f"AgentPorter uninstall {result.status}")


if __name__ == "__main__":
    main()
