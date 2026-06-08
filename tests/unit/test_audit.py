"""Unit tests for the append-only audit log."""

from __future__ import annotations

from pathlib import Path

import pytest

from filerouter.adapters.local_file_store import LocalFileStore
from filerouter.core.audit import AuditLog
from filerouter.core.models import Direction


class _Clock:
    """Minimal clock producing ordered ISO timestamps."""

    def __init__(self) -> None:
        self._n = 0

    def now_utc_iso(self) -> str:
        self._n += 1
        return f"2026-06-08T12:00:{self._n:02d}.000Z"

    def now_compact(self, fmt: str) -> str:
        return "20260608T120000"

    def monotonic(self) -> float:
        return 0.0


def _log(tmp_path: Path) -> AuditLog:
    """Build an AuditLog on a temp directory."""
    return AuditLog(tmp_path / "audit", LocalFileStore(), _Clock())


def test_append_assigns_monotonic_seq(tmp_path: Path) -> None:
    """Successive events get increasing seq numbers."""
    log = _log(tmp_path)
    log.append("ID1", "DETECTED", direction=Direction.OUT)
    log.append("ID1", "HASH_COMPUTED")
    events = log.read("ID1")
    assert [e.seq for e in events] == [1, 2]
    assert [e.event for e in events] == ["DETECTED", "HASH_COMPUTED"]


def test_unknown_event_rejected(tmp_path: Path) -> None:
    """Appending an event outside the vocabulary raises."""
    log = _log(tmp_path)
    with pytest.raises(ValueError):
        log.append("ID1", "NOT_A_REAL_EVENT")


def test_history_reconstructible_in_order(tmp_path: Path) -> None:
    """The full history is returned in seq order."""
    log = _log(tmp_path)
    for evt in ["DETECTED", "HASH_COMPUTED", "MOVED_TO_EXCHANGE_OUT", "ARCHIVED"]:
        log.append("ID2", evt)
    assert [e.event for e in log.read("ID2")][-1] == "ARCHIVED"


def test_has_event_and_terminal(tmp_path: Path) -> None:
    """has_event and has_terminal_success report correctly."""
    log = _log(tmp_path)
    log.append("ID3", "DETECTED")
    assert log.has_event("ID3", "DETECTED") is True
    assert log.has_event("ID3", "ARCHIVED") is False
    assert log.has_terminal_success("ID3") is False
    log.append("ID3", "MOVED_TO_BUSINESS_FOLDER")
    assert log.has_terminal_success("ID3") is True


def test_empty_history(tmp_path: Path) -> None:
    """Reading an unknown id returns an empty list, not an error."""
    assert _log(tmp_path).read("UNKNOWN") == []
