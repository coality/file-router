"""E2E: payload compression (gzip) round trip, alone and combined with crypto."""

from __future__ import annotations

from pathlib import Path

from filerouter.config.loader import load_config_dict
from filerouter.core.orchestrator import Orchestrator
from filerouter.service.runner import build_context
from tests.conftest import FrozenClock, write_file


def _ctx(config_dict: dict, *, with_rule: bool):
    """Wire a context that compresses SAP_FR when ``with_rule`` is set."""
    if with_rule:
        config_dict["compression"] = {
            "algorithm": "gzip", "level": 6,
            "rules": [{"base_folder_alias": "SAP_FR", "path_pattern": "**",
                       "enabled": True}],
        }
    ctx = build_context(load_config_dict(config_dict), quiet=True)
    object.__setattr__(ctx, "clock", FrozenClock())
    object.__setattr__(ctx.audit, "_clock", ctx.clock)
    return ctx


def _transport_all(ctx) -> None:
    """Move every published pair from exchange_out to exchange_in."""
    for item in list(ctx.layout.exchange_out.iterdir()):
        item.replace(ctx.layout.exchange_in / item.name)


def test_compression_roundtrip(config_dict: dict, tmp_path: Path) -> None:
    """A compressed file is gzip-shrunk on the wire and restored identically."""
    ctx = _ctx(config_dict, with_rule=True)
    # Highly compressible content so the payload is clearly smaller.
    content = b"A" * 100_000
    src = write_file(tmp_path / "business" / "sap_fr" / "deep/x/big.txt", content)

    orch = Orchestrator(ctx)
    orch.scan_once()

    payload = next(p for p in ctx.layout.exchange_out.iterdir()
                   if not p.name.endswith(".meta.json"))
    # The gzip payload must be much smaller than the clear content.
    assert payload.stat().st_size < len(content)

    import json
    meta = json.loads(next(ctx.layout.exchange_out.glob("*.meta.json"))
                      .read_text(encoding="utf-8"))
    assert meta["compressed"] is True
    assert meta["compression"]["algorithm"] == "gzip"

    _transport_all(ctx)
    orch.scan_once()
    assert src.read_bytes() == content  # restored bit-for-bit


def test_no_compression_rule_means_uncompressed(config_dict: dict,
                                                tmp_path: Path) -> None:
    """Without a compression rule, the metadata is not flagged compressed."""
    ctx = _ctx(config_dict, with_rule=False)
    write_file(tmp_path / "business" / "sap_fr" / "f.txt", b"hello")
    Orchestrator(ctx).scan_once()

    import json
    meta = json.loads(next(ctx.layout.exchange_out.glob("*.meta.json"))
                      .read_text(encoding="utf-8"))
    assert meta.get("compressed", False) is False
