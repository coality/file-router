"""FileStore port: atomic filesystem operations.

The adapter guarantees atomic publish (write-to-temp then atomic rename) and
handles cross-volume moves explicitly. See docs/fr/03-state-management.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Protocol


class FileStore(Protocol):
    """Filesystem operations used by the core."""

    def exists(self, path: Path) -> bool: ...

    def size(self, path: Path) -> int:
        """Return the file size in bytes."""
        ...

    def mtime(self, path: Path) -> float:
        """Return the file modification time (epoch seconds)."""
        ...

    def iter_files(self, root: Path, recursive: bool = True) -> Iterator[Path]:
        """Yield regular files under ``root``."""
        ...

    def is_stable(self, path: Path, checks: int, interval: float) -> bool:
        """Return True if size/mtime stay unchanged across ``checks`` polls.

        Prevents picking up a file still being written by a producer.
        """
        ...

    def atomic_move(self, src: Path, dst: Path) -> None:
        """Atomically move ``src`` to ``dst``.

        Intra-volume: a single ``os.replace``. Cross-volume: copy to a temp
        file on the destination volume, fsync, then atomic rename.
        """
        ...

    def atomic_write_bytes(self, dst: Path, data: bytes) -> None:
        """Write ``data`` to a temp file then atomically rename onto ``dst``."""
        ...

    def append_line(self, dst: Path, line: str) -> None:
        """Append a single text line to ``dst`` (creating it if needed)."""
        ...

    def read_bytes(self, path: Path) -> bytes: ...

    def read_text(self, path: Path) -> str: ...

    def makedirs(self, path: Path) -> None:
        """Create a directory and its parents if missing."""
        ...

    def remove(self, path: Path) -> None:
        """Remove a file (no error if absent)."""
        ...
