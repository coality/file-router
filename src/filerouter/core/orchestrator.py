"""Orchestrator: the portable scan loop that drives both pipelines.

Detection is decoupled from processing. ``scan_once`` performs one full pass and
is directly callable from tests; ``run_forever`` adds the timing loop and clean
shutdown. Worker coordination is purely via filesystem locks, so the same code
works with threads, processes, or multiple hosts sharing storage.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from filerouter.core.context import Context
from filerouter.core.inbound import InboundProcessor
from filerouter.core.outbound import OutboundProcessor
from filerouter.core.pathing import identify_base_folder, relative_path


@dataclass
class ScanReport:
    """Counts produced by one scan pass (handy for tests and metrics)."""

    outbound_published: int = 0
    outbound_skipped: int = 0
    outbound_quarantined: int = 0
    inbound_delivered: int = 0
    inbound_skipped: int = 0
    inbound_quarantined: int = 0
    inbound_not_ready: int = 0
    details: list[str] = field(default_factory=list)


class Orchestrator:
    """Collects eligible files and dispatches them to the processors."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._outbound = OutboundProcessor(ctx)
        self._inbound = InboundProcessor(ctx)
        self._stop = False

    # -- collection ------------------------------------------------------

    def collect_outbound(self) -> list[Path]:
        """List eligible, stable source files across all base_folders."""
        files: list[Path] = []
        for base in self._ctx.config.base_folders:
            files.extend(self._eligible_in_base(Path(base.path)))
        return files

    def _eligible_in_base(self, base_path: Path) -> list[Path]:
        """List eligible files under one base_folder root."""
        out: list[Path] = []
        for path in self._ctx.store.iter_files(base_path, recursive=True):
            if self._is_eligible_source(path):
                out.append(path)
        return out

    def _is_eligible_source(self, path: Path) -> bool:
        """Return True if a source file passes inclusion/exclusion and is stable."""
        rel_file = self._relative_file(path)
        if rel_file is None:
            return False
        if not self._ctx.config.ruleset.is_eligible(rel_file):
            return False
        return self._is_stable(path)

    def _relative_file(self, path: Path) -> str | None:
        """Return the POSIX path (with filename) relative to its base_folder."""
        bases = list(self._ctx.config.base_folders)
        try:
            base = identify_base_folder(PurePath(str(path)), bases)
        except Exception:  # noqa: BLE001 - not under any base_folder
            return None
        rel_dir = relative_path(PurePath(str(path)), base)
        return f"{rel_dir}/{path.name}" if rel_dir else path.name

    def collect_inbound(self) -> list[Path]:
        """List payload files in exchange_in (metadata sidecars excluded)."""
        suffix = self._ctx.config.naming.meta_suffix
        return [
            p for p in self._ctx.store.iter_files(self._ctx.layout.exchange_in,
                                                  recursive=False)
            if not p.name.endswith(suffix)
        ]

    def _is_stable(self, path: Path) -> bool:
        """Stability gate shared by detection (avoid files still being written)."""
        return self._ctx.store.is_stable(
            path,
            self._ctx.config.scanning.stability_checks,
            self._ctx.config.scanning.stability_interval_seconds,
        )

    # -- dispatch --------------------------------------------------------

    def scan_once(self, parallel: bool = False) -> ScanReport:
        """Run one full pass over outbound then inbound work."""
        report = ScanReport()
        if self._role_does_outbound():
            self._dispatch_outbound(self.collect_outbound(), report, parallel)
        if self._role_does_inbound():
            self._dispatch_inbound(self.collect_inbound(), report, parallel)
        return report

    def _role_does_outbound(self) -> bool:
        """Return True if this instance handles outbound work."""
        return self._ctx.config.instance.role in ("outbound", "both")

    def _role_does_inbound(self) -> bool:
        """Return True if this instance handles inbound work."""
        return self._ctx.config.instance.role in ("inbound", "both")

    def _dispatch_outbound(self, files: list[Path], report: ScanReport,
                           parallel: bool) -> None:
        """Process outbound files, sequentially or across the worker pool."""
        for outcome in self._map(self._outbound.process, files, parallel):
            self._tally_outbound(outcome, report)

    def _dispatch_inbound(self, files: list[Path], report: ScanReport,
                          parallel: bool) -> None:
        """Process inbound payloads, sequentially or across the worker pool."""
        for outcome in self._map(self._inbound.process, files, parallel):
            self._tally_inbound(outcome, report)

    def _map(self, fn, items: list[Path], parallel: bool):
        """Apply ``fn`` to items, optionally in parallel via a thread pool."""
        if not parallel or len(items) <= 1:
            return [fn(item) for item in items]
        workers = max(1, self._ctx.config.instance.workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, items))

    @staticmethod
    def _tally_outbound(outcome, report: ScanReport) -> None:
        """Update the report counters for one outbound outcome."""
        if outcome.status == "published":
            report.outbound_published += 1
        elif outcome.status == "skipped_duplicate":
            report.outbound_skipped += 1
        else:
            report.outbound_quarantined += 1
            report.details.append(outcome.detail)

    @staticmethod
    def _tally_inbound(outcome, report: ScanReport) -> None:
        """Update the report counters for one inbound outcome."""
        mapping = {
            "delivered": "inbound_delivered",
            "skipped_duplicate": "inbound_skipped",
            "quarantined": "inbound_quarantined",
            "not_ready": "inbound_not_ready",
        }
        attr = mapping.get(outcome.status, "inbound_not_ready")
        setattr(report, attr, getattr(report, attr) + 1)

    # -- loop ------------------------------------------------------------

    def request_stop(self) -> None:
        """Ask the run loop to stop after the current pass (clean shutdown)."""
        self._stop = True

    def run_forever(self, sleep_fn) -> None:
        """Run scan passes until stop is requested, sleeping between passes.

        ``sleep_fn`` is injected so tests can drive the loop deterministically.
        """
        while not self._stop:
            self.scan_once(parallel=self._ctx.config.instance.workers > 1)
            if self._stop:
                break
            sleep_fn(self._ctx.config.scanning.interval_seconds)
