"""FileLockManager: advisory file locks with heartbeat and stale reclaim.

See docs/fr/03-state-management.md §5.
"""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filerouter.core.errors import LockError


class _FileLock:
    """An acquired lock handle backed by a lock file."""

    def __init__(self, path: Path, payload: dict) -> None:
        self._path = path
        self._payload = payload

    def heartbeat(self) -> None:
        self._payload["heartbeat_at"] = time.time()
        tmp = self._path.with_name(self._path.name + ".hb")
        tmp.write_text(json.dumps(self._payload), encoding="utf-8")
        os.replace(tmp, self._path)

    def release(self) -> None:
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass


class FileLockManager:
    """Creates advisory locks under ``locks_dir`` using O_EXCL."""

    def __init__(self, locks_dir: Path, lock_ttl: float = 300.0) -> None:
        self._dir = locks_dir
        self._ttl = lock_ttl
        self._host = socket.gethostname()

    @contextmanager
    def acquire(self, key: str) -> Iterator[_FileLock]:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{key}.lock"
        payload = {
            "host": self._host,
            "pid": os.getpid(),
            "technical_id": key,
            "acquired_at": time.time(),
            "heartbeat_at": time.time(),
            "stage": "",
        }
        self._try_create(path, payload)
        lock = _FileLock(path, payload)
        try:
            yield lock
        finally:
            lock.release()

    def _try_create(self, path: Path, payload: dict) -> None:
        try:
            self._create_exclusive(path, payload)
            return
        except FileExistsError:
            pass
        # Lock exists: reclaim only if stale (heartbeat older than TTL).
        if self._is_stale(path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            try:
                self._create_exclusive(path, payload)
                return
            except FileExistsError:
                pass
        raise LockError(f"lock held: {path.name}")

    @staticmethod
    def _create_exclusive(path: Path, payload: dict) -> None:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, json.dumps(payload).encode("utf-8"))
        finally:
            os.close(fd)

    def _is_stale(self, path: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return True
        heartbeat = float(data.get("heartbeat_at", 0))
        return (time.time() - heartbeat) > self._ttl
