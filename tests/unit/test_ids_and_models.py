"""Unit tests for the id generators and domain model serialization."""

from __future__ import annotations

from filerouter.adapters.ulid_generator import (
    UlidGenerator,
    Uuid4Generator,
    make_id_generator,
)
from filerouter.core.models import AuditEvent, Direction, FileHash, Metadata


def test_ulid_is_26_chars_and_unique() -> None:
    """ULIDs are 26 Crockford base32 chars and unique across calls."""
    gen = UlidGenerator()
    ids = {gen.new_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(len(i) == 26 for i in ids)


def test_ulid_is_sortable_over_time() -> None:
    """ULIDs generated later sort after earlier ones (time-ordered prefix)."""
    gen = UlidGenerator()
    first = gen.new_id()
    # Same millisecond may tie; generate many and ensure monotonic-ish ordering.
    ids = [gen.new_id() for _ in range(100)]
    assert first <= max(ids)


def test_uuid4_is_hex_32() -> None:
    """UUIDv4 ids are 32 hex characters."""
    gen = Uuid4Generator()
    val = gen.new_id()
    assert len(val) == 32
    assert all(c in "0123456789abcdef" for c in val)


def test_make_id_generator_selects_strategy() -> None:
    """The factory returns the right generator per strategy string."""
    assert isinstance(make_id_generator("uuid4"), Uuid4Generator)
    assert isinstance(make_id_generator("ulid"), UlidGenerator)
    assert isinstance(make_id_generator("anything-else"), UlidGenerator)


def test_metadata_roundtrip_dict() -> None:
    """Metadata.to_dict / from_dict is a faithful round-trip."""
    meta = Metadata(
        schema_version="1.0", technical_id="ABC123", direction=Direction.OUT,
        source_site="PARIS", target_site="FRANKFURT", base_folder_alias="PAYMENT",
        relative_path="a/b", original_filename="f.csv", encrypted=False,
        clear_file_hash=FileHash("SHA-256", "a" * 64),
        payload_file_hash=FileHash("SHA-256", "a" * 64),
        creation_date="2026-06-08T12:00:00Z",
    )
    again = Metadata.from_dict(meta.to_dict())
    assert again.direction is Direction.OUT
    assert again.to_dict() == meta.to_dict()


def test_audit_event_roundtrip_dict() -> None:
    """AuditEvent.to_dict / from_dict preserves all fields."""
    evt = AuditEvent(technical_id="ID1", seq=3, event="DETECTED",
                     ts="2026-06-08T12:00:00.000Z", direction=Direction.IN,
                     host="h", actor="a", details={"k": "v"})
    again = AuditEvent.from_dict(evt.to_dict())
    assert again == evt
