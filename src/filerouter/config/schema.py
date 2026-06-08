"""Configuration validation: JSON Schema + semantic checks.

Two layers: (1) structural validation against the bundled JSON Schema, then
(2) semantic checks that the schema cannot express (unique aliases, mandatory
naming placeholder, same-volume runtime/exchange). Each check is a tiny helper.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from filerouter.core.errors import ConfigError


@lru_cache(maxsize=None)
def _config_schema() -> dict[str, Any]:
    """Load and cache the bundled config JSON Schema."""
    text = resources.files("filerouter.config._schemas").joinpath(
        "config.schema.json"
    ).read_text(encoding="utf-8")
    return json.loads(text)


def validate_structure(data: dict[str, Any]) -> None:
    """Validate the config dict against the JSON Schema (structural layer)."""
    try:
        import jsonschema  # noqa: PLC0415 - optional dependency, lazy import
    except ImportError:  # pragma: no cover
        return
    try:
        jsonschema.validate(data, _config_schema())
    except jsonschema.ValidationError as exc:
        raise ConfigError(f"invalid config: {exc.message}") from exc


def validate_semantics(data: dict[str, Any]) -> None:
    """Run all semantic checks the JSON Schema cannot express."""
    _check_unique_aliases(data)
    _check_naming_placeholder(data)
    _check_same_volume(data)


def _check_unique_aliases(data: dict[str, Any]) -> None:
    """Reject duplicate base_folder aliases (each file maps to exactly one)."""
    aliases = [bf["alias"] for bf in data.get("base_folders", [])]
    duplicates = {a for a in aliases if aliases.count(a) > 1}
    if duplicates:
        raise ConfigError(f"duplicate base_folder aliases: {sorted(duplicates)}")


def _check_naming_placeholder(data: dict[str, Any]) -> None:
    """Ensure the naming pattern carries the mandatory unique id placeholder."""
    pattern = data.get("naming", {}).get("pattern", "")
    if "{technical_id}" not in pattern:
        raise ConfigError("naming.pattern must contain {technical_id}")


def _check_same_volume(data: dict[str, Any]) -> None:
    """Warn-by-erroring if runtime and exchange roots are obviously different.

    Atomic publish requires runtime/ and the exchange dirs to share a volume.
    We can only do a best-effort check on the drive/anchor here; a deeper check
    runs at startup once the directories exist.
    """
    runtime_root = data.get("runtime", {}).get("root")
    out = data.get("exchange", {}).get("out")
    if not runtime_root or not out:
        return
    if Path(runtime_root).anchor and Path(out).anchor:
        if Path(runtime_root).anchor != Path(out).anchor:
            raise ConfigError(
                "runtime.root and exchange.out must share the same volume/anchor"
            )


def validate(data: dict[str, Any]) -> None:
    """Full validation entry point: structure then semantics."""
    validate_structure(data)
    validate_semantics(data)
