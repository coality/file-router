"""E2E with a REAL OpenPGP backend (GnuPG).

Generates an ephemeral keyring, then exercises the full encrypt+sign -> verify+
decrypt round trip, plus the security rejections (tampered payload, unauthorized
signer, required-but-missing signature). Skipped automatically if gpg is absent.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from filerouter.config.loader import load_config_dict
from filerouter.core.inbound import InboundProcessor
from filerouter.core.orchestrator import Orchestrator
from filerouter.service.runner import build_context
from tests.conftest import FrozenClock, write_file

pytestmark = pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")


def _generate_key(gnupg_home: str) -> str:
    """Create an ephemeral, passphrase-less key and return its fingerprint."""
    import gnupg

    gpg = gnupg.GPG(gnupghome=gnupg_home)
    params = gpg.gen_key_input(
        key_type="RSA", key_length=2048,
        name_real="FileRouter Test", name_email="test@filerouter.local",
        no_protection=True,
    )
    return str(gpg.gen_key(params).fingerprint)


def _gnupg_context(config_dict: dict, tmp_path: Path, *, sign: bool,
                   allowed_ok: bool):
    """Wire a context using the real GnuPG backend over a fresh keyring."""
    home = str(tmp_path / "gnupg")
    os.makedirs(home, exist_ok=True)
    fpr = _generate_key(home)
    enc: dict = {
        "backend": "gnupg",
        "gnupg_home": home,
        "require_signature_inbound": True,
        "allowed_signers": [fpr] if allowed_ok else ["0xNOTALLOWED"],
        "rules": [{"base_folder_alias": "SAP_FR", "path_pattern": "**",
                   "enabled": True, "recipient_key_ids": [fpr]}],
    }
    if sign:
        enc["signing_key_id"] = fpr  # omit entirely when not signing
    config_dict["encryption"] = enc
    ctx = build_context(load_config_dict(config_dict), quiet=True)
    object.__setattr__(ctx, "clock", FrozenClock())
    object.__setattr__(ctx.audit, "_clock", ctx.clock)
    return ctx, fpr


def _transport_one(ctx) -> Path:
    """Move the single published pair from exchange_out to exchange_in.

    Returns the payload path now sitting in exchange_in.
    """
    out = ctx.layout.exchange_out
    payload = next(p for p in out.iterdir() if not p.name.endswith(".meta.json"))
    meta = payload.with_name(payload.name + ".meta.json")
    dst = ctx.layout.exchange_in / payload.name
    payload.replace(dst)
    meta.replace(ctx.layout.exchange_in / meta.name)
    return dst


def test_gnupg_encrypt_sign_roundtrip(config_dict: dict, tmp_path: Path) -> None:
    """A file is really encrypted+signed, then verified+decrypted, byte-identical."""
    ctx, _fpr = _gnupg_context(config_dict, tmp_path, sign=True, allowed_ok=True)
    content = b"top-secret;1;2;3\n"
    src = write_file(tmp_path / "business" / "sap_fr" / "confidential/x/y/secret.csv",
                     content)

    orch = Orchestrator(ctx)
    out_report = orch.scan_once()
    assert out_report.outbound_published == 1

    # The on-wire payload must NOT be the clear bytes (it is OpenPGP-encrypted).
    payload = next(p for p in ctx.layout.exchange_out.iterdir()
                   if not p.name.endswith(".meta.json"))
    assert payload.read_bytes() != content

    _transport_one(ctx)
    in_report = orch.scan_once()
    assert in_report.inbound_delivered == 1
    assert src.read_bytes() == content  # restored bit-for-bit


def test_gnupg_tampered_payload_quarantined(config_dict: dict, tmp_path: Path) -> None:
    """Corrupting the encrypted payload fails the payload-hash check."""
    ctx, _ = _gnupg_context(config_dict, tmp_path, sign=True, allowed_ok=True)
    write_file(tmp_path / "business" / "sap_fr" / "a/b.csv", b"data\n")
    Orchestrator(ctx).scan_once()
    payload = _transport_one(ctx)
    payload.write_bytes(payload.read_bytes() + b"corruption")

    outcome = InboundProcessor(ctx).process(payload)
    assert outcome.status == "quarantined"


def test_gnupg_unauthorized_signer_quarantined(config_dict: dict,
                                               tmp_path: Path) -> None:
    """A valid signature from a non-whitelisted signer is rejected."""
    # Signed with the real key, but allowed_signers points elsewhere.
    ctx, _ = _gnupg_context(config_dict, tmp_path, sign=True, allowed_ok=False)
    write_file(tmp_path / "business" / "sap_fr" / "a/b.csv", b"data\n")
    Orchestrator(ctx).scan_once()
    payload = _transport_one(ctx)

    outcome = InboundProcessor(ctx).process(payload)
    assert outcome.status == "quarantined"


def test_gnupg_unsigned_but_required_quarantined(config_dict: dict,
                                                 tmp_path: Path) -> None:
    """An encrypted-but-unsigned payload is rejected when signatures are required."""
    ctx, _ = _gnupg_context(config_dict, tmp_path, sign=False, allowed_ok=True)
    write_file(tmp_path / "business" / "sap_fr" / "a/b.csv", b"data\n")
    Orchestrator(ctx).scan_once()
    payload = _transport_one(ctx)

    outcome = InboundProcessor(ctx).process(payload)
    assert outcome.status == "quarantined"
