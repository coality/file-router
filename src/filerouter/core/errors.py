"""Error taxonomy (see docs/09-error-handling.md).

The transient/permanent distinction drives the retry strategy: only
``TransientError`` instances are retried.
"""

from __future__ import annotations


class FileRouterError(Exception):
    """Root of all FileRouter errors."""


class TransientError(FileRouterError):
    """Temporary IO error (third-party lock, share unavailable, disk full...).

    Eligible for retry with backoff.
    """


class IntegrityError(FileRouterError):
    """SHA-256 hash mismatch (payload or clear)."""


class CryptoError(FileRouterError):
    """Cryptographic failure (missing key, invalid signature, decryption failure)."""


class ConfigError(FileRouterError):
    """Invalid or inconsistent configuration."""


class DataError(FileRouterError):
    """Invalid data (missing/corrupt metadata, incomplete pair, name too long)."""


class LockError(FileRouterError):
    """Lock unavailable (held by another live worker)."""
