"""Windows native service wrapper (pywin32).

Thin lifecycle adapter: SvcDoRun starts the portable Service, SvcStop sets the
cooperative shutdown flag. pywin32 is imported lazily so the module imports on
non-Windows hosts (where the class is simply unusable).
"""

from __future__ import annotations

import os

# Config path is read from an environment variable so the SCM-managed service
# does not need command-line arguments.
_CONFIG_ENV = "FILEROUTER_CONFIG"


def _load_service_base():
    """Import pywin32 pieces lazily and return the base classes.

    Raises ImportError on non-Windows hosts; callers handle that gracefully.
    """
    import servicemanager  # noqa: F401, PLC0415
    import win32event  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415

    return win32serviceutil, win32service, win32event


def build_service_class():
    """Build the Windows service class bound to pywin32 (Windows only)."""
    win32serviceutil, win32service, win32event = _load_service_base()
    from filerouter.config.loader import load_config  # lazy
    from filerouter.service.runner import build_service  # lazy

    class FileRouterService(win32serviceutil.ServiceFramework):
        """SCM-managed FileRouter service."""

        _svc_name_ = "FileRouterService"
        _svc_display_name_ = "FileRouter"

        def __init__(self, args) -> None:
            super().__init__(args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._service = None

        def SvcStop(self) -> None:
            """Signal a clean stop to the running Service."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self._service is not None:
                self._service.stop()
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self) -> None:
            """Start the portable Service loop."""
            config_path = os.environ[_CONFIG_ENV]
            self._service = build_service(load_config(config_path))
            self._service.run()

    return FileRouterService


def main() -> None:
    """Command-line dispatch for install/start/stop/remove (Windows only)."""
    import win32serviceutil  # noqa: PLC0415

    win32serviceutil.HandleCommandLine(build_service_class())
