"""NoopCryptoProvider: passthrough used when no encryption rule applies.

When ``encrypted`` is false the payload IS the clear file. This provider lets
the pipeline treat both cases uniformly; it never encrypts and reports no
signature.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from filerouter.core.models import KeyInfo, VerificationResult


class NoopCryptoProvider:
    """A no-op CryptoProvider (copies bytes, no crypto)."""

    def encrypt(
        self,
        clear_path: Path,
        payload_path: Path,
        recipient_key_ids: list[str],
        signing_key_id: str | None,
    ) -> None:
        shutil.copyfile(clear_path, payload_path)

    def decrypt(self, payload_path: Path, clear_path: Path) -> VerificationResult:
        shutil.copyfile(payload_path, clear_path)
        return VerificationResult(valid=False, reason="no-encryption")

    def verify(self, payload_path: Path) -> VerificationResult:
        return VerificationResult(valid=False, reason="no-encryption")

    def list_keys(self) -> list[KeyInfo]:
        return []

    def self_test(self) -> None:
        return None
