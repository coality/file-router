"""Linux service entry point (systemd, Type=notify-friendly).

Kept intentionally thin: it owns no business logic, only process lifecycle. The
actual work lives in the portable Service/Orchestrator.
"""

from __future__ import annotations

import signal

from filerouter.config.loader import load_config
from filerouter.service.runner import build_service


def run(config_path: str) -> None:
    """Run FileRouter under Linux, stopping cleanly on SIGTERM/SIGINT."""
    service = build_service(load_config(config_path))

    def _handle_stop(signum, _frame) -> None:
        """Request a clean stop when a termination signal arrives."""
        service.stop()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    service.run()
