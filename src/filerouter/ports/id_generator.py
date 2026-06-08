"""IdGenerator port: produces unique technical identifiers."""

from __future__ import annotations

from typing import Protocol


class IdGenerator(Protocol):
    """Produces a globally unique ``technical_id``."""

    def new_id(self) -> str:
        """Return a fresh, unique identifier (ULID or UUIDv4)."""
        ...
