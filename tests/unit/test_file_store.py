"""Unit tests for the LocalFileStore atomic operations."""

from __future__ import annotations

import os
import time
from pathlib import Path

from filerouter.adapters.local_file_store import LocalFileStore


def test_atomic_write_bytes_creates_file(tmp_path: Path) -> None:
    """atomic_write_bytes writes the content and leaves no temp file."""
    store = LocalFileStore()
    dst = tmp_path / "sub/dir/out.bin"
    store.atomic_write_bytes(dst, b"payload")
    assert dst.read_bytes() == b"payload"
    assert not (dst.with_name(dst.name + ".tmp")).exists()


def test_atomic_move_within_volume(tmp_path: Path) -> None:
    """atomic_move relocates a file and removes the source."""
    store = LocalFileStore()
    src = tmp_path / "a.txt"
    src.write_bytes(b"data")
    dst = tmp_path / "nested/b.txt"
    store.atomic_move(src, dst)
    assert dst.read_bytes() == b"data"
    assert not src.exists()


def test_append_line_appends(tmp_path: Path) -> None:
    """append_line adds newline-terminated records."""
    store = LocalFileStore()
    f = tmp_path / "log.jsonl"
    store.append_line(f, "line1")
    store.append_line(f, "line2")
    assert f.read_text().splitlines() == ["line1", "line2"]


def test_is_stable_true_for_quiet_file(tmp_path: Path) -> None:
    """A file that is not changing is reported stable."""
    store = LocalFileStore()
    f = tmp_path / "quiet.bin"
    f.write_bytes(b"x" * 100)
    assert store.is_stable(f, checks=2, interval=0.05) is True


def test_is_stable_false_while_growing(tmp_path: Path) -> None:
    """A file whose size changes between polls is reported unstable."""
    import threading

    store = LocalFileStore()
    f = tmp_path / "growing.bin"
    f.write_bytes(b"x" * 10)

    def _mutate() -> None:
        """Grow the file mid-check so the stability poll observes a change."""
        time.sleep(0.02)
        f.write_bytes(b"y" * 50000)

    worker = threading.Thread(target=_mutate)
    worker.start()
    try:
        # Multiple polls with a small interval guarantee the growth is seen.
        assert store.is_stable(f, checks=3, interval=0.05) is False
    finally:
        worker.join()


def test_remove_is_idempotent(tmp_path: Path) -> None:
    """remove() does not raise on a missing file."""
    store = LocalFileStore()
    store.remove(tmp_path / "nope")  # must not raise
