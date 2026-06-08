"""Composition root: build a wired Context and a runnable Service.

This is the only place that knows which concrete adapter implements each port.
Each builder is a tiny function so the wiring reads top-to-bottom.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass

from filerouter.adapters.file_lock_manager import FileLockManager
from filerouter.adapters.jsonl_log_sink import JsonlLogSink, NullLogSink
from filerouter.adapters.local_file_store import LocalFileStore
from filerouter.adapters.noop_crypto import NoopCryptoProvider
from filerouter.adapters.system_clock import SystemClock
from filerouter.adapters.ulid_generator import make_id_generator
from filerouter.config.model import Config
from filerouter.core.audit import AuditLog
from filerouter.core.context import Context
from filerouter.core.dedup import DedupIndex
from filerouter.core.orchestrator import Orchestrator
from filerouter.core.reconciliation import Reconciler
from filerouter.core.state_machine import Quarantine
from filerouter.ports.crypto_provider import CryptoProvider


def _build_crypto(config: Config) -> CryptoProvider:
    """Select the crypto backend from config (gnupg | pgpy | noop).

    The passphrase is read from the environment, never from the YAML (security).
    """
    backend = config.encryption.backend
    if backend == "gnupg":
        from filerouter.adapters.gnupg_provider import GnuPGProvider  # lazy

        return GnuPGProvider(
            gnupg_home=config.encryption.gnupg_home or "",
            signing_key_id=config.encryption.signing_key_id,
            passphrase=os.environ.get("FILEROUTER_GPG_PASSPHRASE"),
            armored=config.encryption.armored,
        )
    if backend == "pgpy":
        from filerouter.adapters.pgpy_provider import PGPyProvider  # lazy

        return PGPyProvider(config.encryption)
    return NoopCryptoProvider()


def _build_log(config: Config, base_dir, quiet: bool):
    """Build the log sink (null sink when quiet, e.g. for tests)."""
    if quiet:
        return NullLogSink()
    levels = {name: spec.get("level", "INFO")
              for name, spec in config.logging.get("streams", {}).items()}
    return JsonlLogSink(base_dir=base_dir, levels=levels)


def build_context(config: Config, *, quiet: bool = False) -> Context:
    """Assemble the fully-wired Context from a typed Config."""
    layout = config.layout
    layout.ensure()  # create runtime/exchange directories if missing
    store = LocalFileStore()
    clock = SystemClock()
    log = _build_log(config, layout.runtime_root.parent / "logs", quiet)
    return Context(
        config=config,
        layout=layout,
        store=store,
        locks=FileLockManager(layout.locks,
                              lock_ttl=_lock_ttl(config)),
        crypto=_build_crypto(config),
        clock=clock,
        ids=make_id_generator(config.id_strategy),
        log=log,
        audit=AuditLog(layout.audit, store, clock),
        dedup=DedupIndex(layout.dedup),
        quarantine=Quarantine(layout.error, store),
        host=socket.gethostname(),
    )


def _lock_ttl(config: Config) -> float:
    """Return the lock TTL, defaulting when not set in config."""
    return 300.0


@dataclass
class Service:
    """A runnable service: reconcile once, then loop scanning."""

    ctx: Context

    def reconcile(self) -> dict[str, int]:
        """Run startup reconciliation (crash recovery)."""
        return Reconciler(self.ctx).run()

    def run(self) -> None:
        """Reconcile then run the scan loop until stopped."""
        self.reconcile()
        orchestrator = Orchestrator(self.ctx)
        self._orchestrator = orchestrator
        orchestrator.run_forever(time.sleep)

    def stop(self) -> None:
        """Request a clean stop of the running loop."""
        orch = getattr(self, "_orchestrator", None)
        if orch is not None:
            orch.request_stop()


def build_service(config: Config, *, quiet: bool = False) -> Service:
    """Build a ready-to-run Service from a typed Config."""
    return Service(ctx=build_context(config, quiet=quiet))
