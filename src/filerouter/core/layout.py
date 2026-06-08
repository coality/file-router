"""Runtime directory layout (see docs/03-state-management.md §1).

Centralizes the technical directory tree so every component agrees on paths.
``runtime`` and the exchange directories should share one volume so that
publish operations are intra-volume atomic renames.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeLayout:
    """Resolved paths for the runtime/exchange directories."""

    runtime_root: Path
    exchange_out: Path
    exchange_in: Path

    @property
    def staging(self) -> Path:
        return self.runtime_root / "staging"

    @property
    def processing(self) -> Path:
        return self.runtime_root / "processing"

    @property
    def archive(self) -> Path:
        return self.runtime_root / "archive"

    @property
    def error(self) -> Path:
        return self.runtime_root / "error"

    @property
    def audit(self) -> Path:
        return self.runtime_root / "audit"

    @property
    def locks(self) -> Path:
        return self.runtime_root / "locks"

    @property
    def temp(self) -> Path:
        return self.runtime_root / "temp"

    @property
    def dedup(self) -> Path:
        return self.runtime_root / "dedup"

    def all_dirs(self) -> list[Path]:
        return [
            self.staging, self.processing, self.archive, self.error,
            self.audit, self.locks, self.temp, self.dedup,
            self.exchange_out, self.exchange_in,
        ]

    def ensure(self) -> None:
        """Create every runtime/exchange directory if missing (idempotent)."""
        for d in self.all_dirs():
            d.mkdir(parents=True, exist_ok=True)
