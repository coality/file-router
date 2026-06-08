"""Outbound pipeline: business folder -> exchange_out.

Implements the 10-step outbound flow (docs/fr/02-flows.md §1). Every step is a
small, documented method. The whole pipeline is transactional: on any failure
the item is quarantined and the source is never lost (it lives in
processing/<id>/ until publish is confirmed).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePath

from filerouter.core import compression, hashing, metadata as meta_mod, naming
from filerouter.core.context import Context
from filerouter.core.errors import FileRouterError
from filerouter.core.models import Direction, EncryptionInfo, FileHash, Metadata
from filerouter.core.pathing import business_target, identify_base_folder, relative_path
from filerouter.version import METADATA_SCHEMA_VERSION


@dataclass(frozen=True)
class Outcome:
    """Result of processing one file."""

    status: str  # "published" | "skipped_duplicate" | "quarantined"
    technical_id: str | None = None
    detail: str = ""


def lock_key_for_source(source: PurePath) -> str:
    """Derive a stable lock key from the absolute source path.

    Used before a technical_id exists so the same source cannot be picked up by
    two workers at once.
    """
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    return f"src-{digest[:32]}"


class OutboundProcessor:
    """Drives one source file through the outbound pipeline."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    # -- public entry ----------------------------------------------------

    def process(self, source: Path) -> Outcome:
        """Process one detected source file end-to-end, quarantining on error."""
        key = lock_key_for_source(PurePath(str(source)))
        try:
            with self._ctx.locks.acquire(key):
                return self._run(source)
        except FileRouterError as exc:
            # Lock contention or any domain error: report without crashing the loop.
            return Outcome(status="quarantined", detail=str(exc))

    # -- pipeline --------------------------------------------------------

    def _run(self, source: Path) -> Outcome:
        """Execute the locked pipeline; capture failures into quarantine."""
        technical_id = self._ctx.ids.new_id()
        work = self._ctx.layout.processing / technical_id
        self._ctx.store.makedirs(work)
        try:
            return self._pipeline(source, technical_id, work)
        except Exception as exc:  # noqa: BLE001 - quarantine any failure safely
            return self._quarantine(technical_id, work, source, exc)

    def _pipeline(self, source: Path, technical_id: str, work: Path) -> Outcome:
        """The 10 ordered steps, each delegated to a small helper."""
        alias, rel_dir, original = self._classify(source)
        self._audit(technical_id, "DETECTED", Direction.OUT,
                    {"source_abspath": str(source), "base_folder_alias": alias,
                     "relative_path": rel_dir})

        clear = self._move_source_in(source, work)
        clear_hash = self._hash(clear, technical_id, "clear")

        if self._is_duplicate(clear_hash, alias, rel_dir, technical_id):
            return Outcome("skipped_duplicate", technical_id)

        rule = self._encryption_rule(alias, rel_dir, original)
        compress = self._compresses(alias, rel_dir, original)
        payload, enc_info, comp_info = self._make_payload(
            clear, work, rule, compress, technical_id)
        payload_hash = self._hash(payload, technical_id, "payload")

        technical_name = self._render_name(alias, original, technical_id)
        meta = self._build_metadata(
            technical_id, alias, rel_dir, original, enc_info, comp_info,
            clear_hash, payload_hash, technical_name, clear,
        )
        self._publish(payload, meta, technical_name, technical_id)
        self._finalize_source(clear, technical_id, original)
        return Outcome("published", technical_id)

    # -- steps -----------------------------------------------------------

    def _classify(self, source: Path) -> tuple[str, str, str]:
        """Identify base_folder alias, relative dir and original filename."""
        bases = list(self._ctx.config.base_folders)
        abs_pure = PurePath(str(source))
        base = identify_base_folder(abs_pure, bases)
        rel_dir = relative_path(abs_pure, base)
        return base.alias, rel_dir, source.name

    def _move_source_in(self, source: Path, work: Path) -> Path:
        """Atomically move the source into processing/<id>/clear.

        Moving the source out of the business tree both claims it and preserves
        it until publish is confirmed (no data loss).
        """
        clear = work / "clear"
        self._ctx.store.atomic_move(source, clear)
        return clear

    def _hash(self, path: Path, technical_id: str, target: str) -> FileHash:
        """Compute and audit a SHA-256 digest for ``path``."""
        digest = hashing.sha256_file(path, self._ctx.config.hashing.chunk_size_bytes)
        self._audit(technical_id, "HASH_COMPUTED", Direction.OUT,
                    {"target": target, "algorithm": digest.algorithm,
                     "value": digest.value})
        return digest

    def _is_duplicate(self, clear_hash: FileHash, alias: str, rel: str,
                      technical_id: str) -> bool:
        """Claim the dedup marker; return True if this content was already routed."""
        if self._ctx.config.duplicates.outbound_policy != "skip":
            return False
        first = self._ctx.dedup.claim(clear_hash.value, alias, rel, technical_id)
        if not first:
            self._log("functional", "INFO", "OUTBOUND_DUPLICATE_SKIPPED",
                      technical_id, base_folder_alias=alias)
        return not first

    def _encryption_rule(self, alias: str, rel_dir: str, original: str):
        """Return the matching encryption rule for this file, or None."""
        rel_file = f"{rel_dir}/{original}" if rel_dir else original
        return self._ctx.config.ruleset.encryption_for(alias, rel_file)

    def _compresses(self, alias: str, rel_dir: str, original: str) -> bool:
        """Return True if a compression rule matches this file."""
        rel_file = f"{rel_dir}/{original}" if rel_dir else original
        return self._ctx.config.ruleset.compresses(alias, rel_file)

    def _make_payload(self, clear: Path, work: Path, rule, compress: bool,
                      technical_id: str):
        """Build the payload: optional gzip compression THEN optional encryption.

        Order matters: compressing before encrypting keeps a good ratio, since
        encrypted bytes do not compress. Returns (payload, enc_info, comp_info).
        """
        staged, comp_info = self._maybe_compress(clear, work, compress, technical_id)
        payload, enc_info = self._maybe_encrypt(staged, work, rule, technical_id)
        return payload, enc_info, comp_info

    def _maybe_compress(self, clear: Path, work: Path, compress: bool,
                        technical_id: str):
        """Gzip the clear file when requested; else pass the clear file through."""
        if not compress:
            return clear, None
        staged = work / "compressed"
        compression.compress_file(clear, staged, self._ctx.config.compression.level)
        self._audit(technical_id, "COMPRESSED", Direction.OUT,
                    {"algorithm": compression.ALGORITHM})
        return staged, {"algorithm": compression.ALGORITHM}

    def _maybe_encrypt(self, staged: Path, work: Path, rule, technical_id: str):
        """Encrypt+sign the staged file when a rule matches; else copy it."""
        payload = work / "payload"
        if rule is None:
            # No rule: payload is a byte-for-byte copy of the staged file.
            self._copy(staged, payload)
            return payload, None
        recipients = list(rule.recipient_key_ids)
        if not recipients:
            # File-based backends (pgpy) encrypt to a configured key, not key ids;
            # record that key's id so the metadata carries a real recipient.
            provider_recipients = getattr(self._ctx.crypto, "recipient_ids", None)
            if provider_recipients is not None:
                recipients = list(provider_recipients())
        signing = self._signing_id()
        self._ctx.crypto.encrypt(staged, payload, recipients, signing)
        enc = EncryptionInfo(
            scheme="OpenPGP", recipient_key_ids=recipients,
            signing_key_id=signing, signed=signing is not None,
        )
        self._audit(technical_id, "ENCRYPTED", Direction.OUT,
                    {"recipient_key_ids": recipients, "signing_key_id": signing})
        return payload, enc

    def _signing_id(self) -> str | None:
        """Resolve the signing identity recorded in metadata (None = do not sign).

        Signing is enabled by ``sign_outbound`` OR (backward compat) by setting
        ``signing_key_id``. For gnupg the key id selects the keyring key; for
        file-based backends (pgpy) the key is ``private_key_file`` and we record
        its REAL key id rather than a placeholder.
        """
        enc = self._ctx.config.encryption
        if not (enc.sign_outbound or enc.signing_key_id):
            return None
        if enc.signing_key_id:
            return enc.signing_key_id
        provider_signer = getattr(self._ctx.crypto, "signer_id", None)
        return provider_signer() if provider_signer is not None else None

    def _copy(self, src: Path, dst: Path) -> None:
        """Copy bytes via the store (payload == clear when not encrypted)."""
        self._ctx.store.atomic_write_bytes(dst, self._ctx.store.read_bytes(src))

    def _render_name(self, alias: str, original: str, technical_id: str) -> str:
        """Render the technical filename for the exchange directory."""
        ctx = naming.NamingContext(
            flow=self._ctx.config.flow_for(alias),
            direction=Direction.OUT,
            timestamp=self._ctx.clock.now_compact(
                self._ctx.config.naming.timestamp_format),
            technical_id=technical_id,
            extension=_extension(original),
            base_folder_alias=alias,
            source_site=self._ctx.config.instance.site,
            target_site=self._ctx.config.routing.get(alias, ""),
        )
        name = naming.render(ctx, self._ctx.config.naming)
        self._audit(technical_id, "RENAMED", Direction.OUT,
                    {"technical_filename": name})
        return name

    def _build_metadata(self, technical_id, alias, rel_dir, original, enc_info,
                        comp_info, clear_hash, payload_hash, technical_name,
                        clear) -> Metadata:
        """Assemble the metadata object (validated later on serialization)."""
        return Metadata(
            schema_version=METADATA_SCHEMA_VERSION,
            technical_id=technical_id,
            direction=Direction.OUT,
            source_site=self._ctx.config.instance.site,
            target_site=self._ctx.config.routing.get(alias, ""),
            base_folder_alias=alias,
            relative_path=rel_dir,
            original_filename=original,
            encrypted=enc_info is not None,
            clear_file_hash=clear_hash,
            payload_file_hash=payload_hash,
            creation_date=self._ctx.clock.now_utc_iso(),
            technical_filename=technical_name,
            extension=_extension(original),
            size_bytes=self._ctx.store.size(clear),
            encryption=enc_info,
            compressed=comp_info is not None,
            compression=comp_info,
            naming={"pattern": self._ctx.config.naming.pattern},
            producer={"app": "FileRouter", "host": self._ctx.host},
        )

    def _publish(self, payload: Path, meta: Metadata, technical_name: str,
                 technical_id: str) -> None:
        """Publish payload then metadata into exchange_out (payload first).

        Publishing the payload before the metadata means a consumer never sees a
        metadata file pointing at a missing payload.
        """
        out = self._ctx.layout.exchange_out
        cfg = self._ctx.config.naming
        meta_name = naming.meta_name(technical_name, cfg)
        meta_bytes = meta_mod.dumps(meta)
        # Order: payload, then (optional) detached metadata signature, then the
        # metadata LAST. The metadata file is the commit marker the receiver waits
        # on, so by the time it appears the signature is already present.
        self._ctx.store.atomic_move(payload, out / technical_name)
        if meta.encryption is not None and meta.encryption.signed:
            sig = self._ctx.crypto.sign_detached(meta_bytes)
            self._ctx.store.atomic_write_bytes(
                out / naming.meta_sig_name(technical_name, cfg), sig)
        self._ctx.store.atomic_write_bytes(out / meta_name, meta_bytes)
        self._audit(technical_id, "MOVED_TO_EXCHANGE_OUT", Direction.OUT,
                    {"path": str(out / technical_name)})
        self._log("functional", "INFO", "ROUTED_OUT", technical_id,
                  base_folder_alias=meta.base_folder_alias)
        self._journal_out(meta, technical_name, technical_id)

    def _journal_out(self, meta: Metadata, technical_name: str,
                     technical_id: str) -> None:
        """Append a support-friendly line to the human-readable transfer log."""
        enc = meta.encryption
        base = self._ctx.config.base_folder_by_alias(meta.base_folder_alias)
        source = (str(business_target(base.path, meta.relative_path,
                                      meta.original_filename))
                  if base else meta.original_filename)
        self._ctx.journal.outbound(
            technical_id=technical_id, alias=meta.base_folder_alias,
            relative_path=meta.relative_path, original_filename=meta.original_filename,
            technical_filename=technical_name, source_site=meta.source_site,
            target_site=meta.target_site, source_path=source,
            encrypted=meta.encrypted,
            signed=bool(enc and enc.signed),
            compressed=meta.compressed,
            compression_algo=(meta.compression or {}).get("algorithm"),
            signer_key_id=(enc.signing_key_id if (enc and enc.signed) else None),
            clear_sha256=meta.clear_file_hash.value)

    def _finalize_source(self, clear: Path, technical_id: str, original: str) -> None:
        """Archive or delete the source now that publish is confirmed."""
        policy = self._ctx.config.archival.source_policy
        if policy == "delete":
            self._ctx.store.remove(clear)
        else:
            layout = self._ctx.clock.now_compact(
                self._ctx.config.archival.archive_layout)
            dest = self._ctx.layout.archive / layout / f"{technical_id}__{original}"
            self._ctx.store.atomic_move(clear, dest)
            self._audit(technical_id, "ARCHIVED", Direction.OUT,
                        {"archive_path": str(dest)})
        self._cleanup(clear.parent)

    def _cleanup(self, work: Path) -> None:
        """Best-effort removal of the now-empty processing directory."""
        try:
            work.rmdir()
        except OSError:
            pass

    # -- failure path ----------------------------------------------------

    def _quarantine(self, technical_id: str, work: Path, source: Path,
                    exc: Exception) -> Outcome:
        """Audit ERROR and move artifacts to quarantine; never lose the source."""
        error = {"step": "outbound", "exception_type": type(exc).__name__,
                 "message": str(exc)}
        artifacts = [p for p in (work / "clear", work / "payload") if p.exists()]
        if source.exists():
            artifacts.append(source)
        qdir = self._ctx.quarantine.capture(technical_id, artifacts, error)
        self._audit(technical_id, "ERROR", Direction.OUT,
                    {**error, "quarantine_path": str(qdir)})
        self._log("security", "ERROR", "OUTBOUND_ERROR", technical_id, **error)
        self._cleanup(work)
        return Outcome("quarantined", technical_id, str(exc))

    # -- helpers ---------------------------------------------------------

    def _audit(self, technical_id: str, event: str, direction: Direction,
               details: dict) -> None:
        """Append one audit event with host/actor populated."""
        self._ctx.audit.append(technical_id, event, direction=direction,
                               host=self._ctx.host, actor="OutboundProcessor",
                               details=details)

    def _log(self, stream: str, level: str, event: str, technical_id: str,
             **fields) -> None:
        """Emit one structured log record."""
        self._ctx.log.log(stream, level, event, technical_id=technical_id, **fields)


def _extension(filename: str) -> str:
    """Return the file extension without the dot (empty if none)."""
    _, dot, ext = filename.rpartition(".")
    return ext if dot else ""
