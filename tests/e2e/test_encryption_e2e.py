"""E2E: encryption rule path (payload flagged encrypted, decrypt on inbound).

Uses the noop backend so the test runs without a gpg keyring, while still
exercising the full encrypt->metadata->decrypt->verify code path and the
``encrypted`` metadata invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

from filerouter.config.loader import load_config_dict
from filerouter.core.orchestrator import Orchestrator
from filerouter.service.runner import build_context
from tests.conftest import FrozenClock, write_file


def _ctx_with_rule(config_dict: dict):
    """Wire a context whose PAYMENT base_folder encrypts confidential/**."""
    config_dict["encryption"]["rules"] = [
        {"base_folder_alias": "PAYMENT", "path_pattern": "confidential/**",
         "enabled": True, "recipient_key_ids": ["0xDEADBEEF"]},
    ]
    ctx = build_context(load_config_dict(config_dict), quiet=True)
    object.__setattr__(ctx, "clock", FrozenClock())
    object.__setattr__(ctx.audit, "_clock", ctx.clock)
    return ctx


def test_encrypted_flag_and_roundtrip(config_dict: dict, tmp_path: Path) -> None:
    """A confidential file is marked encrypted and still rebuilt bit-for-bit."""
    ctx = _ctx_with_rule(config_dict)
    content = b"<sepa>secret</sepa>"
    src = write_file(
        tmp_path / "business" / "payment" / "confidential/sepa/2026/file.xml", content)

    orch = Orchestrator(ctx)
    orch.scan_once()

    # The metadata must declare encryption with the recipient from the rule.
    meta_file = next(ctx.layout.exchange_out.glob("*.meta.json"))
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["encrypted"] is True
    assert meta["encryption"]["recipient_key_ids"] == ["0xDEADBEEF"]

    # Transport and inbound: file is decrypted and restored identically.
    for item in list(ctx.layout.exchange_out.iterdir()):
        item.replace(ctx.layout.exchange_in / item.name)
    orch.scan_once()
    assert src.read_bytes() == content


def test_non_matching_file_not_encrypted(config_dict: dict, tmp_path: Path) -> None:
    """A file outside the rule path stays unencrypted (payload == clear)."""
    ctx = _ctx_with_rule(config_dict)
    write_file(tmp_path / "business" / "payment" / "public/info.txt", b"hello")

    Orchestrator(ctx).scan_once()

    meta_file = next(ctx.layout.exchange_out.glob("*.meta.json"))
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["encrypted"] is False
    # When not encrypted, payload and clear digests are identical.
    assert meta["payload_file_hash"] == meta["clear_file_hash"]
