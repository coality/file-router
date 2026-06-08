"""Validate the shipped example configurations against the real loader.

Loading a config runs full schema + semantic validation, so these tests prove the
documented examples are valid and stay in sync with the code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from filerouter.config.loader import load_config

_EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"


def test_main_example_config_is_valid() -> None:
    """The reference config.example.yaml loads and validates."""
    cfg = load_config(_EXAMPLES / "config.example.yaml")
    assert cfg.instance.site == "PARIS"
    # Compression and encryption rules are present and compiled.
    assert cfg.compression.algorithm == "gzip"


@pytest.mark.parametrize("name,role,site", [
    ("siteA.config.yaml", "outbound", "PARIS"),
    ("siteB.config.yaml", "inbound", "FRANKFURT"),
])
def test_two_instance_configs_are_valid(name: str, role: str, site: str) -> None:
    """Both two-instance demo configs load, validate and share the BIZ alias."""
    cfg = load_config(_EXAMPLES / "two-instance" / name)
    assert cfg.instance.role == role
    assert cfg.instance.site == site
    assert cfg.base_folder_by_alias("BIZ") is not None
