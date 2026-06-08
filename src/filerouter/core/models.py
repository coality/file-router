"""Domain model (dataclasses).

Identifiers are in English (contract elements); comments and docstrings in English.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Direction(enum.Enum):
    """Direction a file travels."""

    OUT = "OUT"
    IN = "IN"


@dataclass(frozen=True)
class FileHash:
    """A file digest."""

    algorithm: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileHash":
        return cls(algorithm=data["algorithm"], value=data["value"])


@dataclass
class EncryptionInfo:
    """Encryption details carried by the metadata."""

    scheme: str = "OpenPGP"
    recipient_key_ids: list[str] = field(default_factory=list)
    signing_key_id: str | None = None
    signed: bool = False
    key_epoch: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "scheme": self.scheme,
            "recipient_key_ids": list(self.recipient_key_ids),
            "signed": self.signed,
        }
        if self.signing_key_id is not None:
            data["signing_key_id"] = self.signing_key_id
        if self.key_epoch is not None:
            data["key_epoch"] = self.key_epoch
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EncryptionInfo":
        return cls(
            scheme=data.get("scheme", "OpenPGP"),
            recipient_key_ids=list(data.get("recipient_key_ids", [])),
            signing_key_id=data.get("signing_key_id"),
            signed=bool(data.get("signed", False)),
            key_epoch=data.get("key_epoch"),
        )


@dataclass
class Metadata:
    """Metadata accompanying a routed file (see docs/fr/04-data-formats.md)."""

    schema_version: str
    technical_id: str
    direction: Direction
    source_site: str
    target_site: str
    base_folder_alias: str
    relative_path: str
    original_filename: str
    encrypted: bool
    clear_file_hash: FileHash
    payload_file_hash: FileHash
    creation_date: str
    technical_filename: str | None = None
    extension: str | None = None
    size_bytes: int | None = None
    encryption: EncryptionInfo | None = None
    compressed: bool = False
    compression: dict[str, Any] | None = None  # {"algorithm": "gzip"} when compressed
    naming: dict[str, Any] = field(default_factory=dict)
    producer: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "technical_id": self.technical_id,
            "direction": self.direction.value,
            "source_site": self.source_site,
            "target_site": self.target_site,
            "base_folder_alias": self.base_folder_alias,
            "relative_path": self.relative_path,
            "original_filename": self.original_filename,
            "encrypted": self.encrypted,
            "clear_file_hash": self.clear_file_hash.to_dict(),
            "payload_file_hash": self.payload_file_hash.to_dict(),
            "creation_date": self.creation_date,
        }
        if self.technical_filename is not None:
            data["technical_filename"] = self.technical_filename
        if self.extension is not None:
            data["extension"] = self.extension
        if self.size_bytes is not None:
            data["size_bytes"] = self.size_bytes
        if self.encryption is not None:
            data["encryption"] = self.encryption.to_dict()
        if self.compressed:
            data["compressed"] = self.compressed
            if self.compression is not None:
                data["compression"] = self.compression
        if self.naming:
            data["naming"] = self.naming
        if self.producer:
            data["producer"] = self.producer
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Metadata":
        enc = data.get("encryption")
        return cls(
            schema_version=data["schema_version"],
            technical_id=data["technical_id"],
            direction=Direction(data["direction"]),
            source_site=data["source_site"],
            target_site=data["target_site"],
            base_folder_alias=data["base_folder_alias"],
            relative_path=data["relative_path"],
            original_filename=data["original_filename"],
            encrypted=bool(data["encrypted"]),
            clear_file_hash=FileHash.from_dict(data["clear_file_hash"]),
            payload_file_hash=FileHash.from_dict(data["payload_file_hash"]),
            creation_date=data["creation_date"],
            technical_filename=data.get("technical_filename"),
            extension=data.get("extension"),
            size_bytes=data.get("size_bytes"),
            encryption=EncryptionInfo.from_dict(enc) if enc else None,
            compressed=bool(data.get("compressed", False)),
            compression=data.get("compression"),
            naming=data.get("naming", {}),
            producer=data.get("producer", {}),
        )


@dataclass
class AuditEvent:
    """One audit event (a single JSON-Lines row)."""

    technical_id: str
    seq: int
    event: str
    ts: str
    direction: Direction | None = None
    host: str | None = None
    actor: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "technical_id": self.technical_id,
            "seq": self.seq,
            "event": self.event,
            "ts": self.ts,
        }
        if self.direction is not None:
            data["direction"] = self.direction.value
        if self.host is not None:
            data["host"] = self.host
        if self.actor is not None:
            data["actor"] = self.actor
        if self.details:
            data["details"] = self.details
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEvent":
        direction = data.get("direction")
        return cls(
            technical_id=data["technical_id"],
            seq=int(data["seq"]),
            event=data["event"],
            ts=data["ts"],
            direction=Direction(direction) if direction else None,
            host=data.get("host"),
            actor=data.get("actor"),
            details=data.get("details", {}),
        )


@dataclass(frozen=True)
class KeyInfo:
    """Minimal information about a keyring key."""

    key_id: str
    uids: tuple[str, ...] = ()
    can_encrypt: bool = False
    can_sign: bool = False


@dataclass(frozen=True)
class VerificationResult:
    """Result of a signature verification."""

    valid: bool
    signer_key_id: str | None = None
    reason: str | None = None


# Audit event vocabulary (docs/fr/04-data-formats.md).
AUDIT_EVENTS: frozenset[str] = frozenset(
    {
        "DETECTED",
        "HASH_COMPUTED",
        "COMPRESSED",
        "ENCRYPTED",
        "RENAMED",
        "MOVED_TO_EXCHANGE_OUT",
        "RECEIVED_FROM_EXCHANGE_IN",
        "HASH_VALIDATED",
        "DECRYPTED",
        "DECOMPRESSED",
        "RESTORED",
        "MOVED_TO_BUSINESS_FOLDER",
        "ARCHIVED",
        "ERROR",
    }
)
