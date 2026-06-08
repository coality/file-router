"""CLI commands. Each command is a small function returning an exit code.

Commands map to docs/fr/13-operations-guide.md §1: validate-config, health, trace,
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


def cmd_preview(args: argparse.Namespace) -> int:
    """Show what FileRouter watches and would process next (read-only, no moves).

    For every base_folder it applies the inclusion/exclusion rules and prints each
    business file as WATCHED or skipped (with the rule pattern responsible) — a fast
    way to confirm e.g. that an 'archive' directory is correctly ignored. It also
    lists the inbound exchange_in payloads awaiting delivery. Nothing is moved,
    hashed, encrypted or delivered.
    """
    from pathlib import Path, PurePath  # lazy

    from filerouter.core.pathing import relative_path  # lazy

    cfg = load_config(args.config)
    ctx = build_context(cfg, quiet=True)

    watched = skipped = 0
    print("OUTBOUND - business files (inclusion/exclusion applied):")
    for base in cfg.base_folders:
        root = Path(base.path)
        if not root.exists():
            print(f"  base_folder {base.alias}  ->  {base.path}   [MISSING DIRECTORY]")
            continue
        print(f"  base_folder {base.alias}  ->  {base.path}")
        for path in sorted(ctx.store.iter_files(root, recursive=True), key=str):
            rel_dir = relative_path(PurePath(str(path)), base)
            rel_file = f"{rel_dir}/{path.name}" if rel_dir else path.name
            eligible, reason = cfg.ruleset.eligibility(rel_file)
            if eligible:
                watched += 1
                print(f"    [WATCHED] {rel_file}")
            else:
                skipped += 1
                if not args.watched_only:
                    print(f"    [ skip  ] {rel_file}   ({reason})")

    suffix = cfg.naming.meta_suffix
    inbound = sorted(
        (p.name for p in ctx.store.iter_files(ctx.layout.exchange_in, recursive=False)
         if not p.name.endswith(suffix)))
    print("INBOUND - exchange_in payloads awaiting delivery:")
    for name in inbound:
        print(f"    {name}")

    print(f"\n{watched} watched (would be processed), {skipped} skipped "
          f"across {len(cfg.base_folders)} base_folder(s); "
          f"{len(inbound)} inbound payload(s).")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Print the human-readable transfer history (support-friendly journal).

    Shows one line per completed transfer: date, direction, alias, original name,
    technical name, flags (clear/encrypted/signed/compressed), SHA-256, paths and
    technical_id. Reads logs/transfers.log; use --limit to show only the last N.
    """
    cfg = load_config(args.config)
    ctx = build_context(cfg, quiet=True)
    lines = ctx.journal.read()
    if not lines:
        print("no transfers recorded yet")
        return 0
    shown = lines[-args.limit:] if args.limit and args.limit > 0 else lines
    for line in shown:
        print(line)
    print(f"\n({len(shown)} of {len(lines)} transfer line(s))")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run the service loop in the foreground (Ctrl+C to stop)."""
    service = build_service(load_config(args.config))
    service.run()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose the configuration and environment (alias of filerouter-doctor)."""
    from filerouter.cli.doctor import Doctor, ask_yes_no  # lazy import

    # --yes turns the asker into an always-yes asker (unattended repair).
    asker = (lambda _p: True) if getattr(args, "yes", False) else ask_yes_no
    return Doctor(args.config, asker=asker).run(apply_fixes=getattr(args, "fix", False))


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
    preview = _add(sub, "preview", cmd_preview)
    preview.add_argument("--watched-only", action="store_true",
                         help="only list files that ARE watched (hide skipped ones)")
    history = _add(sub, "history", cmd_history)
    history.add_argument("--limit", type=int, default=0,
                         help="show only the last N transfer lines (0 = all)")
    trace = _add(sub, "trace", cmd_trace)
    trace.add_argument("technical_id", help="technical_id to trace")
    doctor = _add(sub, "doctor", cmd_doctor)
    doctor.add_argument("--fix", action="store_true",
                        help="offer to fix safe problems")
    doctor.add_argument("--yes", action="store_true",
                        help="with --fix, apply every safe fix without asking")
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
