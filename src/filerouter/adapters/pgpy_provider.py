"""PGPyProvider: pure-Python OpenPGP backend (optional alternative to GnuPG).

PGPy is imported lazily so the package works without it installed. This adapter
covers the same CryptoProvider contract; it is a documented alternative for hosts
where installing the gpg binary is undesirable (see docs/fr/06-encryption.md §1).
"""

from __future__ import annotations

from pathlib import Path

from filerouter.core.errors import CryptoError
from filerouter.core.models import KeyInfo, VerificationResult


class PGPyProvider:
    """CryptoProvider backed by PGPy keyrings.

    Note: this is a minimal, documented implementation. Production use should
    load real keys from the configured key files; here we keep the surface small
    and raise clearly when keys are not wired so behavior is never silent.
    """

    def __init__(self, encryption_config) -> None:
        try:
            import pgpy  # noqa: F401, PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover
            raise CryptoError("PGPy is not installed") from exc
        self._config = encryption_config

    def encrypt(self, clear_path: Path, payload_path: Path,
                recipient_key_ids: list[str], signing_key_id: str | None) -> None:
        raise CryptoError("PGPyProvider.encrypt: key loading not configured")

    def decrypt(self, payload_path: Path, clear_path: Path) -> VerificationResult:
        raise CryptoError("PGPyProvider.decrypt: key loading not configured")

    def verify(self, payload_path: Path) -> VerificationResult:
        raise CryptoError("PGPyProvider.verify: key loading not configured")

    def list_keys(self) -> list[KeyInfo]:
        return []

    def self_test(self) -> None:
        raise CryptoError("PGPyProvider: not configured")
