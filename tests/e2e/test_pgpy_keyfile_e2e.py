"""E2E for the file-based PGPy backend + the support transfer journal.

Generates a passphrase-protected key, writes private/public/passphrase FILES
(no key material in the config), then runs a full encrypt+sign+gzip round trip
and checks the human-readable transfer journal records the right flags, signer
and clear-text hash.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pgpy = pytest.importorskip("pgpy")

from filerouter.config.loader import load_config_dict  # noqa: E402
from filerouter.core.orchestrator import Orchestrator  # noqa: E402
from filerouter.service.runner import build_context  # noqa: E402

PASSPHRASE = "S3cret-Pass!"
CONTENT = b"id;amount\n1;100\n2;200\n"


def _generate_key(keys: Path) -> None:
    """Write a peer public key and a passphrase-protected private key to files."""
    from pgpy.constants import (CompressionAlgorithm, HashAlgorithm, KeyFlags,
                                PubKeyAlgorithm, SymmetricKeyAlgorithm)

    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    uid = pgpy.PGPUID.new("FileRouter Test", email="test@local")
    key.add_uid(uid, usage={KeyFlags.Sign, KeyFlags.EncryptCommunications,
                            KeyFlags.EncryptStorage},
                hashes=[HashAlgorithm.SHA256], ciphers=[SymmetricKeyAlgorithm.AES256],
                compression=[CompressionAlgorithm.ZLIB])
    (keys / "pub.asc").write_text(str(key.pubkey))
    key.protect(PASSPHRASE, SymmetricKeyAlgorithm.AES256, HashAlgorithm.SHA256)
    (keys / "priv.asc").write_text(str(key))


def _config(root: Path, keys: Path) -> dict:
    biz = root / "business" / "PAY"
    return {
        "instance": {"site": "PARIS", "role": "both", "workers": 1},
        "base_folders": [{"alias": "PAY", "path": str(biz)}],
        "mappings": {"flows": {"PAY": "PAYMENT"}, "routing": {"PAY": "FRANKFURT"}},
        "exchange": {"out": str(root / "exchange_out"), "in": str(root / "exchange_in")},
        "runtime": {"root": str(root / "runtime")},
        "naming": {"pattern": "{flow}_{direction}_{timestamp}_{technical_id}.{extension}",
                   "timestamp_format": "%Y%m%dT%H%M%S", "technical_id_strategy": "ulid",
                   "meta_suffix": ".meta.json"},
        "hashing": {"algorithm": "SHA-256", "chunk_size_bytes": 65536,
                    "verify_inbound": True},
        "encryption": {"backend": "pgpy", "require_signature_inbound": True,
                       "private_key_file": str(keys / "priv.asc"),
                       "public_key_file": str(keys / "pub.asc"),
                       "passphrase_file": str(keys / "pass.txt"),
                       "signing_key_id": "test-signer",
                       "rules": [{"base_folder_alias": "PAY", "path_pattern": "**",
                                  "enabled": True}]},
        "compression": {"algorithm": "gzip", "level": 6,
                        "rules": [{"base_folder_alias": "PAY", "path_pattern": "**",
                                   "enabled": True}]},
        "inclusion": {"patterns": ["*.csv"]}, "exclusion": {"patterns": []},
        "duplicates": {"outbound_policy": "skip", "inbound_policy": "skip"},
        "archival": {"source_policy": "archive", "archive_layout": "%Y/%m/%d"},
        "retention": {"archive_days": 30, "audit_days": 365, "logs_days": 90,
                      "error_days": 0},
        "scanning": {"interval_seconds": 1, "stability_checks": 1,
                     "stability_interval_seconds": 0.1, "pair_grace_period_seconds": 5},
        "locking": {"lock_ttl_seconds": 300, "heartbeat_interval_seconds": 30},
        "logging": {"format": "jsonl", "streams": {}},
    }


def test_pgpy_keyfile_roundtrip_and_journal(tmp_path: Path) -> None:
    """Encrypt+sign+gzip out, decrypt+verify+decompress in; journal records flags."""
    keys = tmp_path / "keys"
    keys.mkdir()
    _generate_key(keys)
    (keys / "pass.txt").write_text(PASSPHRASE)
    biz = tmp_path / "business" / "PAY"
    biz.mkdir(parents=True)
    (biz / "data.csv").write_bytes(CONTENT)

    ctx = build_context(load_config_dict(_config(tmp_path, keys)), quiet=True)
    orch = Orchestrator(ctx)

    # Outbound: produces an encrypted (binary OpenPGP) payload + a SIGNED metadata.
    assert orch.scan_once().outbound_published == 1
    out = tmp_path / "exchange_out"
    payload = next(p for p in out.iterdir()
                   if not (p.name.endswith(".meta.json") or p.name.endswith(".sig")))
    assert payload.read_bytes()[:1] == b"\xc1"          # OpenPGP packet, not clear
    assert payload.read_bytes() != CONTENT
    # the detached metadata signature sidecar is published alongside
    assert (out / (payload.name + ".meta.json.sig")).exists()

    # Transport then inbound: decrypt + verify signature + decompress + deliver.
    for f in list(out.iterdir()):
        shutil.move(str(f), str(tmp_path / "exchange_in" / f.name))
    assert orch.scan_once().inbound_delivered == 1
    assert (biz / "data.csv").read_bytes() == CONTENT     # round-trip integrity

    # The support journal records both legs with flags, signer and clear hash.
    journal = (tmp_path / "logs" / "transfers.log").read_text(encoding="utf-8")
    assert "OUT  PAY" in journal and "IN   PAY" in journal
    assert journal.count("gzip+encrypted+signed") == 2
    assert "signer=test-signer" in journal
    assert "sha256(clear)=" in journal


def test_pgpy_tampered_metadata_is_rejected(tmp_path: Path) -> None:
    """Altering a routing field after signing breaks the metadata signature.

    Proves the detached metadata signature actually authenticates the routing
    fields: a man-in-the-middle who rewrites original_filename (to redirect the
    delivery) but cannot re-sign is quarantined, not delivered.
    """
    keys = tmp_path / "keys"
    keys.mkdir()
    _generate_key(keys)
    (keys / "pass.txt").write_text(PASSPHRASE)
    biz = tmp_path / "business" / "PAY"
    biz.mkdir(parents=True)
    (biz / "data.csv").write_bytes(CONTENT)

    ctx = build_context(load_config_dict(_config(tmp_path, keys)), quiet=True)
    orch = Orchestrator(ctx)
    assert orch.scan_once().outbound_published == 1

    out = tmp_path / "exchange_out"
    inbox = tmp_path / "exchange_in"
    payload = next(p for p in out.iterdir()
                   if not (p.name.endswith(".meta.json") or p.name.endswith(".sig")))
    meta_file = out / (payload.name + ".meta.json")
    # TAMPER: redirect the delivery by rewriting a routing field, keep the OLD sig.
    import json as _json
    meta = _json.loads(meta_file.read_text(encoding="utf-8"))
    meta["original_filename"] = "hijacked.csv"
    meta_file.write_text(_json.dumps(meta, indent=2), encoding="utf-8")

    for f in list(out.iterdir()):
        shutil.move(str(f), str(inbox / f.name))
    report = orch.scan_once()
    assert report.inbound_delivered == 0
    assert report.inbound_quarantined == 1
    assert not (biz / "hijacked.csv").exists()      # the redirect did NOT happen
