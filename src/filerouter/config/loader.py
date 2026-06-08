"""YAML configuration loading.

Loads the YAML safely, validates it, and builds the typed Config. Kept tiny:
read -> parse -> validate -> build.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from filerouter.config.model import Config, build_config
from filerouter.config.schema import validate
from filerouter.core.errors import ConfigError


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and safely parse a YAML file into a dict.

    Uses ``yaml.safe_load`` to avoid arbitrary object construction (security).
    """
    try:
        import yaml  # noqa: PLC0415 - dependency, lazy import for clear errors
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("PyYAML is not installed") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    return data


def load_config(path: str | Path) -> Config:
    """Load, validate and build the typed configuration from a YAML file."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    data = _read_yaml(p)
    validate(data)  # fail-fast: raises ConfigError on any problem
    return build_config(data)


def load_config_dict(data: dict[str, Any]) -> Config:
    """Validate and build a Config from an already-parsed dict (test helper)."""
    validate(data)
    return build_config(data)
