"""Unit tests for the SHA-256 hashing engine."""

from __future__ import annotations

import hashlib
from pathlib import Path

from filerouter.core import hashing
from filerouter.core.models import FileHash


def test_sha256_bytes_matches_hashlib() -> None:
    """sha256_bytes must equal the stdlib digest."""
    data = b"hello world"
    assert hashing.sha256_bytes(data).value == hashlib.sha256(data).hexdigest()


def test_sha256_file_streams_correctly(tmp_path: Path) -> None:
    """Streaming a file in small chunks yields the correct digest."""
    payload = bytes(range(256)) * 5000  # ~1.25 MiB, multiple chunks
    f = tmp_path / "blob.bin"
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert hashing.sha256_file(f, chunk_size=4096).value == expected


def test_sha256_empty_file(tmp_path: Path) -> None:
    """An empty file hashes to the well-known SHA-256 of empty input."""
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert hashing.sha256_file(f).value == hashlib.sha256(b"").hexdigest()


def test_hashes_match_true_and_false() -> None:
    """Constant-time comparison returns True only for identical digests."""
    a = FileHash("SHA-256", "ab" * 32)
    b = FileHash("SHA-256", "ab" * 32)
    c = FileHash("SHA-256", "cd" * 32)
    assert hashing.hashes_match(a, b) is True
    assert hashing.hashes_match(a, c) is False


def test_hashes_match_rejects_algorithm_mismatch() -> None:
    """Different algorithms never match even with the same value."""
    a = FileHash("SHA-256", "ab" * 32)
    b = FileHash("SHA-1", "ab" * 32)
    assert hashing.hashes_match(a, b) is False
