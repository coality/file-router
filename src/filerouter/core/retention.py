"""Retention sweep: purge archive/audit/logs/dedup past their age (no database).

Deletion is per-file, idempotent and interruptible: a crash mid-sweep simply
resumes next cycle. Quarantine (error/) is never purged automatically. See
docs/11-archival-retention.md.
"""

from __future__ import annotations

import time
from pathlib import Path

from filerouter.core.context import Context

_SECONDS_PER_DAY = 86400.0


class RetentionSweeper:
    """Removes aged artifacts according to the configured retention windows."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def run(self) -> dict[str, int]:
        """Run every retention pass; return per-area deletion counts."""
        retention = self._ctx.config.retention
        counts = {
            "archive": self._sweep(self._ctx.layout.archive, retention.get("archive_days", 0)),
            "audit": self._sweep(self._ctx.layout.audit, retention.get("audit_days", 0)),
            "dedup": self._sweep(self._ctx.layout.dedup, retention.get("dedup_days", 0)),
        }
        self._ctx.log.log("admin", "INFO", "RETENTION_DONE", **counts)
        return counts

    def _sweep(self, root: Path, days: int) -> int:
        """Delete files under ``root`` older than ``days`` (0 disables the sweep)."""
        if days <= 0 or not root.exists():
            return 0
        cutoff = days * _SECONDS_PER_DAY
        deleted = 0
        for path in root.rglob("*"):
            if path.is_file() and self._age(path) >= cutoff:
                self._ctx.store.remove(path)
                deleted += 1
        return deleted

    def _age(self, path: Path) -> float:
        """Age of a file in seconds, based on its mtime."""
        try:
            return max(0.0, time.time() - self._ctx.store.mtime(path))
        except FileNotFoundError:
            return 0.0
