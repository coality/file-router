"""Unit tests for configuration loading and validation."""

from __future__ import annotations

import copy

import pytest

from filerouter.config.loader import load_config_dict
from filerouter.core.errors import ConfigError


def test_valid_config_builds(config_dict: dict) -> None:
    """A well-formed config builds a typed Config with the expected pieces."""
    cfg = load_config_dict(config_dict)
    assert cfg.instance.site == "PARIS"
    assert len(cfg.base_folders) == 3
    assert cfg.flow_for("SAP_FR") == "SAPFR"
    assert cfg.routing["PAYMENT"] == "FRANKFURT"


def test_duplicate_aliases_rejected(config_dict: dict) -> None:
    """Duplicate base_folder aliases fail semantic validation."""
    data = copy.deepcopy(config_dict)
    data["base_folders"].append({"alias": "SAP_FR", "path": "/tmp/dup"})
    with pytest.raises(ConfigError):
        load_config_dict(data)


def test_missing_technical_id_placeholder_rejected(config_dict: dict) -> None:
    """A naming pattern lacking {technical_id} is rejected."""
    data = copy.deepcopy(config_dict)
    data["naming"]["pattern"] = "{flow}_{timestamp}.{extension}"
    with pytest.raises(ConfigError):
        load_config_dict(data)


def test_invalid_backend_rejected(config_dict: dict) -> None:
    """An unknown encryption backend fails schema validation."""
    data = copy.deepcopy(config_dict)
    data["encryption"]["backend"] = "rot13"
    with pytest.raises(ConfigError):
        load_config_dict(data)


def test_missing_required_section_rejected(config_dict: dict) -> None:
    """Removing a required section fails schema validation."""
    data = copy.deepcopy(config_dict)
    del data["base_folders"]
    with pytest.raises(ConfigError):
        load_config_dict(data)


def test_base_folder_lookup_by_alias(config_dict: dict) -> None:
    """base_folder_by_alias resolves a known alias and None otherwise."""
    cfg = load_config_dict(config_dict)
    assert cfg.base_folder_by_alias("PAYMENT") is not None
    assert cfg.base_folder_by_alias("UNKNOWN") is None
