"""GnuPGProvider: OpenPGP backend via python-gnupg.

Encrypts+signs on outbound, verifies+decrypts on inbound. See
docs/06-encryption.md. python-gnupg is imported lazily so the rest of the
package works without the gpg binary installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from filerouter.core.errors import CryptoError
from filerouter.core.models import KeyInfo, VerificationResult


class GnuPGProvider:
    """CryptoProvider backed by a GnuPG keyring."""

    def __init__(
        self,
        gnupg_home: str,
        signing_key_id: str | None = None,
        passphrase: str | None = None,
        armored: bool = False,
    ) -> None:
        try:
            import gnupg  # noqa: PLC0415 - lazy import (optional dependency)
        except ImportError as exc:  # pragma: no cover
            raise CryptoError("python-gnupg is not installed") from exc
        self._gpg = gnupg.GPG(gnupghome=gnupg_home)
        self._signing_key_id = signing_key_id
        self._passphrase = passphrase
        self._armored = armored

    def encrypt(
        self,
        clear_path: Path,
        payload_path: Path,
        recipient_key_ids: list[str],
        signing_key_id: str | None,
    ) -> None:
        if not recipient_key_ids:
            raise CryptoError("no recipient key for encryption")
        sign_with = signing_key_id or self._signing_key_id
        with open(clear_path, "rb") as fh:
            result = self._gpg.encrypt_file(
                fh,
                recipients=recipient_key_ids,
                sign=sign_with,
                passphrase=self._passphrase,
                armor=self._armored,
                output=str(payload_path),
                always_trust=True,
            )
        if not getattr(result, "ok", False):
            raise CryptoError(f"encryption failed: {getattr(result, 'status', '?')}")

    def decrypt(self, payload_path: Path, clear_path: Path) -> VerificationResult:
        with open(payload_path, "rb") as fh:
            result = self._gpg.decrypt_file(
                fh,
                passphrase=self._passphrase,
                output=str(clear_path),
                always_trust=True,
            )
        if not getattr(result, "ok", False):
            raise CryptoError(f"decryption failed: {getattr(result, 'status', '?')}")
        return self._verification_from(result)

    def verify(self, payload_path: Path) -> VerificationResult:
        with open(payload_path, "rb") as fh:
            result = self._gpg.verify_file(fh)
        return self._verification_from(result)

    @staticmethod
    def _verification_from(result: Any) -> VerificationResult:
        valid = bool(getattr(result, "valid", False))
        key_id = getattr(result, "key_id", None) or getattr(result, "fingerprint", None)
        return VerificationResult(
            valid=valid,
            signer_key_id=key_id,
            reason=None if valid else getattr(result, "status", "unsigned"),
        )

    def list_keys(self) -> list[KeyInfo]:
        keys: list[KeyInfo] = []
        for entry in self._gpg.list_keys():
            caps = entry.get("cap", "") or ""
            keys.append(
                KeyInfo(
                    key_id=entry.get("keyid", ""),
                    uids=tuple(entry.get("uids", ())),
                    can_encrypt="e" in caps.lower(),
                    can_sign="s" in caps.lower(),
                )
            )
        return keys

    def self_test(self) -> None:
        keys = self.list_keys()
        if not keys:
            raise CryptoError("empty keyring: self-test cannot run")
