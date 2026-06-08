"""In-process metrics counters/gauges (no network dependency).

A minimal registry that the orchestrator can feed and that can be exported to a
JSON file or a Prometheus textfile. See docs/08-observability.md §4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Metrics:
    """A tiny counter/gauge registry."""

    counters: dict[str, float] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)

    def inc(self, name: str, value: float = 1.0) -> None:
        """Increment a counter by ``value`` (created on first use)."""
        self.counters[name] = self.counters.get(name, 0.0) + value

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to an absolute value."""
        self.gauges[name] = value

    def to_dict(self) -> dict:
        """Return a serializable snapshot of all metrics."""
        return {"counters": dict(self.counters), "gauges": dict(self.gauges)}

    def write_json(self, path: Path) -> None:
        """Write the snapshot atomically to ``path`` as JSON."""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)
