"""Ports (interfaces) du cœur portable — voir docs/fr/01-architecture.md §3."""

from filerouter.ports.clock import Clock
from filerouter.ports.crypto_provider import CryptoProvider
from filerouter.ports.file_store import FileStore
from filerouter.ports.id_generator import IdGenerator
from filerouter.ports.lock_manager import Lock, LockManager
from filerouter.ports.log_sink import LogSink

__all__ = [
    "Clock",
    "CryptoProvider",
    "FileStore",
    "IdGenerator",
    "Lock",
    "LockManager",
    "LogSink",
]
