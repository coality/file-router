"""Filesystem-based duplicate index (no database).

A marker file ``runtime/dedup/<hash[:2]>/<hash>`` is created atomically with
O_EXCL; first-arrival-wins. See docs/fr/09-error-handling.md §5.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class DedupIndex:
    """Atomic, first-arrival-wins duplicate marker index."""

    def __init__(self, dedup_dir: Path) -> None:
        self._dir = dedup_dir

    def _marker(self, clear_hash: str, alias: str, rel: str) -> Path:
        # Key on content hash + business location to catch the same file twice.
        key = f"{clear_hash}_{alias}_{rel}".replace("/", "_").replace("\\", "_")
        return self._dir / clear_hash[:2] / key

    def claim(self, clear_hash: str, alias: str, rel: str, technical_id: str) -> bool:
        """Try to claim a (hash, alias, rel) tuple.

        Returns True if this is the first claim (proceed), False if a duplicate
        marker already exists (skip).
        """
        marker = self._marker(clear_hash, alias, rel)
        marker.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"technical_id": technical_id, "claimed_at": time.time()}
        ).encode("utf-8")
        try:
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        return True

    def exists(self, clear_hash: str, alias: str, rel: str) -> bool:
        return self._marker(clear_hash, alias, rel).exists()
