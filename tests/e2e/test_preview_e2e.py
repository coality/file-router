"""E2E for the ``preview`` CLI command.

Confirms the read-only diagnostic correctly classifies business files as WATCHED
or skipped (with the responsible rule), covering extension filtering, directory
exclusion (root and nested) and case-insensitive matching.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from filerouter.cli.commands import cmd_preview


def _write_cfg(tmp_path: Path, data: dict) -> str:
    """Serialize a config dict to a YAML file; return its path."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def _seed(base: Path) -> None:
    """Create a varied tree under one base_folder."""
    for rel in ("data.csv", "REPORT.CSV", "notes.txt", "archive/old.csv",
                "clients/archive/2025.csv", "clients/2026/sales.xml",
                "data/myarchive/keep.csv"):
        f = base / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")


def test_preview_classifies_watched_and_skipped(make_config, tmp_path, capsys) -> None:
    """Only *.csv/*.xml are watched; an 'archive' dir is ignored at any depth."""
    def mutate(cfg: dict) -> None:
        cfg["inclusion"] = {"patterns": ["*.csv", "*.xml"]}
        cfg["exclusion"] = {"patterns": ["archive/**", "*/archive/*"]}

    data = make_config(mutate=mutate)
    _seed(Path(data["base_folders"][0]["path"]))  # SAP_FR

    args = argparse.Namespace(config=_write_cfg(tmp_path, data), watched_only=False)
    assert cmd_preview(args) == 0
    out = capsys.readouterr().out

    # Watched: csv/xml at any depth, incl. uppercase extension (case-insensitive).
    assert "[WATCHED] data.csv" in out
    assert "[WATCHED] REPORT.CSV" in out
    assert "clients/2026/sales.xml" in out
    assert "data/myarchive/keep.csv" in out          # 'myarchive' != 'archive'

    # Skipped with the responsible rule.
    assert "archive/old.csv" in out and "archive/**" in out
    assert "clients/archive/2025.csv" in out and "*/archive/*" in out
    assert "notes.txt" in out and "no inclusion pattern matched" in out

    assert "4 watched" in out  # data.csv, REPORT.CSV, sales.xml, keep.csv


def test_preview_watched_only_hides_skipped(make_config, tmp_path, capsys) -> None:
    """--watched-only suppresses the skipped lines but still counts them."""
    def mutate(cfg: dict) -> None:
        cfg["inclusion"] = {"patterns": ["*.csv"]}

    data = make_config(mutate=mutate)
    base = Path(data["base_folders"][0]["path"])
    (base / "keep.csv").parent.mkdir(parents=True, exist_ok=True)
    (base / "keep.csv").write_bytes(b"x")
    (base / "drop.txt").write_bytes(b"x")

    args = argparse.Namespace(config=_write_cfg(tmp_path, data), watched_only=True)
    assert cmd_preview(args) == 0
    out = capsys.readouterr().out
    assert "[WATCHED] keep.csv" in out
    assert "drop.txt" not in out          # skipped line hidden
    assert "1 watched" in out and "1 skipped" in out
