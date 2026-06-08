"""Metadata serialization, validation and IO.

Validation uses the JSON Schema bundled in the package (config/_schemas). See
docs/fr/04-data-formats.md.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from filerouter.core.errors import DataError
from filerouter.core.models import Metadata
from filerouter.version import SUPPORTED_METADATA_SCHEMA_VERSIONS


@lru_cache(maxsize=None)
def _schema() -> dict[str, Any]:
    text = resources.files("filerouter.config._schemas").joinpath("metadata.schema.json").read_text(
        encoding="utf-8"
    )
    return json.loads(text)


def validate_dict(data: dict[str, Any]) -> None:
    """Validate a metadata dict against the JSON Schema and forward-tolerance rules."""
    try:
        import jsonschema  # noqa: PLC0415 - optional dependency, lazy import
    except ImportError:  # pragma: no cover
        _validate_minimal(data)
    else:
        try:
            jsonschema.validate(data, _schema())
        except jsonschema.ValidationError as exc:
            raise DataError(f"invalid metadata: {exc.message}") from exc
    version = str(data.get("schema_version", ""))
    if version not in SUPPORTED_METADATA_SCHEMA_VERSIONS:
        raise DataError(f"unsupported metadata schema_version: {version!r}")


def _validate_minimal(data: dict[str, Any]) -> None:
    """Fallback validation when jsonschema is unavailable."""
    required = (
        "schema_version", "technical_id", "direction", "source_site", "target_site",
        "base_folder_alias", "relative_path", "original_filename", "encrypted",
        "clear_file_hash", "payload_file_hash", "creation_date",
    )
    missing = [k for k in required if k not in data]
    if missing:
        raise DataError(f"metadata missing required fields: {missing}")
    if data.get("encrypted") and "encryption" not in data:
        raise DataError("encrypted metadata must include 'encryption'")
    # Security: technical_id is used to build filesystem paths; reject anything
    # that is not a safe single component (no separators, no '..') even on the
    # fallback path where jsonschema is unavailable. Mirrors the schema pattern.
    import re  # noqa: PLC0415

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(data.get("technical_id", ""))):
        raise DataError("technical_id contains illegal characters")
    rel = str(data.get("relative_path", ""))
    if rel.startswith("/") or "\\" in rel or ".." in rel.split("/"):
        raise DataError("relative_path is not a safe relative POSIX path")


def dumps(meta: Metadata) -> bytes:
    """Serialize and validate metadata to canonical JSON bytes."""
    data = meta.to_dict()
    validate_dict(data)
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")


def loads(raw: bytes | str) -> Metadata:
    """Parse and validate metadata from JSON bytes/text."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise DataError(f"corrupt metadata JSON: {exc}") from exc
    validate_dict(data)
    return Metadata.from_dict(data)


def load_file(path: Path) -> Metadata:
    """Load and validate metadata from a file."""
    return loads(path.read_text(encoding="utf-8"))
