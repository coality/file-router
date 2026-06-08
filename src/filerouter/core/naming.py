"""Technical-name rendering engine.

Renders the configurable technical filename from a placeholder pattern, enforces
max length and a portable charset, and guarantees a unique technical_id. The
original name is NOT derived from the technical name; it is restored from
metadata. See docs/04-data-formats.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from filerouter.core.errors import DataError
from filerouter.core.models import Direction

# Characters forbidden on Windows plus control chars; used by the portable charset.
_PORTABLE_RE = re.compile(r"[^A-Za-z0-9_.\-]")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class NamingConfig:
    """Naming configuration (subset of the YAML ``naming`` section)."""

    pattern: str
    timestamp_format: str = "%Y%m%dT%H%M%S"
    max_length: int = 120
    charset: str = "portable"
    meta_suffix: str = ".meta.json"


@dataclass(frozen=True)
class NamingContext:
    """Values available to the naming pattern."""

    flow: str
    direction: Direction
    timestamp: str
    technical_id: str
    extension: str
    base_folder_alias: str
    source_site: str = ""
    target_site: str = ""


def validate_pattern(pattern: str) -> None:
    """Ensure the pattern contains the mandatory unique id placeholder."""
    if "{technical_id}" not in pattern:
        raise DataError("naming.pattern must contain {technical_id}")


def render(ctx: NamingContext, cfg: NamingConfig) -> str:
    """Render the technical filename, enforcing charset and max length."""
    validate_pattern(cfg.pattern)
    values = {
        "flow": ctx.flow,
        "direction": ctx.direction.value,
        "timestamp": ctx.timestamp,
        "technical_id": ctx.technical_id,
        "extension": ctx.extension,
        "base_folder_alias": ctx.base_folder_alias,
        "source_site": ctx.source_site,
        "target_site": ctx.target_site,
    }
    try:
        name = cfg.pattern.format(**values)
    except KeyError as exc:  # unknown placeholder in pattern
        raise DataError(f"unknown naming placeholder: {exc}") from exc

    if cfg.charset == "portable":
        _assert_portable(name)
    if len(name) > cfg.max_length:
        raise DataError(
            f"technical name exceeds max_length={cfg.max_length}: {len(name)} chars"
        )
    return name


def meta_name(technical_filename: str, cfg: NamingConfig) -> str:
    """Return the metadata sidecar filename for a technical filename."""
    return technical_filename + cfg.meta_suffix


def _assert_portable(name: str) -> None:
    if _PORTABLE_RE.search(name):
        raise DataError(f"technical name contains non-portable characters: {name!r}")
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise DataError(f"technical name uses a reserved Windows name: {name!r}")
