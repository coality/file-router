"""E2E for filerouter-doctor: full-config diagnosis and unattended auto-repair.

Covers the spectrum: a fully-broken config (missing directories) is diagnosed,
auto-repaired WITHOUT any question, then re-diagnosed clean; plus the CLI entry
points (subcommand and standalone) and the gnupg key checks with a real keyring.
"""

from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

import pytest
import yaml

from filerouter.cli import commands
from filerouter.cli.doctor import ERROR, OK, Doctor, main


def _write(tmp_path: Path, data: dict) -> Path:
    """Persist a config dict to YAML and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _all_dirs(data: dict) -> list[Path]:
    """All directories the config references (base_folders + exchange + runtime)."""
    dirs = [Path(e["path"]) for e in data["base_folders"]]
    dirs += [Path(data["exchange"]["out"]), Path(data["exchange"]["in"]),
             Path(data["runtime"]["root"])]
    return dirs


def test_auto_repair_fixes_all_missing_dirs(config_dict: dict, tmp_path: Path) -> None:
    """Unattended mode creates every missing directory and ends clean."""
    data = copy.deepcopy(config_dict)
    cfg = _write(tmp_path, data)
    # Nothing exists yet -> several ERROR findings.
    assert any(f.level == ERROR for f in Doctor(cfg).diagnose())

    # Unattended repair: always-yes asker, silent output.
    code = Doctor(cfg, asker=lambda _p: True, out=lambda *_: None).run(apply_fixes=True)

    # Every directory now exists and the re-diagnosis is clean (exit code 0).
    assert all(d.exists() for d in _all_dirs(data))
    assert code == 0


def test_report_only_does_not_create_dirs(config_dict: dict, tmp_path: Path) -> None:
    """Without --fix, the doctor reports but changes nothing on disk."""
    data = copy.deepcopy(config_dict)
    cfg = _write(tmp_path, data)
    Doctor(cfg, out=lambda *_: None).run(apply_fixes=False)
    assert not any(d.exists() for d in _all_dirs(data))


def test_cli_main_returns_nonzero_on_errors(config_dict: dict, tmp_path: Path,
                                            capsys) -> None:
    """The standalone CLI returns a non-zero code when errors remain."""
    cfg = _write(tmp_path, copy.deepcopy(config_dict))
    code = main(["--config", str(cfg)])
    assert code == 1  # missing directories -> errors


def test_cli_auto_repair_returns_zero(config_dict: dict, tmp_path: Path) -> None:
    """The standalone CLI with --fix --yes repairs everything and returns 0."""
    data = copy.deepcopy(config_dict)
    cfg = _write(tmp_path, data)
    code = main(["--config", str(cfg), "--fix", "--yes"])
    assert code == 0
    assert all(d.exists() for d in _all_dirs(data))


def test_subcommand_doctor_dispatch(config_dict: dict, tmp_path: Path) -> None:
    """`filerouter doctor` dispatches to the same diagnostics."""
    data = copy.deepcopy(config_dict)
    cfg = _write(tmp_path, data)
    code = commands.main(["--config", str(cfg), "doctor", "--fix", "--yes"])
    assert code == 0
    assert all(d.exists() for d in _all_dirs(data))


def test_same_volume_detected_when_dirs_exist(config_dict: dict,
                                              tmp_path: Path) -> None:
    """When runtime and exchange exist on one volume, same_volume is OK."""
    data = copy.deepcopy(config_dict)
    for d in _all_dirs(data):
        d.mkdir(parents=True, exist_ok=True)
    findings = {f.check: f.level for f in Doctor(_write(tmp_path, data)).diagnose()}
    assert findings["same_volume"] == OK


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_permission_problems_listed_on_stdout(config_dict: dict,
                                              tmp_path: Path) -> None:
    """A directory with no rights is listed as a permission problem on output."""
    data = copy.deepcopy(config_dict)
    for d in _all_dirs(data):
        d.mkdir(parents=True, exist_ok=True)
    locked = Path(data["base_folders"][0]["path"])
    os.chmod(locked, 0o000)  # remove all rights
    try:
        lines: list[str] = []
        Doctor(_write(tmp_path, data), out=lines.append).run(apply_fixes=False)
        joined = "\n".join(lines)
        # The permission problem is explicitly reported on stdout with the path.
        assert "insufficient permissions" in joined
        assert str(locked) in joined
    finally:
        os.chmod(locked, 0o700)  # restore so tmp cleanup works


@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")
def test_gnupg_keys_present_is_ok(config_dict: dict, tmp_path: Path) -> None:
    """With a real key in the keyring, the crypto check passes."""
    import gnupg

    home = str(tmp_path / "gnupg")
    os.makedirs(home, exist_ok=True)
    gpg = gnupg.GPG(gnupghome=home)
    params = gpg.gen_key_input(key_type="RSA", key_length=2048,
                               name_real="Doc", name_email="doc@test.local",
                               no_protection=True)
    fpr = str(gpg.gen_key(params).fingerprint)

    data = copy.deepcopy(config_dict)
    for d in _all_dirs(data):
        d.mkdir(parents=True, exist_ok=True)
    data["encryption"] = {
        "backend": "gnupg", "gnupg_home": home, "signing_key_id": fpr,
        "rules": [{"base_folder_alias": "SAP_FR", "path_pattern": "**",
                   "enabled": True, "recipient_key_ids": [fpr]}],
    }
    findings = {f.check: f.level for f in Doctor(_write(tmp_path, data)).diagnose()}
    assert findings["crypto"] == OK
