"""Clock port: wall/monotonic time and timestamp formatting."""

from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    """Abstracts time so the core can be tested with a frozen clock."""

    def now_utc_iso(self) -> str:
        """Return the current UTC time as an ISO-8601 string with milliseconds."""
        ...

    def now_compact(self, fmt: str) -> str:
        """Return the current UTC time formatted with ``fmt`` (strftime)."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic clock value in seconds (for timeouts/heartbeats)."""
        ...
