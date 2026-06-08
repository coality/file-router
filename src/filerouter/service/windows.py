"""Windows native service wrapper (pywin32), multi-instance capable.

Several FileRouter instances can run as native services on one machine. Each
instance gets a unique service name (``FileRouter_<instance>``) and reads its
config from a per-instance environment variable
(``FILEROUTER_CONFIG_<INSTANCE>``), falling back to ``FILEROUTER_CONFIG``.

The pure naming/resolution helpers are import-safe and unit-tested on any OS;
pywin32 is imported lazily so this module loads on non-Windows hosts.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# Default config env var used when no instance name is given (single-instance).
_DEFAULT_CONFIG_ENV = "FILEROUTER_CONFIG"
_BASE_NAME = "FileRouter"


# -- pure, testable helpers --------------------------------------------------

def service_name(instance: str | None) -> str:
    """Return the Windows service name for an instance (or the base name)."""
    return _BASE_NAME if not instance else f"{_BASE_NAME}_{instance}"


def service_display_name(instance: str | None) -> str:
    """Return a human-readable service display name."""
    return _BASE_NAME if not instance else f"{_BASE_NAME} ({instance})"


def config_env_var(instance: str | None) -> str:
    """Return the environment variable holding the config path for an instance."""
    if not instance:
        return _DEFAULT_CONFIG_ENV
    return f"{_DEFAULT_CONFIG_ENV}_{instance.upper()}"


def instance_from_service_name(name: str) -> str | None:
    """Extract the instance name from a service name (None for the base name)."""
    prefix = f"{_BASE_NAME}_"
    return name[len(prefix):] if name.startswith(prefix) else None


def resolve_config_path(name: str, environ: Mapping[str, str]) -> str:
    """Resolve the config path for a running service from its name and the env.

    Looks up the per-instance variable first, then the default. Raises a clear
    error if neither is set, so a misconfigured service fails fast and loud.
    """
    instance = instance_from_service_name(name)
    per_instance = config_env_var(instance)
    if per_instance in environ:
        return environ[per_instance]
    if _DEFAULT_CONFIG_ENV in environ:
        return environ[_DEFAULT_CONFIG_ENV]
    raise RuntimeError(
        f"no config path set: define {per_instance} (or {_DEFAULT_CONFIG_ENV})")


# -- pywin32 service glue (Windows only) -------------------------------------

def _load_service_base():
    """Import pywin32 pieces lazily; raises ImportError off Windows."""
    import servicemanager  # noqa: F401, PLC0415
    import win32event  # noqa: PLC0415
    import win32service  # noqa: PLC0415
    import win32serviceutil  # noqa: PLC0415

    return win32serviceutil, win32service, win32event


def build_service_class():
    """Build the Windows service class bound to pywin32 (Windows only).

    The running service derives its config path from its OWN service name, so a
    single class powers every instance.
    """
    win32serviceutil, win32service, win32event = _load_service_base()
    from filerouter.config.loader import load_config  # lazy
    from filerouter.service.runner import build_service  # lazy

    class FileRouterService(win32serviceutil.ServiceFramework):
        """SCM-managed FileRouter service (one per instance)."""

        _svc_name_ = _BASE_NAME
        _svc_display_name_ = _BASE_NAME

        def __init__(self, args) -> None:
            super().__init__(args)
            # args[0] is the actual service name SCM started us under.
            self._runtime_name = args[0] if args else _BASE_NAME
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._service = None

        def SvcStop(self) -> None:
            """Signal a clean stop to the running Service."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self._service is not None:
                self._service.stop()
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self) -> None:
            """Resolve this instance's config and run the portable Service loop."""
            config_path = resolve_config_path(self._runtime_name, os.environ)
            self._service = build_service(load_config(config_path))
            self._service.run()

    return FileRouterService


def _persist_config_env(instance: str | None, config_path: str) -> None:
    """Persist the per-instance config path as a machine environment variable.

    Uses ``setx /M`` so the SCM-started service sees it. Best-effort: a failure
    is reported but does not abort the install (the operator can set it by hand).
    """
    import subprocess  # noqa: PLC0415

    var = config_env_var(instance)
    try:
        subprocess.run(["setx", var, config_path, "/M"], check=True)
        print(f"set machine env {var}={config_path}")
    except Exception as exc:  # noqa: BLE001 - report, do not crash the install
        print(f"WARNING: could not set {var} automatically ({exc}); "
              f"set it manually: setx {var} \"{config_path}\" /M")


def main(argv: list[str] | None = None) -> int:
    """CLI for install/update/remove/start/stop with optional --instance/--config.

    Examples:
        python -m filerouter.service.windows install --instance siteA \
            --config C:\\SiteA\\config.yaml
        python -m filerouter.service.windows start --instance siteA
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="filerouter-windows-service")
    parser.add_argument("action",
                        choices=["install", "update", "remove", "start", "stop",
                                 "restart"])
    parser.add_argument("--instance", default=None,
                        help="instance name (enables multiple services on one host)")
    parser.add_argument("--config", default=None,
                        help="config path to persist for this instance on install")
    args = parser.parse_args(argv)

    name = service_name(args.instance)
    display = service_display_name(args.instance)

    # On install/update, remember which config this instance must load.
    if args.action in ("install", "update") and args.config:
        _persist_config_env(args.instance, args.config)

    import win32serviceutil  # noqa: PLC0415 - Windows only

    cls = build_service_class()
    win32serviceutil.HandleCommandLine(
        cls, serviceName=name, serviceDisplayName=display,
        argv=["filerouter-windows-service", args.action])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
