"""SystemClock: real wall/monotonic clock."""

from __future__ import annotations

import time
from datetime import datetime, timezone


class SystemClock:
    """Clock backed by the operating system clock."""

    def now_utc_iso(self) -> str:
        # Millisecond precision, trailing 'Z' for UTC.
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def now_compact(self, fmt: str) -> str:
        return datetime.now(timezone.utc).strftime(fmt)

    def monotonic(self) -> float:
        return time.monotonic()
