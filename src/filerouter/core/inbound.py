"""Inbound pipeline: exchange_in -> business folder.

Implements the 8-step inbound flow (docs/fr/02-flows.md §2) with strict validation
order. A payload in exchange_in may still be uploading, or its metadata may not
have arrived yet; readiness is decided WITHOUT a database, from pair presence,
file stability and file age (see ``InboundReadiness``).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from filerouter.core import compression, hashing, metadata as meta_mod
from filerouter.core.context import Context
from filerouter.core.errors import CryptoError, DataError, IntegrityError
from filerouter.core.models import Direction, Metadata, VerificationResult
from filerouter.core.pathing import business_target


@dataclass(frozen=True)
class Outcome:
    """Result of processing one inbound pair."""

    status: str  # "delivered" | "skipped_duplicate" | "quarantined" | "not_ready"
    technical_id: str | None = None
    detail: str = ""


class InboundReadiness:
    """Decides whether an exchange_in payload is ready to be processed.

    Readiness rules (no database, crash-safe):
      * payload + metadata BOTH present and BOTH stable -> ready;
      * payload present, metadata missing, file age < grace -> wait (retry later);
      * payload present, metadata missing, file age >= grace -> incomplete pair.
    File age uses mtime, so it survives restarts.
    """

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def meta_path_for(self, payload: Path) -> Path:
        """Return the metadata sidecar path for a payload in exchange_in."""
        return payload.with_name(payload.name + self._ctx.config.naming.meta_suffix)

    def sig_path_for(self, payload: Path) -> Path:
        """Return the metadata-signature sidecar path for a payload."""
        return self.meta_path_for(payload).with_name(
            self.meta_path_for(payload).name + ".sig")

    def is_meta(self, path: Path) -> bool:
        """Return True if ``path`` is a metadata or signature sidecar (not a payload)."""
        suffix = self._ctx.config.naming.meta_suffix
        return path.name.endswith(suffix) or path.name.endswith(suffix + ".sig")

    def state(self, payload: Path) -> str:
        """Classify a payload: 'ready' | 'wait' | 'incomplete'.

        When the metadata itself declares the payload was SIGNED, the detached
        metadata-signature sidecar is part of the expected set — so a reordered
        transport (meta before sig) does not trigger a premature quarantine. An
        UNSIGNED sender (meta says not signed) is not made to wait for a sig that
        will never arrive; the pipeline then decides per require_signature_inbound.
        """
        meta = self.meta_path_for(payload)
        grace = self._ctx.config.scanning.pair_grace_period_seconds
        if not self._ctx.store.exists(meta):
            return "wait" if self._age_seconds(payload) < grace else "incomplete"
        expected = [payload, meta]
        if self._meta_says_signed(meta):
            sig = self.sig_path_for(payload)
            if not self._ctx.store.exists(sig):
                return "wait" if self._age_seconds(payload) < grace else "incomplete"
            expected.append(sig)
        return "ready" if self._all_stable(expected) else "wait"

    def _meta_says_signed(self, meta: Path) -> bool:
        """Best-effort peek at whether the sender signed (drives sig expectation)."""
        try:
            data = json.loads(self._ctx.store.read_text(meta))
        except Exception:  # noqa: BLE001 - unparseable meta: let the pipeline handle it
            return False
        enc = data.get("encryption")
        return bool(enc and enc.get("signed"))

    def _all_stable(self, paths: list[Path]) -> bool:
        """Return True only if none of ``paths`` is still being written."""
        checks = self._ctx.config.scanning.stability_checks
        interval = self._ctx.config.scanning.stability_interval_seconds
        return all(self._ctx.store.is_stable(p, checks, interval) for p in paths)

    def _age_seconds(self, path: Path) -> float:
        """Age of a file in seconds, based on its mtime."""
        return max(0.0, time.time() - self._ctx.store.mtime(path))


class InboundProcessor:
    """Drives one exchange_in pair through the inbound pipeline."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._readiness = InboundReadiness(ctx)

    # -- public entry ----------------------------------------------------

    def process(self, payload: Path) -> Outcome:
        """Process one payload if ready; otherwise report 'not_ready'."""
        if self._readiness.is_meta(payload):
            return Outcome("not_ready", detail="metadata sidecar, not a payload")
        state = self._readiness.state(payload)
        if state == "wait":
            return Outcome("not_ready", detail="pair incomplete or unstable")
        if state == "incomplete":
            return self._quarantine_orphan(payload)
        return self._locked_run(payload)

    # -- pipeline --------------------------------------------------------

    def _locked_run(self, payload: Path) -> Outcome:
        """Read metadata, take the per-id lock, then run the validated pipeline."""
        meta_path = self._readiness.meta_path_for(payload)
        try:
            meta = meta_mod.load_file(meta_path)
        except DataError as exc:
            return self._quarantine_unparsed(payload, meta_path, exc)
        try:
            with self._ctx.locks.acquire(meta.technical_id):
                return self._pipeline(payload, meta_path, meta)
        except Exception as exc:  # noqa: BLE001 - quarantine any failure safely
            return self._quarantine(meta.technical_id, payload, meta_path, exc)

    def _pipeline(self, payload: Path, meta_path: Path, meta: Metadata) -> Outcome:
        """The 8 ordered steps; each delegated to a small helper."""
        technical_id = meta.technical_id
        # Inbound duplicate = already DELIVERED here (not merely published by the
        # outbound side, whose events may share this id's audit on a single host).
        if self._ctx.audit.has_event(technical_id, "MOVED_TO_BUSINESS_FOLDER"):
            return self._skip_duplicate(technical_id, payload, meta_path)

        work = self._move_pair_in(payload, meta_path, technical_id, meta)
        self._verify_payload_hash(work.payload, meta, technical_id)
        self._verify_metadata_signature(work, meta, technical_id)
        staged = self._decrypt_or_passthrough(work.payload, work.dir, meta, technical_id)
        clear = self._maybe_decompress(staged, work.dir, meta, technical_id)
        self._verify_clear_hash(clear, meta, technical_id)
        self._deliver(clear, meta, technical_id)
        self._cleanup(work.dir)
        return Outcome("delivered", technical_id)

    # -- steps -----------------------------------------------------------

    def _move_pair_in(self, payload: Path, meta_path: Path, technical_id: str,
                      meta: Metadata) -> "_Work":
        """Move payload+metadata into processing/<id>/ and audit receipt."""
        work_dir = self._ctx.layout.processing / technical_id
        self._ctx.store.makedirs(work_dir)
        dst_payload = work_dir / "payload"
        dst_meta = work_dir / "metadata.json"
        self._ctx.store.atomic_move(payload, dst_payload)
        self._ctx.store.atomic_move(meta_path, dst_meta)
        # Move the detached metadata signature too, when present.
        sig_src = self._readiness.sig_path_for(payload)
        dst_sig: Path | None = None
        if self._ctx.store.exists(sig_src):
            dst_sig = work_dir / "metadata.json.sig"
            self._ctx.store.atomic_move(sig_src, dst_sig)
        self._audit(technical_id, "RECEIVED_FROM_EXCHANGE_IN", meta,
                    {"technical_filename": meta.technical_filename})
        return _Work(work_dir, dst_payload, dst_meta, dst_sig)

    def _verify_metadata_signature(self, work: "_Work", meta: Metadata,
                                   technical_id: str) -> None:
        """Authenticate the metadata sidecar via its detached signature.

        This binds the ROUTING fields (relative_path, original_filename, alias,
        hashes...) to the trusted signer, so a tampering party on exchange_in
        cannot redirect a validly-signed payload. Enforced when signatures are
        required; if a signature is present it is always checked.
        """
        enc = self._ctx.config.encryption
        if work.sig is None or not self._ctx.store.exists(work.sig):
            if enc.require_signature_inbound:
                raise CryptoError("metadata signature missing")
            return
        meta_bytes = self._ctx.store.read_bytes(work.meta)
        result = self._ctx.crypto.verify_detached(
            meta_bytes, self._ctx.store.read_bytes(work.sig))
        if not result.valid:
            raise CryptoError(f"invalid metadata signature: {result.reason}")
        if enc.allowed_signers and not _signer_allowed(result.signer_key_id,
                                                        enc.allowed_signers):
            raise CryptoError(
                f"metadata signer not authorized: {result.signer_key_id}")
        self._audit(technical_id, "HASH_VALIDATED", meta,
                    {"target": "metadata_signature",
                     "signer_key_id": result.signer_key_id})

    def _verify_payload_hash(self, payload: Path, meta: Metadata,
                             technical_id: str) -> None:
        """Verify the payload digest BEFORE any cryptographic operation."""
        actual = hashing.sha256_file(payload, self._ctx.config.hashing.chunk_size_bytes)
        if not hashing.hashes_match(meta.payload_file_hash, actual):
            raise IntegrityError("payload hash mismatch")
        self._audit(technical_id, "HASH_VALIDATED", meta,
                    {"target": "payload", "value": actual.value})

    def _decrypt_or_passthrough(self, payload: Path, work_dir: Path, meta: Metadata,
                                technical_id: str) -> Path:
        """Decrypt+verify signature if encrypted, else pass the payload through.

        Returns the decrypted file (which may still be compressed) or the payload.
        """
        if not meta.encrypted:
            return payload
        decrypted = work_dir / "decrypted"
        result = self._ctx.crypto.decrypt(payload, decrypted)
        self._enforce_signature(result, meta)
        self._audit(technical_id, "DECRYPTED", meta,
                    {"signer_key_id": result.signer_key_id})
        return decrypted

    def _maybe_decompress(self, staged: Path, work_dir: Path, meta: Metadata,
                          technical_id: str) -> Path:
        """Decompress the staged file when the metadata says it was compressed."""
        if not meta.compressed:
            return staged
        clear = work_dir / "clear"
        compression.decompress_file(staged, clear)
        self._audit(technical_id, "DECOMPRESSED", meta,
                    {"algorithm": (meta.compression or {}).get("algorithm")})
        return clear

    def _enforce_signature(self, result: VerificationResult, meta: Metadata) -> None:
        """Require a valid signature from a whitelisted signer when configured.

        Security: a valid signature is not enough; the signer must be authorized.
        """
        enc = self._ctx.config.encryption
        if not enc.require_signature_inbound:
            return
        if not result.valid:
            raise CryptoError(f"invalid or missing signature: {result.reason}")
        allowed = enc.allowed_signers
        if allowed and not _signer_allowed(result.signer_key_id, allowed):
            raise CryptoError(f"signer not authorized: {result.signer_key_id}")

    def _verify_clear_hash(self, clear: Path, meta: Metadata,
                           technical_id: str) -> None:
        """Verify the clear digest after decryption (end-to-end integrity)."""
        actual = hashing.sha256_file(clear, self._ctx.config.hashing.chunk_size_bytes)
        if not hashing.hashes_match(meta.clear_file_hash, actual):
            raise IntegrityError("clear hash mismatch")
        self._audit(technical_id, "HASH_VALIDATED", meta,
                    {"target": "clear", "value": actual.value})

    def _deliver(self, clear: Path, meta: Metadata, technical_id: str) -> None:
        """Rebuild the business path, restore the name and publish atomically."""
        base = self._ctx.config.base_folder_by_alias(meta.base_folder_alias)
        if base is None:
            raise DataError(f"unknown base_folder alias: {meta.base_folder_alias}")
        target = Path(business_target(base.path, meta.relative_path,
                                      meta.original_filename))
        self._ctx.store.makedirs(target.parent)
        self._audit(technical_id, "RESTORED", meta,
                    {"target_path": str(target)})
        self._ctx.store.atomic_move(clear, target)
        self._audit(technical_id, "MOVED_TO_BUSINESS_FOLDER", meta,
                    {"path": str(target)})
        self._log("functional", "INFO", "DELIVERED_IN", technical_id,
                  base_folder_alias=meta.base_folder_alias)
        enc = meta.encryption
        self._ctx.journal.inbound(
            technical_id=technical_id, alias=meta.base_folder_alias,
            relative_path=meta.relative_path, original_filename=meta.original_filename,
            technical_filename=meta.technical_filename or "", source_site=meta.source_site,
            target_site=meta.target_site, target_path=str(target),
            encrypted=meta.encrypted,
            signed=bool(enc and enc.signed),
            compressed=meta.compressed,
            compression_algo=(meta.compression or {}).get("algorithm"),
            signer_key_id=(enc.signing_key_id if (enc and enc.signed) else None),
            clear_sha256=meta.clear_file_hash.value)

    # -- duplicate / failure paths --------------------------------------

    def _skip_duplicate(self, technical_id: str, payload: Path,
                        meta_path: Path) -> Outcome:
        """Skip an already-delivered technical_id per inbound duplicate policy."""
        self._ctx.store.remove(payload)
        self._ctx.store.remove(meta_path)
        self._log("functional", "INFO", "INBOUND_DUPLICATE_SKIPPED", technical_id)
        return Outcome("skipped_duplicate", technical_id)

    def _quarantine(self, technical_id: str, payload: Path, meta_path: Path,
                    exc: Exception) -> Outcome:
        """Audit ERROR and quarantine the pair; never deliver on doubt."""
        work_dir = self._ctx.layout.processing / technical_id
        error = {"step": "inbound", "exception_type": type(exc).__name__,
                 "message": str(exc)}
        artifacts = _existing([
            work_dir / "payload", work_dir / "clear", work_dir / "metadata.json",
            work_dir / "metadata.json.sig", payload, meta_path,
            self._readiness.sig_path_for(payload),
        ])
        qdir = self._ctx.quarantine.capture(technical_id, artifacts, error)
        self._audit_id(technical_id, "ERROR", error | {"quarantine_path": str(qdir)})
        self._log("security", "ERROR", "INBOUND_ERROR", technical_id, **error)
        self._cleanup(work_dir)
        return Outcome("quarantined", technical_id, str(exc))

    def _quarantine_unparsed(self, payload: Path, meta_path: Path,
                             exc: Exception) -> Outcome:
        """Quarantine a pair whose metadata cannot be parsed (no technical_id)."""
        fallback_id = f"unparsed-{payload.name}"
        error = {"step": "inbound_load", "exception_type": type(exc).__name__,
                 "message": str(exc)}
        qdir = self._ctx.quarantine.capture(fallback_id, _existing([payload, meta_path]),
                                            error)
        self._log("security", "ERROR", "INBOUND_METADATA_CORRUPT", fallback_id,
                  quarantine_path=str(qdir))
        return Outcome("quarantined", fallback_id, str(exc))

    def _quarantine_orphan(self, payload: Path) -> Outcome:
        """Quarantine a payload whose metadata never arrived within the grace."""
        fallback_id = f"orphan-{payload.name}"
        error = {"step": "inbound_pair", "exception_type": "DataError",
                 "message": "metadata never arrived within grace period"}
        qdir = self._ctx.quarantine.capture(fallback_id, _existing([payload]), error)
        self._log("security", "WARNING", "INBOUND_INCOMPLETE_PAIR", fallback_id,
                  quarantine_path=str(qdir))
        return Outcome("quarantined", fallback_id, error["message"])

    # -- helpers ---------------------------------------------------------

    def _cleanup(self, work: Path) -> None:
        """Best-effort removal of the now-empty processing directory."""
        try:
            work.rmdir()
        except OSError:
            pass

    def _audit(self, technical_id: str, event: str, meta: Metadata,
               details: dict) -> None:
        """Append one inbound audit event with direction IN."""
        self._ctx.audit.append(technical_id, event, direction=Direction.IN,
                               host=self._ctx.host, actor="InboundProcessor",
                               details=details)

    def _audit_id(self, technical_id: str, event: str, details: dict) -> None:
        """Append an audit event when only the technical_id is known."""
        self._ctx.audit.append(technical_id, event, direction=Direction.IN,
                               host=self._ctx.host, actor="InboundProcessor",
                               details=details)

    def _log(self, stream: str, level: str, event: str, technical_id: str,
             **fields) -> None:
        """Emit one structured log record."""
        self._ctx.log.log(stream, level, event, technical_id=technical_id, **fields)


@dataclass(frozen=True)
class _Work:
    """Paths of an item being processed in processing/<id>/."""

    dir: Path
    payload: Path
    meta: Path
    sig: Path | None = None


def _signer_allowed(signer_key_id: str | None, allowed: tuple[str, ...]) -> bool:
    """Return True if the signer key id matches any allowed key (suffix match).

    GnuPG reports key ids/fingerprints of varying length; a suffix match handles
    short vs long key ids consistently.
    """
    if signer_key_id is None:
        return False
    sid = signer_key_id.upper().removeprefix("0X")
    for key in allowed:
        k = key.upper().removeprefix("0X")
        if sid.endswith(k) or k.endswith(sid):
            return True
    return False


def _existing(paths: list[Path]) -> list[Path]:
    """Filter a list of paths down to those that currently exist."""
    return [p for p in paths if p.exists()]
