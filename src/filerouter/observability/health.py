"""Health check: a self-test summarizing service readiness.

Produces a small dict consumable by an external probe (and writable to
runtime/health.json). See docs/08-observability.md §5.
"""

from __future__ import annotations

from filerouter.core.context import Context
from filerouter.core.errors import CryptoError


def crypto_ok(ctx: Context) -> bool:
    """Return True if the crypto backend self-test passes."""
    try:
        ctx.crypto.self_test()
        return True
    except CryptoError:
        return False


def quarantine_count(ctx: Context) -> int:
    """Count items currently in quarantine (should trend to zero)."""
    error_dir = ctx.layout.error
    if not error_dir.exists():
        return 0
    return sum(1 for p in error_dir.iterdir() if p.is_dir())


def backlog_count(ctx: Context) -> int:
    """Count payloads currently waiting in exchange_in."""
    suffix = ctx.config.naming.meta_suffix
    return sum(
        1 for p in ctx.store.iter_files(ctx.layout.exchange_in, recursive=False)
        if not p.name.endswith(suffix)
    )


def health(ctx: Context) -> dict:
    """Assemble the health summary used by probes and the CLI."""
    return {
        "crypto_ok": crypto_ok(ctx),
        "quarantine": quarantine_count(ctx),
        "inbound_backlog": backlog_count(ctx),
        "host": ctx.host,
    }
