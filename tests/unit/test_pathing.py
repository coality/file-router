"""Unit tests for base_folder identification and relative-path logic."""

from __future__ import annotations

from pathlib import PurePath, PurePosixPath

import pytest

from filerouter.core.errors import ConfigError, DataError
from filerouter.core.pathing import (
    BaseFolder,
    business_target,
    identify_base_folder,
    relative_path,
)

BASES = [
    BaseFolder("SAP_FR", PurePath("/data/sap/fr")),
    BaseFolder("SAP", PurePath("/data/sap")),  # shorter prefix, must not win
    BaseFolder("PAYMENT", PurePath("/payments")),
]


def test_longest_prefix_match_wins() -> None:
    """The most specific base_folder owns the file, not a shorter prefix."""
    p = PurePath("/data/sap/fr/clients/a/b/file.csv")
    assert identify_base_folder(p, BASES).alias == "SAP_FR"


def test_identify_unknown_path_raises() -> None:
    """A path under no base_folder raises ConfigError."""
    with pytest.raises(ConfigError):
        identify_base_folder(PurePath("/elsewhere/x.csv"), BASES)


def test_relative_path_is_posix_and_deep() -> None:
    """Relative path is the POSIX directory path, unlimited depth."""
    base = BaseFolder("SAP_FR", PurePath("/data/sap/fr"))
    p = PurePath("/data/sap/fr/a/b/c/d/e/file.csv")
    assert relative_path(p, base) == "a/b/c/d/e"


def test_relative_path_root_level_is_empty() -> None:
    """A file at the base root has an empty relative path."""
    base = BaseFolder("SAP_FR", PurePath("/data/sap/fr"))
    assert relative_path(PurePath("/data/sap/fr/file.csv"), base) == ""


def test_business_target_rebuilds_path() -> None:
    """The business target is base + relative dir + original filename."""
    target = business_target(PurePath("/imports/sapfr"), "a/b/c", "file.csv")
    assert target == PurePath("/imports/sapfr/a/b/c/file.csv")


def test_business_target_rejects_absolute_relative() -> None:
    """An absolute relative_path is rejected (path-injection guard)."""
    with pytest.raises(DataError):
        business_target(PurePath("/base"), "/etc/passwd", "x")


def test_business_target_rejects_traversal() -> None:
    """A '..' traversal in relative_path is rejected."""
    with pytest.raises(DataError):
        business_target(PurePath("/base"), "a/../../etc", "x")


def test_business_target_empty_relative() -> None:
    """An empty relative dir places the file at the base root."""
    assert business_target(PurePath("/base"), "", "x.csv") == PurePath("/base/x.csv")
