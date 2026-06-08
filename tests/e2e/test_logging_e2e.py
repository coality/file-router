"""E2E: verify that operational logs are written with correlated events.

Uses the real JsonlLogSink (not the quiet null sink) and asserts the functional
and security streams contain the expected, technical_id-correlated records.
"""

from __future__ import annotations

import json
from pathlib import Path

from filerouter.config.loader import load_config_dict
from filerouter.core.inbound import InboundProcessor
from filerouter.core.orchestrator import Orchestrator
from filerouter.service.runner import build_context
from tests.conftest import FrozenClock, write_file


def _ctx_with_logs(config_dict: dict):
    """Wire a context whose logs are actually written to disk (quiet=False)."""
    ctx = build_context(load_config_dict(config_dict), quiet=False)
    object.__setattr__(ctx, "clock", FrozenClock())
    object.__setattr__(ctx.audit, "_clock", ctx.clock)
    return ctx


def _logs_dir(ctx) -> Path:
    """Return the base directory where the JSON-Lines log streams are written."""
    return ctx.layout.runtime_root.parent / "logs"


def _read_stream(ctx, stream: str) -> list[dict]:
    """Read all records from one log stream (empty list if the file is absent)."""
    path = _logs_dir(ctx) / stream / f"{stream}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_functional_logs_record_routing(config_dict: dict, tmp_path: Path) -> None:
    """Outbound and inbound emit correlated functional log records."""
    ctx = _ctx_with_logs(config_dict)
    src = write_file(tmp_path / "business" / "sap_fr" / "a/b/c.csv", b"x;y\n1;2\n")

    orch = Orchestrator(ctx)
    orch.scan_once()
    for item in list(ctx.layout.exchange_out.iterdir()):
        item.replace(ctx.layout.exchange_in / item.name)
    orch.scan_once()

    functional = _read_stream(ctx, "functional")
    events = {r["event"] for r in functional}
    assert "ROUTED_OUT" in events
    assert "DELIVERED_IN" in events
    # Every record is correlated by technical_id.
    assert all("technical_id" in r for r in functional)
    assert src.exists()  # delivered back


def test_security_logs_record_quarantine(config_dict: dict, tmp_path: Path) -> None:
    """A tampered payload produces a security-stream error record."""
    ctx = _ctx_with_logs(config_dict)
    write_file(tmp_path / "business" / "sap_fr" / "f.csv", b"data\n")
    orch = Orchestrator(ctx)
    orch.scan_once()
    payload = next(p for p in ctx.layout.exchange_out.iterdir()
                   if not p.name.endswith(".meta.json"))
    meta = payload.with_name(payload.name + ".meta.json")
    dst = ctx.layout.exchange_in / payload.name
    payload.replace(dst)
    meta.replace(ctx.layout.exchange_in / meta.name)
    dst.write_bytes(b"TAMPERED")

    InboundProcessor(ctx).process(dst)

    security = _read_stream(ctx, "security")
    assert any(r["event"] == "INBOUND_ERROR" for r in security)
