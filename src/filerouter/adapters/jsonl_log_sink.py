"""JsonlLogSink: structured JSON-Lines logging to four stream files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from filerouter.adapters.system_clock import SystemClock

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class JsonlLogSink:
    """Writes one JSON object per line, one file per stream.

    A real deployment adds rotation/compression/retention; this adapter keeps
    the wire format and the per-stream level filtering.
    """

    def __init__(self, base_dir: Path, levels: dict[str, str] | None = None) -> None:
        self._base = base_dir
        self._levels = {k: _LEVELS.get(v.upper(), 20) for k, v in (levels or {}).items()}
        self._clock = SystemClock()

    def log(
        self,
        stream: str,
        level: str,
        event: str,
        *,
        technical_id: str | None = None,
        **fields: Any,
    ) -> None:
        threshold = self._levels.get(stream, _LEVELS["INFO"])
        if _LEVELS.get(level.upper(), 20) < threshold:
            return
        record: dict[str, Any] = {
            "ts": self._clock.now_utc_iso(),
            "level": level.upper(),
            "stream": stream,
            "event": event,
        }
        if technical_id is not None:
            record["technical_id"] = technical_id
        record.update(fields)
        path = self._base / stream / f"{stream}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


class NullLogSink:
    """A log sink that discards everything (useful for tests)."""

    def log(self, *args: Any, **kwargs: Any) -> None:
        return None
