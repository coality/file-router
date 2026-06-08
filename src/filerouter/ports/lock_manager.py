"""LockManager port: advisory, self-healing file locks.

See docs/fr/03-state-management.md §5.
"""

from __future__ import annotations

from typing import ContextManager, Protocol


class Lock(Protocol):
    """An acquired lock handle. Use as a context manager."""

    def heartbeat(self) -> None:
        """Refresh the lock's liveness timestamp."""
        ...

    def release(self) -> None:
        """Release the lock (best-effort)."""
        ...


class LockManager(Protocol):
    """Acquires advisory locks keyed by an opaque string."""

    def acquire(self, key: str) -> ContextManager[Lock]:
        """Acquire the lock for ``key``.

        Raises ``LockError`` if held by another live worker. A stale lock
        (heartbeat older than the TTL) is reclaimed.
        """
        ...
