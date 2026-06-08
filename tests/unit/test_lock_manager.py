"""Unit tests for the advisory file lock manager."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from filerouter.adapters.file_lock_manager import FileLockManager
from filerouter.core.errors import LockError


def test_acquire_and_release(tmp_path: Path) -> None:
    """A lock can be acquired and is released on context exit."""
    mgr = FileLockManager(tmp_path / "locks")
    with mgr.acquire("KEY1"):
        assert (tmp_path / "locks" / "KEY1.lock").exists()
    # Released after the context: file removed.
    assert not (tmp_path / "locks" / "KEY1.lock").exists()


def test_second_acquire_is_rejected(tmp_path: Path) -> None:
    """A held lock cannot be acquired again (single writer)."""
    mgr = FileLockManager(tmp_path / "locks")
    with mgr.acquire("KEY2"):
        with pytest.raises(LockError):
            with mgr.acquire("KEY2"):
                pass


def test_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    """A lock whose heartbeat is older than the TTL is reclaimed."""
    # Very short TTL so the existing lock is immediately considered stale.
    mgr = FileLockManager(tmp_path / "locks", lock_ttl=0.0)
    lock_path = tmp_path / "locks" / "KEY3.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('{"heartbeat_at": 0}', encoding="utf-8")
    time.sleep(0.01)
    # Acquisition should reclaim the stale lock rather than fail.
    with mgr.acquire("KEY3"):
        assert lock_path.exists()


def test_heartbeat_updates_file(tmp_path: Path) -> None:
    """Calling heartbeat rewrites the lock with a fresh timestamp."""
    mgr = FileLockManager(tmp_path / "locks")
    with mgr.acquire("KEY4") as lock:
        before = (tmp_path / "locks" / "KEY4.lock").read_text()
        time.sleep(0.01)
        lock.heartbeat()
        after = (tmp_path / "locks" / "KEY4.lock").read_text()
        assert before != after
