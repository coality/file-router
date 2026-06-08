"""Per-file append-only audit log (JSON-Lines).

One file per technical_id under ``runtime/audit``. Events are appended with a
monotonic ``seq``; the full history is reconstructible by replaying the file in
seq order. See docs/fr/04-data-formats.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from filerouter.core.models import AUDIT_EVENTS, AuditEvent, Direction
from filerouter.ports.clock import Clock
from filerouter.ports.file_store import FileStore


class AuditLog:
    """Reads and appends audit events for a given runtime/audit directory."""

    def __init__(self, audit_dir: Path, store: FileStore, clock: Clock) -> None:
        self._dir = audit_dir
        self._store = store
        self._clock = clock

    def path_for(self, technical_id: str) -> Path:
        return self._dir / f"{technical_id}.audit.json"

    def append(
        self,
        technical_id: str,
        event: str,
        *,
        direction: Direction | None = None,
        host: str | None = None,
        actor: str | None = None,
        details: dict | None = None,
    ) -> AuditEvent:
        """Append one event and return it. ``seq`` is assigned automatically."""
        if event not in AUDIT_EVENTS:
            raise ValueError(f"unknown audit event: {event}")
        events = self.read(technical_id)
        seq = (events[-1].seq + 1) if events else 1
        evt = AuditEvent(
            technical_id=technical_id,
            seq=seq,
            event=event,
            ts=self._clock.now_utc_iso(),
            direction=direction,
            host=host,
            actor=actor,
            details=details or {},
        )
        line = json.dumps(evt.to_dict(), ensure_ascii=False)
        self._store.append_line(self.path_for(technical_id), line)
        return evt

    def read(self, technical_id: str) -> list[AuditEvent]:
        """Return the ordered list of events for a technical_id (empty if none)."""
        path = self.path_for(technical_id)
        if not self._store.exists(path):
            return []
        events: list[AuditEvent] = []
        for raw in self._store.read_text(path).splitlines():
            raw = raw.strip()
            if raw:
                events.append(AuditEvent.from_dict(json.loads(raw)))
        events.sort(key=lambda e: e.seq)
        return events

    def last_event(self, technical_id: str) -> AuditEvent | None:
        events = self.read(technical_id)
        return events[-1] if events else None

    def has_terminal_success(self, technical_id: str) -> bool:
        """Return True if the file already reached a successful terminal state.

        Used by reconciliation to decide whether a publish already happened
        (outbound OR inbound).
        """
        terminal = {"MOVED_TO_EXCHANGE_OUT", "ARCHIVED", "MOVED_TO_BUSINESS_FOLDER"}
        return any(e.event in terminal for e in self.read(technical_id))

    def has_event(self, technical_id: str, event: str) -> bool:
        """Return True if a specific event already exists for this technical_id."""
        return any(e.event == event for e in self.read(technical_id))
