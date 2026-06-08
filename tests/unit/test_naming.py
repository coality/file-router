"""Unit tests for the technical-name rendering engine."""

from __future__ import annotations

import pytest

from filerouter.core.errors import DataError
from filerouter.core.models import Direction
from filerouter.core.naming import (
    NamingConfig,
    NamingContext,
    meta_name,
    render,
    validate_pattern,
)


def _ctx(**over) -> NamingContext:
    """Build a naming context with sensible defaults for tests."""
    base = dict(flow="PAYMENT", direction=Direction.OUT, timestamp="20260608T120000",
                technical_id="ABC123", extension="csv", base_folder_alias="PAYMENT")
    base.update(over)
    return NamingContext(**base)


def _cfg(**over) -> NamingConfig:
    """Build a naming config with a default pattern for tests."""
    base = dict(pattern="{flow}_{direction}_{timestamp}_{technical_id}.{extension}")
    base.update(over)
    return NamingConfig(**base)


def test_render_basic_pattern() -> None:
    """The default pattern renders the expected support-friendly name."""
    assert render(_ctx(), _cfg()) == "PAYMENT_OUT_20260608T120000_ABC123.csv"


def test_validate_pattern_requires_technical_id() -> None:
    """A pattern without {technical_id} is rejected (uniqueness guarantee)."""
    with pytest.raises(DataError):
        validate_pattern("{flow}_{timestamp}.{extension}")


def test_render_rejects_unknown_placeholder() -> None:
    """An unknown placeholder raises a clear DataError."""
    with pytest.raises(DataError):
        render(_ctx(), _cfg(pattern="{flow}_{unknown}_{technical_id}"))


def test_render_enforces_max_length() -> None:
    """A name longer than max_length is rejected."""
    with pytest.raises(DataError):
        render(_ctx(technical_id="X" * 200), _cfg(max_length=32))


def test_render_rejects_non_portable_characters() -> None:
    """The portable charset rejects characters illegal on Windows."""
    with pytest.raises(DataError):
        render(_ctx(flow="bad:name"), _cfg())


def test_render_rejects_reserved_windows_name() -> None:
    """A reserved Windows device name (stem 'CON') is rejected."""
    # Pattern renders to "CON.csv_ABC123" whose stem before '.' is 'CON'.
    with pytest.raises(DataError):
        render(_ctx(), _cfg(pattern="CON.{extension}_{technical_id}"))


def test_meta_name_appends_suffix() -> None:
    """The metadata sidecar name appends the configured suffix."""
    cfg = _cfg(meta_suffix=".meta.json")
    assert meta_name("PAYMENT_OUT_X_ABC123.csv", cfg) == \
        "PAYMENT_OUT_X_ABC123.csv.meta.json"
