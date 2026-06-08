"""Startup reconciliation / crash recovery (see docs/03 §6, docs/16).

Because every transition is a single atomic rename and every step is idempotent,
any crash leaves the system in one of a few finite states. This module classifies
leftover artifacts and resolves them WITHOUT losing data:

  * temp/        -> partial writes with no consumer        -> delete
  * processing/  -> interrupted pipeline                   -> finalize or quarantine
  * locks/       -> abandoned locks past TTL               -> reclaim (delete)

Incomplete exchange pairs are handled by the inbound readiness logic during the
normal scan, so they are intentionally not touched here.
"""

from __future__ import annotations

import time
from pathlib import Path

from filerouter.core.context import Context


class Reconciler:
    """Resolves leftover runtime artifacts at startup and periodically."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def run(self) -> dict[str, int]:
        """Run all reconciliation passes; return per-pass counts for logging."""
        counts = {
            "temp_purged": self._purge_temp(),
            "locks_reclaimed": self._reclaim_locks(),
            "processing_resolved": self._resolve_processing(),
        }
        self._ctx.log.log("admin", "INFO", "RECONCILE_DONE", **counts)
        return counts

    # -- temp ------------------------------------------------------------

    def _purge_temp(self) -> int:
        """Delete stale scratch files; nothing in temp/ is ever published."""
        max_age = 600.0
        purged = 0
        for path in self._iter_files(self._ctx.layout.temp):
            if self._age(path) >= max_age:
                self._ctx.store.remove(path)
                purged += 1
        return purged

    # -- locks -----------------------------------------------------------

    def _reclaim_locks(self) -> int:
        """Delete lock files whose heartbeat is older than the TTL."""
        reclaimed = 0
        ttl = 300.0
        for path in self._iter_files(self._ctx.layout.locks):
            if self._age(path) >= ttl:
                self._ctx.store.remove(path)
                reclaimed += 1
        return reclaimed

    # -- processing ------------------------------------------------------

    def _resolve_processing(self) -> int:
        """Resolve each interrupted processing/<id> directory safely."""
        resolved = 0
        root = self._ctx.layout.processing
        if not root.exists():
            return 0
        for work in sorted(p for p in root.iterdir() if p.is_dir()):
            resolved += self._resolve_one(work)
        return resolved

    def _resolve_one(self, work: Path) -> int:
        """Finalize an already-published item, else quarantine for replay."""
        technical_id = work.name
        if self._ctx.audit.has_terminal_success(technical_id):
            # Publish already happened before the crash: just clean leftovers.
            self._safe_rmtree(work)
            self._ctx.log.log("admin", "INFO", "RECONCILE_FINALIZED",
                              technical_id=technical_id)
            return 1
        # Unknown progress: preserve everything in quarantine for manual replay.
        artifacts = [p for p in work.iterdir() if p.is_file()]
        error = {"step": "reconcile", "exception_type": "Interrupted",
                 "message": "processing interrupted by crash; preserved for replay"}
        qdir = self._ctx.quarantine.capture(technical_id, artifacts, error)
        self._ctx.audit.append(technical_id, "ERROR", host=self._ctx.host,
                               actor="Reconciler",
                               details=error | {"quarantine_path": str(qdir)})
        self._safe_rmtree(work)
        self._ctx.log.log("admin", "WARNING", "RECONCILE_QUARANTINED",
                          technical_id=technical_id)
        return 1

    # -- helpers ---------------------------------------------------------

    def _iter_files(self, root: Path) -> list[Path]:
        """List regular files directly under ``root`` (empty if missing)."""
        if not root.exists():
            return []
        return [p for p in root.iterdir() if p.is_file()]

    def _age(self, path: Path) -> float:
        """Age of a file in seconds, based on its mtime."""
        try:
            return max(0.0, time.time() - self._ctx.store.mtime(path))
        except FileNotFoundError:
            return 0.0

    def _safe_rmtree(self, directory: Path) -> None:
        """Remove a directory and any remaining files, ignoring errors."""
        for child in list(directory.iterdir()) if directory.exists() else []:
            self._ctx.store.remove(child)
        try:
            directory.rmdir()
        except OSError:
            pass
