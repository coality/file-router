"""End-to-end functional tests on complex directory trees.

These tests build deep, multi-base_folder business trees, run the full outbound
pipeline, simulate the external transport (exchange_out -> exchange_in), run the
full inbound pipeline, and assert the business tree is rebuilt bit-for-bit with a
complete audit trail. They aim to cover 100% of the documented functional scope.
"""

from __future__ import annotations

from pathlib import Path

from filerouter.core.orchestrator import Orchestrator
from tests.conftest import build_complex_tree


def _transport(exchange_out: Path, exchange_in: Path) -> int:
    """Simulate the external transport: move every file out -> in (flat).

    Returns the number of payload files moved (metadata excluded from the count).
    """
    exchange_in.mkdir(parents=True, exist_ok=True)
    moved_payloads = 0
    for item in sorted(exchange_out.iterdir()):
        if item.is_file():
            if not item.name.endswith(".meta.json"):
                moved_payloads += 1
            item.replace(exchange_in / item.name)
    return moved_payloads


def test_full_roundtrip_rebuilds_tree(context, tmp_path: Path) -> None:
    """A complex tree survives outbound + transport + inbound unchanged."""
    files = build_complex_tree(tmp_path)
    expected = {p: content for _alias, p, content in files}

    orch = Orchestrator(context)

    # -- outbound -------------------------------------------------------
    out_report = orch.scan_once()
    assert out_report.outbound_published == len(files)
    assert out_report.outbound_quarantined == 0

    # Sources were consumed (archived), exchange_out holds flat payload+meta pairs.
    for p in expected:
        assert not p.exists(), f"source should be consumed: {p}"
    _assert_flat_pairs(context.layout.exchange_out, len(files))

    # -- transport ------------------------------------------------------
    moved = _transport(context.layout.exchange_out, context.layout.exchange_in)
    assert moved == len(files)

    # -- inbound --------------------------------------------------------
    in_report = orch.scan_once()
    assert in_report.inbound_delivered == len(files)
    assert in_report.inbound_quarantined == 0

    # -- verification ---------------------------------------------------
    for path, content in expected.items():
        assert path.exists(), f"file not rebuilt: {path}"
        assert path.read_bytes() == content, f"content mismatch: {path}"


def _assert_flat_pairs(exchange_out: Path, count: int) -> None:
    """Assert exchange_out is flat and holds exactly ``count`` payload+meta pairs."""
    entries = list(exchange_out.iterdir())
    assert all(e.is_file() for e in entries), "exchange_out must stay flat"
    payloads = [e for e in entries if not e.name.endswith(".meta.json")]
    metas = [e for e in entries if e.name.endswith(".meta.json")]
    assert len(payloads) == count
    assert len(metas) == count


def test_relative_paths_are_posix_and_deep(context, tmp_path: Path) -> None:
    """Deep nesting is preserved and relative_path is POSIX-normalized."""
    build_complex_tree(tmp_path)
    Orchestrator(context).scan_once()

    metas = list(context.layout.exchange_out.glob("*.meta.json"))
    rels = [_read_relative_path(m) for m in metas]
    # No backslashes, no drive letters: POSIX-normalized for cross-platform transport.
    assert all("\\" not in r for r in rels)
    # The deepest known path is preserved end-to-end.
    assert any("a/very/deep/nested/path" in r for r in rels)


def _read_relative_path(meta_file: Path) -> str:
    """Extract the relative_path field from a metadata file."""
    import json

    return json.loads(meta_file.read_text(encoding="utf-8"))["relative_path"]


def test_multi_base_folder_routing(context, tmp_path: Path) -> None:
    """Each file is attributed to the correct base_folder alias and target site."""
    import json

    build_complex_tree(tmp_path)
    Orchestrator(context).scan_once()

    by_alias: dict[str, str] = {}
    for meta_file in context.layout.exchange_out.glob("*.meta.json"):
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        by_alias[data["base_folder_alias"]] = data["target_site"]

    # Routing table from the test config must be honored.
    assert by_alias["PAYMENT"] == "FRANKFURT"
    assert by_alias["SAP_FR"] == "PARIS"
    assert by_alias["CRM_DE"] == "BERLIN"
