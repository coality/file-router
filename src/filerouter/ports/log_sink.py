"""LogSink port: structured JSON-Lines logging across four streams."""

from __future__ import annotations

from typing import Any, Protocol


class LogSink(Protocol):
    """Emits structured log records to a named stream.

    Streams: ``technical``, ``functional``, ``security``, ``admin``.
    """

    def log(
        self,
        stream: str,
        level: str,
        event: str,
        *,
        technical_id: str | None = None,
        **fields: Any,
    ) -> None:
        """Emit one structured record to ``stream``."""
        ...
