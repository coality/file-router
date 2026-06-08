"""E2E concurrency tests: no races, no double processing, no loss.

Two angles:
  1. A large batch processed by the worker pool: every file published exactly once.
  2. Many threads racing on the SAME source: exactly one wins (single-writer lock).
See docs/03-state-management.md §5.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filerouter.core.orchestrator import Orchestrator
from filerouter.core.outbound import OutboundProcessor
from tests.conftest import write_file


def test_batch_processed_exactly_once(context, tmp_path: Path) -> None:
    """A large batch is fully published with no duplicates and no quarantine."""
    count = 60
    for i in range(count):
        # Spread across base_folders and depths to stress path logic too.
        alias = ["sap_fr", "crm_de", "payment"][i % 3]
        write_file(tmp_path / "business" / alias / f"d{i % 7}/sub/f{i}.dat",
                   f"content-{i}".encode())

    report = Orchestrator(context).scan_once(parallel=True)
    assert report.outbound_published == count
    assert report.outbound_quarantined == 0

    # Exactly `count` flat pairs in exchange_out -> each file published once.
    out = context.layout.exchange_out
    payloads = [p for p in out.iterdir() if not p.name.endswith(".meta.json")]
    metas = [p for p in out.iterdir() if p.name.endswith(".meta.json")]
    assert len(payloads) == count
    assert len(metas) == count


def test_single_writer_on_same_source(context, tmp_path: Path) -> None:
    """Many threads racing on one source: exactly one publishes, no loss."""
    src = write_file(tmp_path / "business" / "payment" / "race/only.dat", b"only-one")

    processor = OutboundProcessor(context)

    def _attempt(_n: int):
        """Each thread tries to process the very same source path."""
        return processor.process(src)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(_attempt, range(8)))

    published = [o for o in outcomes if o.status == "published"]
    # The lock guarantees a single successful writer for one source.
    assert len(published) == 1
    # Exactly one payload pair exists; the source is consumed.
    out = context.layout.exchange_out
    payloads = [p for p in out.iterdir() if not p.name.endswith(".meta.json")]
    assert len(payloads) == 1
    assert not src.exists()
