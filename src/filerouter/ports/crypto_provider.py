"""CryptoProvider port: OpenPGP encryption, decryption, signing, verification.

Backends: GnuPG (python-gnupg), PGPy, or a no-op passthrough. See
docs/fr/06-encryption.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from filerouter.core.models import KeyInfo, VerificationResult


class CryptoProvider(Protocol):
    """Abstracts the OpenPGP backend."""

    def encrypt(
        self,
        clear_path: Path,
        payload_path: Path,
        recipient_key_ids: list[str],
        signing_key_id: str | None,
    ) -> None:
        """Encrypt (and optionally sign) ``clear_path`` into ``payload_path``."""
        ...

    def decrypt(self, payload_path: Path, clear_path: Path) -> VerificationResult:
        """Decrypt ``payload_path`` into ``clear_path``.

        Returns the signature verification result (when the payload is signed).
        """
        ...

    def verify(self, payload_path: Path) -> VerificationResult:
        """Verify the signature of ``payload_path`` without decrypting."""
        ...

    def sign_detached(self, data: bytes) -> bytes:
        """Return a DETACHED OpenPGP signature over ``data`` (e.g. the metadata).

        Used to authenticate the metadata sidecar so its routing fields cannot be
        tampered with in transit. Raises ``CryptoError`` if signing is unavailable.
        """
        ...

    def verify_detached(self, data: bytes, signature: bytes) -> VerificationResult:
        """Verify a detached ``signature`` over ``data`` against the trusted key."""
        ...

    def list_keys(self) -> list[KeyInfo]:
        """List keys available in the keyring."""
        ...

    def self_test(self) -> None:
        """Encrypt/decrypt a sample to validate the backend and keyring.

        Raises ``CryptoError`` on failure.
        """
        ...
