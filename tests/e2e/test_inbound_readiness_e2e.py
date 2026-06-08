"""E2E: inbound robustness when a file is still uploading or metadata is missing.

Covers the user requirement: a payload in exchange_in may arrive before its
metadata; we must wait (retry) and never deliver or lose data, then quarantine
only if the metadata never arrives within the grace period.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from filerouter.core.inbound import InboundProcessor
from filerouter.core.orchestrator import Orchestrator
from tests.conftest import build_complex_tree


def _publish_then_split(context, tmp_path: Path) -> tuple[Path, Path]:
    """Run outbound, then return one (payload, meta) pair sitting in exchange_in."""
    build_complex_tree(tmp_path)
    Orchestrator(context).scan_once()
    # Move exactly one pair into exchange_in.
    out = context.layout.exchange_out
    payloads = [p for p in out.iterdir() if not p.name.endswith(".meta.json")]
    payload = payloads[0]
    meta = payload.with_name(payload.name + ".meta.json")
    dst_payload = context.layout.exchange_in / payload.name
    dst_meta = context.layout.exchange_in / meta.name
    payload.replace(dst_payload)
    meta.replace(dst_meta)
    return dst_payload, dst_meta


def test_payload_without_metadata_waits(context, tmp_path: Path) -> None:
    """A payload whose metadata has not arrived yet is 'not_ready', not delivered."""
    payload, meta = _publish_then_split(context, tmp_path)
    meta.unlink()  # metadata not here yet (still 'in transit')

    outcome = InboundProcessor(context).process(payload)
    assert outcome.status == "not_ready"
    # The payload is untouched, still waiting in exchange_in (no data loss).
    assert payload.exists()


def test_payload_orphan_quarantined_after_grace(context, tmp_path: Path) -> None:
    """If metadata never arrives within the grace, the payload is quarantined."""
    payload, meta = _publish_then_split(context, tmp_path)
    meta.unlink()
    # Age the payload past the grace period by backdating its mtime.
    grace = context.config.scanning.pair_grace_period_seconds
    old = time.time() - grace - 10
    os.utime(payload, (old, old))

    outcome = InboundProcessor(context).process(payload)
    assert outcome.status == "quarantined"
    assert not payload.exists()  # moved into quarantine, not left dangling


def test_pair_completes_then_delivers(context, tmp_path: Path) -> None:
    """Once both files are present and stable, the pair is delivered."""
    _payload, _meta = _publish_then_split(context, tmp_path)
    # Both present from the start: should deliver on the next inbound run.
    report = Orchestrator(context).scan_once()
    assert report.inbound_delivered >= 1
