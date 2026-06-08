"""E2E security tests: integrity and signature enforcement.

Proves that tampering or a missing/invalid signature never results in delivery;
the item is quarantined instead. See docs/10-security-policy.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from filerouter.config.loader import load_config_dict
from filerouter.core.inbound import InboundProcessor
from filerouter.core.orchestrator import Orchestrator
from filerouter.service.runner import build_context
from tests.conftest import FrozenClock, write_file


def _one_pair_in_inbound(context, tmp_path: Path):
    """Publish one file and move its pair into exchange_in; return the pair."""
    write_file(tmp_path / "business" / "sap_fr" / "deep/dir/file.csv", b"a;b\n1;2\n")
    Orchestrator(context).scan_once()
    out = context.layout.exchange_out
    payload = next(p for p in out.iterdir() if not p.name.endswith(".meta.json"))
    meta = payload.with_name(payload.name + ".meta.json")
    dst_p = context.layout.exchange_in / payload.name
    dst_m = context.layout.exchange_in / meta.name
    payload.replace(dst_p)
    meta.replace(dst_m)
    return dst_p, dst_m


def test_tampered_payload_is_quarantined(context, tmp_path: Path) -> None:
    """A corrupted payload fails the payload-hash check and is quarantined."""
    payload, _meta = _one_pair_in_inbound(context, tmp_path)
    payload.write_bytes(b"TAMPERED CONTENT")  # corrupt the transported payload

    outcome = InboundProcessor(context).process(payload)
    assert outcome.status == "quarantined"
    # Nothing was delivered into the business tree.
    delivered = tmp_path / "business" / "sap_fr" / "deep/dir/file.csv"
    assert not delivered.exists()


def test_tampered_clear_hash_is_quarantined(context, tmp_path: Path) -> None:
    """A metadata clear-hash that does not match the content is rejected."""
    payload, meta = _one_pair_in_inbound(context, tmp_path)
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["clear_file_hash"]["value"] = "0" * 64  # wrong digest
    meta.write_text(json.dumps(data), encoding="utf-8")

    outcome = InboundProcessor(context).process(payload)
    assert outcome.status == "quarantined"


def test_signature_required_but_absent_is_quarantined(config_dict: dict,
                                                      tmp_path: Path) -> None:
    """With signatures required, an unsigned (noop) encrypted payload is rejected."""
    # Require inbound signatures and encrypt everything via a rule.
    config_dict["encryption"]["require_signature_inbound"] = True
    config_dict["encryption"]["rules"] = [
        {"base_folder_alias": "SAP_FR", "path_pattern": "**", "enabled": True,
         "recipient_key_ids": ["0xDEADBEEF"]},
    ]
    ctx = build_context(load_config_dict(config_dict), quiet=True)
    object.__setattr__(ctx, "clock", FrozenClock())
    object.__setattr__(ctx.audit, "_clock", ctx.clock)

    payload, _meta = _one_pair_in_inbound(ctx, tmp_path)
    outcome = InboundProcessor(ctx).process(payload)
    # noop "decrypt" reports no valid signature -> security rejection.
    assert outcome.status == "quarantined"
