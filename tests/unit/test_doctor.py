"""Unit tests for filerouter-doctor (diagnostics + guided fixes)."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from filerouter.cli.doctor import ERROR, OK, Doctor


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a config dict to a YAML file and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _levels(findings) -> dict[str, str]:
    """Index finding levels by check name for easy assertions."""
    return {f.check: f.level for f in findings}


def test_healthy_config_has_no_errors(config_dict: dict, tmp_path: Path) -> None:
    """A valid config with existing directories yields no ERROR findings."""
    data = copy.deepcopy(config_dict)
    # Create all referenced directories so filesystem checks pass.
    for entry in data["base_folders"]:
        Path(entry["path"]).mkdir(parents=True, exist_ok=True)
    for p in (data["exchange"]["out"], data["exchange"]["in"],
              data["runtime"]["root"]):
        Path(p).mkdir(parents=True, exist_ok=True)

    findings = Doctor(_write_config(tmp_path, data)).diagnose()
    assert not [f for f in findings if f.level == ERROR]


def test_detects_invalid_schema(config_dict: dict, tmp_path: Path) -> None:
    """An invalid backend is reported as a schema ERROR."""
    data = copy.deepcopy(config_dict)
    data["encryption"]["backend"] = "rot13"
    findings = Doctor(_write_config(tmp_path, data)).diagnose()
    assert _levels(findings)["schema"] == ERROR


def test_detects_duplicate_aliases(config_dict: dict, tmp_path: Path) -> None:
    """Duplicate base_folder aliases are reported by the semantics check."""
    data = copy.deepcopy(config_dict)
    data["base_folders"].append({"alias": "SAP_FR", "path": str(tmp_path / "dup")})
    findings = Doctor(_write_config(tmp_path, data)).diagnose()
    assert _levels(findings)["semantics"] == ERROR


def test_detects_missing_directories(config_dict: dict, tmp_path: Path) -> None:
    """Missing base_folder directories are flagged as errors."""
    findings = Doctor(_write_config(tmp_path, config_dict)).diagnose()
    # base_folders do not exist yet -> at least one ERROR among them.
    assert any(f.check.startswith("base_folder:") and f.level == ERROR
               for f in findings)


def test_detects_unknown_rule_alias(config_dict: dict, tmp_path: Path) -> None:
    """An encryption rule on an unknown alias is reported."""
    data = copy.deepcopy(config_dict)
    data["encryption"]["rules"] = [
        {"base_folder_alias": "DOES_NOT_EXIST", "path_pattern": "**",
         "enabled": True, "recipient_key_ids": ["0xKEY"]},
    ]
    findings = Doctor(_write_config(tmp_path, data)).diagnose()
    assert any(f.check == "encryption.rule" and f.level == ERROR for f in findings)


def test_interactive_fix_creates_directory(config_dict: dict, tmp_path: Path) -> None:
    """The guided fix creates a missing directory when the operator agrees."""
    data = copy.deepcopy(config_dict)
    missing = Path(data["base_folders"][0]["path"])
    assert not missing.exists()

    # Scripted asker that always says yes; silent output.
    doctor = Doctor(_write_config(tmp_path, data),
                    asker=lambda _prompt: True, out=lambda *_: None)
    doctor.run(apply_fixes=True)
    assert missing.exists()  # created by the guided fix


def test_gnupg_missing_keys_reported(config_dict: dict, tmp_path: Path) -> None:
    """A gnupg backend pointing at an empty/missing keyring is reported."""
    data = copy.deepcopy(config_dict)
    data["encryption"] = {
        "backend": "gnupg",
        "gnupg_home": str(tmp_path / "no_such_home"),
        "rules": [],
    }
    findings = Doctor(_write_config(tmp_path, data)).diagnose()
    assert any(f.check == "crypto" and f.level == ERROR for f in findings)
