"""E2E: duplicate skipping and crash-recovery reconciliation.

See docs/09-error-handling.md §5 and docs/16-disaster-recovery.md.
"""

from __future__ import annotations

from pathlib import Path

from filerouter.core.orchestrator import Orchestrator
from filerouter.core.reconciliation import Reconciler
from tests.conftest import write_file


def test_duplicate_content_is_skipped(context, tmp_path: Path) -> None:
    """Re-creating the same file at the same path is skipped on the second run."""
    rel = tmp_path / "business" / "sap_fr" / "x/y/z/data.csv"
    write_file(rel, b"same-content\n")

    orch = Orchestrator(context)
    first = orch.scan_once()
    assert first.outbound_published == 1

    # The source was archived; re-create identical content at the same location.
    write_file(rel, b"same-content\n")
    second = orch.scan_once()
    assert second.outbound_published == 0
    assert second.outbound_skipped == 1


def test_reconcile_quarantines_interrupted_processing(context, tmp_path: Path) -> None:
    """A leftover processing/<id> with no terminal success is quarantined."""
    work = context.layout.processing / "INTERRUPTED1"
    work.mkdir(parents=True)
    (work / "clear").write_bytes(b"half-done")

    counts = Reconciler(context).run()
    assert counts["processing_resolved"] == 1
    # Artifacts preserved in quarantine; processing dir cleaned up.
    assert not work.exists()
    assert (context.layout.error / "INTERRUPTED1").exists()


def test_reconcile_finalizes_published_item(context, tmp_path: Path) -> None:
    """A processing/<id> whose audit shows success is finalized, not quarantined."""
    technical_id = "PUBLISHED1"
    context.audit.append(technical_id, "MOVED_TO_EXCHANGE_OUT",
                         host="h", actor="t", details={})
    work = context.layout.processing / technical_id
    work.mkdir(parents=True)
    (work / "leftover").write_bytes(b"residual")

    Reconciler(context).run()
    # Finalized: directory removed, no quarantine entry created.
    assert not work.exists()
    assert not (context.layout.error / technical_id).exists()


def test_reconcile_purges_temp_orphans(context, tmp_path: Path) -> None:
    """Old scratch files in temp/ are purged (never published)."""
    import os
    import time

    orphan = context.layout.temp / "abc.tmp"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"scratch")
    old = time.time() - 10_000
    os.utime(orphan, (old, old))

    counts = Reconciler(context).run()
    assert counts["temp_purged"] == 1
    assert not orphan.exists()
