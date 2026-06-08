"""Processing context: the dependency bundle shared by the processors.

Grouping the ports here keeps each processor method tiny (it just calls into
the context) and makes wiring explicit in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from filerouter.config.model import Config
from filerouter.core.audit import AuditLog
from filerouter.core.dedup import DedupIndex
from filerouter.core.layout import RuntimeLayout
from filerouter.core.state_machine import Quarantine
from filerouter.ports.clock import Clock
from filerouter.ports.crypto_provider import CryptoProvider
from filerouter.ports.file_store import FileStore
from filerouter.ports.id_generator import IdGenerator
from filerouter.ports.lock_manager import LockManager
from filerouter.ports.log_sink import LogSink


@dataclass(frozen=True)
class Context:
    """All collaborators a processor needs, wired once at startup."""

    config: Config
    layout: RuntimeLayout
    store: FileStore
    locks: LockManager
    crypto: CryptoProvider
    clock: Clock
    ids: IdGenerator
    log: LogSink
    audit: AuditLog
    dedup: DedupIndex
    quarantine: Quarantine
    host: str
