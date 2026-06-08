"""PGPyProvider: pure-Python OpenPGP backend using on-disk key FILES.

Configuration (paths only — no key material ever lives in the YAML):
  * ``encryption.private_key_file`` — signs outbound, decrypts inbound;
  * ``encryption.public_key_file``  — encrypts to the peer outbound, verifies
    the peer's signature inbound (the peer public key plays both roles);
  * passphrase (optional) — resolved by the runner from
    ``FILEROUTER_GPG_PASSPHRASE`` or ``encryption.passphrase_file`` and passed in;
    it only unlocks the private key, it is never stored in the YAML.

Keys are loaded lazily (so non-crypto commands never need them) and cached.
PGPy is imported lazily too, so the package works when PGPy is not installed.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from filerouter.core.errors import CryptoError
from filerouter.core.models import KeyInfo, VerificationResult


class PGPyProvider:
    """CryptoProvider backed by PGPy and file-based keys."""

    def __init__(self, encryption_config: Any, passphrase: str | None = None) -> None:
        try:
            import pgpy  # noqa: F401, PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover
            raise CryptoError("PGPy is not installed") from exc
        self._cfg = encryption_config
        self._passphrase = passphrase
        self._priv: Any = None
        self._pub: Any = None

    # -- lazy key loading ----------------------------------------------------

    def _load(self, path: str | None, what: str) -> Any:
        import pgpy  # noqa: PLC0415

        if not path:
            raise CryptoError(f"pgpy backend: encryption.{what} is not set")
        try:
            key, _ = pgpy.PGPKey.from_file(path)
        except Exception as exc:  # noqa: BLE001 - surface any load error clearly
            raise CryptoError(f"cannot load {what} '{path}': {exc}") from exc
        return key

    def _private(self) -> Any:
        if self._priv is None:
            self._priv = self._load(self._cfg.private_key_file, "private_key_file")
        return self._priv

    def _public(self) -> Any:
        if self._pub is None:
            self._pub = self._load(self._cfg.public_key_file, "public_key_file")
        return self._pub

    def _unlocked(self, key: Any):
        """Yield an unlocked private key (context manager); pass-through if clear."""
        if getattr(key, "is_protected", False):
            if not self._passphrase:
                raise CryptoError(
                    "private key is passphrase-protected but no passphrase was "
                    "provided (set FILEROUTER_GPG_PASSPHRASE or encryption.passphrase_file)")
            return key.unlock(self._passphrase)
        return contextlib.nullcontext()

    @staticmethod
    def _encrypt_to(pub: Any, message: Any) -> Any:
        """Encrypt to the first encryption-capable (sub)key of ``pub``."""
        import pgpy  # noqa: PLC0415

        last: Exception | None = None
        for candidate in [pub, *pub.subkeys.values()]:
            try:
                return candidate.encrypt(message)
            except (pgpy.errors.PGPError, ValueError, TypeError) as exc:
                last = exc
        raise CryptoError(f"no encryption-capable (sub)key in public_key_file: {last}")

    def signer_id(self) -> str:
        """Key id of the signing key (the private key) — recorded in metadata.

        Reading the fingerprint does not require the passphrase.
        """
        return str(self._private().fingerprint.keyid)

    def recipient_ids(self) -> list[str]:
        """Recipient identifier(s) recorded in metadata: the peer public key id.

        With the file-based model the recipient is the configured public key, so
        its key id is the natural recipient identifier (the metadata schema needs
        a non-empty recipient list).
        """
        pub = self._public()
        return [str(pub.fingerprint.keyid)]

    # -- CryptoProvider contract --------------------------------------------

    def encrypt(self, clear_path: Path, payload_path: Path,
                recipient_key_ids: list[str], signing_key_id: str | None) -> None:
        """Encrypt to the configured peer public key, optionally signing first."""
        import pgpy  # noqa: PLC0415

        pub = self._public()
        message = pgpy.PGPMessage.new(Path(clear_path).read_bytes())
        if signing_key_id:  # signing requested -> sign with our private key
            priv = self._private()
            with self._unlocked(priv):
                message |= priv.sign(message)
        encrypted = self._encrypt_to(pub, message)
        Path(payload_path).write_bytes(bytes(encrypted))

    def decrypt(self, payload_path: Path, clear_path: Path) -> VerificationResult:
        """Decrypt with our private key and verify the peer signature (if any)."""
        import pgpy  # noqa: PLC0415

        priv = self._private()
        try:
            enc = pgpy.PGPMessage.from_blob(Path(payload_path).read_bytes())
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(f"not a valid OpenPGP message: {exc}") from exc
        with self._unlocked(priv):
            decrypted = priv.decrypt(enc)
        data = decrypted.message
        Path(clear_path).write_bytes(bytes(data) if isinstance(data, (bytes, bytearray))
                                     else str(data).encode("utf-8"))
        return self._verify_message(decrypted)

    def sign_detached(self, data: bytes) -> bytes:
        """Detached signature over ``data`` (the metadata bytes), armored."""
        priv = self._private()
        with self._unlocked(priv):
            sig = priv.sign(data.decode("utf-8"))
        return str(sig).encode("utf-8")

    def verify_detached(self, data: bytes, signature: bytes) -> VerificationResult:
        """Verify a detached signature over ``data`` against the peer public key."""
        import pgpy  # noqa: PLC0415

        pub = self._public()
        try:
            sig = pgpy.PGPSignature.from_blob(signature.decode("utf-8"))
            sv = pub.verify(data.decode("utf-8"), sig)
        except Exception as exc:  # noqa: BLE001
            return VerificationResult(valid=False, reason=str(exc))
        valid = bool(sv)
        return VerificationResult(
            valid=valid, signer_key_id=str(pub.fingerprint.keyid) if valid else None,
            reason=None if valid else "metadata signature not valid")

    def verify(self, payload_path: Path) -> VerificationResult:
        """Verify a signed (clear-signed or signed) message without decrypting."""
        import pgpy  # noqa: PLC0415

        try:
            msg = pgpy.PGPMessage.from_blob(Path(payload_path).read_bytes())
        except Exception as exc:  # noqa: BLE001
            return VerificationResult(valid=False, reason=str(exc))
        return self._verify_message(msg)

    def _verify_message(self, message: Any) -> VerificationResult:
        """Verify ``message`` against the configured peer public key."""
        if not getattr(message, "is_signed", False):
            return VerificationResult(valid=False, reason="unsigned")
        pub = self._public()
        try:
            sv = pub.verify(message)
        except Exception as exc:  # noqa: BLE001
            return VerificationResult(valid=False, reason=str(exc))
        valid = bool(sv)
        signer = str(pub.fingerprint.keyid) if valid else None
        return VerificationResult(valid=valid, signer_key_id=signer,
                                  reason=None if valid else "signature not valid")

    def list_keys(self) -> list[KeyInfo]:
        """Best-effort listing of the configured keys."""
        keys: list[KeyInfo] = []
        for key, can_sign, can_encrypt in (
            (self._safe(self._private), True, False),
            (self._safe(self._public), False, True),
        ):
            if key is not None:
                uids = tuple(str(u) for u in getattr(key, "userids", ()))
                keys.append(KeyInfo(key_id=str(key.fingerprint.keyid), uids=uids,
                                    can_encrypt=can_encrypt, can_sign=can_sign))
        return keys

    @staticmethod
    def _safe(loader) -> Any:
        try:
            return loader()
        except CryptoError:
            return None

    def self_test(self) -> None:
        """Round-trip a small sample through encrypt+sign / decrypt+verify."""
        import tempfile  # noqa: PLC0415

        sample = b"filerouter self-test"
        with tempfile.TemporaryDirectory() as d:
            clear = Path(d) / "c"
            payload = Path(d) / "p"
            back = Path(d) / "b"
            clear.write_bytes(sample)
            self.encrypt(clear, payload, [], "self-test")
            result = self.decrypt(payload, back)
            if back.read_bytes() != sample:
                raise CryptoError("pgpy self-test: round-trip mismatch")
            if not result.valid:
                raise CryptoError(f"pgpy self-test: signature invalid ({result.reason})")
