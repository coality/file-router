"""Unit tests for metadata serialization and validation."""

from __future__ import annotations

import pytest

from filerouter.core import metadata as meta_mod
from filerouter.core.errors import DataError
from filerouter.core.models import Direction, EncryptionInfo, FileHash, Metadata


def _meta(**over) -> Metadata:
    """Build a valid metadata object with overridable fields."""
    base = dict(
        schema_version="1.0", technical_id="ABC123", direction=Direction.OUT,
        source_site="PARIS", target_site="FRANKFURT", base_folder_alias="PAYMENT",
        relative_path="a/b/c", original_filename="file.csv", encrypted=False,
        clear_file_hash=FileHash("SHA-256", "a" * 64),
        payload_file_hash=FileHash("SHA-256", "a" * 64),
        creation_date="2026-06-08T12:00:00Z",
    )
    base.update(over)
    return Metadata(**base)


def test_roundtrip_serialization() -> None:
    """dumps then loads returns an equivalent metadata object."""
    original = _meta()
    parsed = meta_mod.loads(meta_mod.dumps(original))
    assert parsed.technical_id == original.technical_id
    assert parsed.relative_path == original.relative_path
    assert parsed.clear_file_hash == original.clear_file_hash


def test_encrypted_requires_encryption_block() -> None:
    """encrypted=True without an encryption block fails validation."""
    bad = _meta(encrypted=True)  # no EncryptionInfo attached
    with pytest.raises(DataError):
        meta_mod.dumps(bad)


def test_encrypted_with_block_validates() -> None:
    """encrypted=True with a proper encryption block is valid."""
    good = _meta(
        encrypted=True,
        encryption=EncryptionInfo(recipient_key_ids=["0xKEY"], signed=True,
                                  signing_key_id="0xSIG"),
        payload_file_hash=FileHash("SHA-256", "b" * 64),
    )
    parsed = meta_mod.loads(meta_mod.dumps(good))
    assert parsed.encrypted is True
    assert parsed.encryption.recipient_key_ids == ["0xKEY"]


def test_corrupt_json_raises() -> None:
    """Corrupt JSON yields a clear DataError."""
    with pytest.raises(DataError):
        meta_mod.loads("{not json")


def test_unsupported_schema_version_rejected() -> None:
    """A metadata with an unknown schema_version is rejected."""
    bad = _meta(schema_version="9.9")
    with pytest.raises(DataError):
        meta_mod.dumps(bad)


def test_relative_path_with_backslash_rejected() -> None:
    """A relative_path containing backslashes fails schema validation."""
    bad = _meta(relative_path="a\\b\\c")
    with pytest.raises(DataError):
        meta_mod.dumps(bad)
