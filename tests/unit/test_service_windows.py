"""Unit tests for the multi-instance Windows service helpers.

Only the pure naming/resolution logic is tested here; it is OS-independent and
does not import pywin32.
"""

from __future__ import annotations

import pytest

from filerouter.service.windows import (
    config_env_var,
    instance_from_service_name,
    resolve_config_path,
    service_display_name,
    service_name,
)


def test_service_name_default_and_instance() -> None:
    """The base name is used without an instance; suffixed otherwise."""
    assert service_name(None) == "FileRouter"
    assert service_name("siteA") == "FileRouter_siteA"


def test_display_name() -> None:
    """The display name mirrors the instance for clarity in the SCM."""
    assert service_display_name(None) == "FileRouter"
    assert service_display_name("siteA") == "FileRouter (siteA)"


def test_config_env_var() -> None:
    """The per-instance env var is upper-cased and suffixed."""
    assert config_env_var(None) == "FILEROUTER_CONFIG"
    assert config_env_var("siteA") == "FILEROUTER_CONFIG_SITEA"


def test_instance_from_service_name() -> None:
    """The instance name is recovered from a service name (None for base)."""
    assert instance_from_service_name("FileRouter") is None
    assert instance_from_service_name("FileRouter_siteB") == "siteB"


def test_resolve_uses_per_instance_var_first() -> None:
    """Resolution prefers the per-instance variable over the default."""
    env = {"FILEROUTER_CONFIG": "C:/default.yaml",
           "FILEROUTER_CONFIG_SITEA": "C:/siteA.yaml"}
    assert resolve_config_path("FileRouter_siteA", env) == "C:/siteA.yaml"


def test_resolve_falls_back_to_default() -> None:
    """Resolution falls back to the default variable when no per-instance one."""
    env = {"FILEROUTER_CONFIG": "C:/default.yaml"}
    assert resolve_config_path("FileRouter_siteA", env) == "C:/default.yaml"


def test_resolve_raises_when_unset() -> None:
    """A clear error is raised when no config variable is set."""
    with pytest.raises(RuntimeError):
        resolve_config_path("FileRouter_siteA", {})
