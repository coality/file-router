"""ULID / UUIDv4 identifier generators (stdlib only).

ULID = 48-bit millisecond timestamp + 80 random bits, Crockford base32,
26 characters, lexicographically sortable. No external dependency.
"""

from __future__ import annotations

import os
import time
import uuid

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


class UlidGenerator:
    """Generates sortable ULID identifiers."""

    def new_id(self) -> str:
        timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
        randomness = int.from_bytes(os.urandom(10), "big")  # 80 bits
        return _encode_base32(timestamp_ms, 10) + _encode_base32(randomness, 16)


class Uuid4Generator:
    """Generates UUIDv4 identifiers (hex, no dashes)."""

    def new_id(self) -> str:
        return uuid.uuid4().hex


def make_id_generator(strategy: str) -> UlidGenerator | Uuid4Generator:
    """Return the id generator for the configured ``strategy``."""
    if strategy == "uuid4":
        return Uuid4Generator()
    return UlidGenerator()
