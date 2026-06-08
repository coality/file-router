"""Per-file state machine helpers (see docs/fr/03-state-management.md §2).

The current state of a file is implicit in its location plus its audit trail.
This module centralizes the legal terminal/quarantine moves so processors do not
duplicate path logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from filerouter.ports.file_store import FileStore


class Quarantine:
    """Moves a failed item and its context into runtime/error/<technical_id>/."""

    def __init__(self, error_dir: Path, store: FileStore) -> None:
        self._dir = error_dir
        self._store = store

    def dir_for(self, technical_id: str) -> Path:
        return self._dir / technical_id

    def capture(
        self,
        technical_id: str,
        artifacts: list[Path],
        error: dict,
    ) -> Path:
        """Move ``artifacts`` into the quarantine dir and write error.json.

        Returns the quarantine directory. Never raises on a missing artifact.
        """
        qdir = self.dir_for(technical_id)
        self._store.makedirs(qdir)
        for art in artifacts:
            if self._store.exists(art):
                self._store.atomic_move(art, qdir / art.name)
        self._store.atomic_write_bytes(
            qdir / "error.json",
            json.dumps(error, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return qdir
