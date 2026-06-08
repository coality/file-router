"""E2E: copy/IO failures must quarantine the item and never lose the source.

A failing FileStore is injected to simulate disk errors at specific steps. The
invariants verified: nothing is published half-way, and the source content is
preserved in quarantine for replay.
"""

from __future__ import annotations

from pathlib import Path

from filerouter.core.inbound import InboundProcessor
from filerouter.core.orchestrator import Orchestrator
from filerouter.core.outbound import OutboundProcessor
from tests.conftest import write_file


class _FailingStore:
    """Wraps a real FileStore but raises OSError on one chosen method.

    ``predicate(*args)`` decides, per call, whether to fail. This lets a test
    simulate a disk error at a precise step (e.g. only when writing under a path).
    """

    def __init__(self, inner, method: str, predicate=lambda *a, **k: True) -> None:
        self._inner = inner
        self._method = method
        self._predicate = predicate

    def __getattr__(self, name):
        """Delegate everything to the wrapped store, faulting the chosen method."""
        attr = getattr(self._inner, name)
        if name != self._method:
            return attr

        def _wrapped(*args, **kwargs):
            if self._predicate(*args, **kwargs):
                raise OSError("simulated disk failure")
            return attr(*args, **kwargs)

        return _wrapped


def test_outbound_copy_failure_quarantines_and_preserves_source(
        context, tmp_path: Path) -> None:
    """A read failure while building the payload quarantines and keeps the source."""
    content = b"important-business-data\n"
    write_file(tmp_path / "business" / "sap_fr" / "x/y/z.csv", content)

    # Fail when the processor reads bytes to build the (noop) payload copy.
    object.__setattr__(context, "store",
                       _FailingStore(context.store, "read_bytes"))

    report = Orchestrator(context).scan_once()
    assert report.outbound_quarantined == 1
    assert report.outbound_published == 0

    # Nothing was published to exchange_out (no half-published pair).
    assert list(context.layout.exchange_out.iterdir()) == []

    # The source content is preserved in quarantine (no data loss).
    error_dirs = list(context.layout.error.iterdir())
    assert len(error_dirs) == 1
    preserved = (error_dirs[0] / "clear")
    assert preserved.exists()
    assert preserved.read_bytes() == content


def test_inbound_delivery_failure_quarantines(context, tmp_path: Path) -> None:
    """A move failure into the business tree quarantines without delivering."""
    # First publish a file normally.
    write_file(tmp_path / "business" / "sap_fr" / "deliver/me.csv", b"payload\n")
    orch = Orchestrator(context)
    orch.scan_once()
    payload = next(p for p in context.layout.exchange_out.iterdir()
                   if not p.name.endswith(".meta.json"))
    meta = payload.with_name(payload.name + ".meta.json")
    dst = context.layout.exchange_in / payload.name
    payload.replace(dst)
    meta.replace(context.layout.exchange_in / meta.name)

    # Fail the atomic move only when delivering into the business tree.
    def _fail_into_business(src, dest):
        return "business" in str(dest)

    object.__setattr__(context, "store",
                       _FailingStore(context.store, "atomic_move",
                                     _fail_into_business))

    outcome = InboundProcessor(context).process(dst)
    assert outcome.status == "quarantined"
    # The file was NOT delivered to the business tree.
    assert not (tmp_path / "business" / "sap_fr" / "deliver/me.csv").exists()
