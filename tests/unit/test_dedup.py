"""Unit tests for the filesystem-based duplicate index."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filerouter.core.dedup import DedupIndex


def test_first_claim_wins(tmp_path: Path) -> None:
    """The first claim succeeds; the second on the same key is a duplicate."""
    idx = DedupIndex(tmp_path / "dedup")
    assert idx.claim("h" * 64, "PAYMENT", "a/b", "ID1") is True
    assert idx.claim("h" * 64, "PAYMENT", "a/b", "ID2") is False


def test_different_keys_both_claim(tmp_path: Path) -> None:
    """Different content/location tuples are independent."""
    idx = DedupIndex(tmp_path / "dedup")
    assert idx.claim("a" * 64, "PAYMENT", "x", "ID1") is True
    assert idx.claim("b" * 64, "PAYMENT", "x", "ID2") is True
    assert idx.claim("a" * 64, "SAP_FR", "x", "ID3") is True


def test_exists_reflects_claim(tmp_path: Path) -> None:
    """exists() returns True only after a successful claim."""
    idx = DedupIndex(tmp_path / "dedup")
    assert idx.exists("c" * 64, "PAYMENT", "p") is False
    idx.claim("c" * 64, "PAYMENT", "p", "ID1")
    assert idx.exists("c" * 64, "PAYMENT", "p") is True


def test_concurrent_claims_single_winner(tmp_path: Path) -> None:
    """Under concurrency, exactly one claim wins for the same key."""
    idx = DedupIndex(tmp_path / "dedup")

    def _claim(n: int) -> bool:
        """Each thread attempts the very same dedup key."""
        return idx.claim("d" * 64, "PAYMENT", "same", f"ID{n}")

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_claim, range(50)))
    assert results.count(True) == 1
