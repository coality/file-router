"""CLI commands. Each command is a small function returning an exit code.

Commands map to docs/13-operations-guide.md §1: validate-config, health, trace,
status, list-quarantine, reconcile.
"""

from __future__ import annotations

import argparse
import json

from filerouter.config.loader import load_config
from filerouter.core.errors import ConfigError
from filerouter.observability.health import health
from filerouter.service.runner import build_context, build_service


def cmd_validate_config(args: argparse.Namespace) -> int:
    """Validate a YAML config file without starting the service."""
    try:
        load_config(args.config)
    except ConfigError as exc:
        print(f"INVALID: {exc}")
        return 2
    print("OK")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Print the health summary as JSON."""
    ctx = build_context(load_config(args.config), quiet=True)
    print(json.dumps(health(ctx), indent=2))
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """Reconstruct and print a file's audit history."""
    ctx = build_context(load_config(args.config), quiet=True)
    events = ctx.audit.read(args.technical_id)
    if not events:
        print(f"no audit history for {args.technical_id}")
        return 1
    for evt in events:
        print(json.dumps(evt.to_dict(), ensure_ascii=False))
    return 0


def cmd_list_quarantine(args: argparse.Namespace) -> int:
    """List technical_ids currently in quarantine."""
    ctx = build_context(load_config(args.config), quiet=True)
    error_dir = ctx.layout.error
    ids = [p.name for p in error_dir.iterdir() if p.is_dir()] if error_dir.exists() else []
    for tid in sorted(ids):
        print(tid)
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Force a reconciliation pass and print the counts."""
    service = build_service(load_config(args.config), quiet=True)
    print(json.dumps(service.reconcile(), indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run the service loop in the foreground (Ctrl+C to stop)."""
    service = build_service(load_config(args.config))
    service.run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser wiring every subcommand."""
    parser = argparse.ArgumentParser(prog="filerouter", description="FileRouter CLI")
    parser.add_argument("--config", required=True, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    _add(sub, "validate-config", cmd_validate_config)
    _add(sub, "health", cmd_health)
    _add(sub, "list-quarantine", cmd_list_quarantine)
    _add(sub, "reconcile", cmd_reconcile)
    _add(sub, "run", cmd_run)
    trace = _add(sub, "trace", cmd_trace)
    trace.add_argument("technical_id", help="technical_id to trace")
    return parser


def _add(sub, name: str, func) -> argparse.ArgumentParser:
    """Register one subcommand and attach its handler."""
    p = sub.add_parser(name)
    p.set_defaults(func=func)
    return p


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
