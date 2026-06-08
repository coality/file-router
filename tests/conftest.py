"""Shared test fixtures: realistic config, frozen clock, complex tree builders.

These fixtures back both the unit tests and the e2e functional tests. The goal
is to exercise 100% of the documented functional scope on real filesystem trees.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from filerouter.config.loader import load_config_dict
from filerouter.service.runner import build_context
from filerouter.service.runner import Service


class FrozenClock:
    """Deterministic clock for tests; advances only when asked.

    Implements the Clock port so audit/naming timestamps are reproducible.
    """

    def __init__(self) -> None:
        self._counter = itertools.count()
        self._seconds = 1_700_000_000.0  # fixed epoch base

    def now_utc_iso(self) -> str:
        # Unique, ordered ISO timestamps for deterministic seq ordering.
        n = next(self._counter)
        return f"2026-06-08T12:00:{n % 60:02d}.{n % 1000:03d}Z"

    def now_compact(self, fmt: str) -> str:
        return "20260608T120000"

    def monotonic(self) -> float:
        return self._seconds


def _base_config(root: Path, *, role: str = "both", backend: str = "noop") -> dict:
    """Build a realistic config dict rooted under a temp directory."""
    business = root / "business"
    fr = root / "FileRouter"
    return {
        "instance": {"site": "PARIS", "role": role, "workers": 4},
        "base_folders": [
            {"alias": "SAP_FR", "path": str(business / "sap_fr")},
            {"alias": "CRM_DE", "path": str(business / "crm_de")},
            {"alias": "PAYMENT", "path": str(business / "payment")},
        ],
        "mappings": {
            "flows": {"PAYMENT": "PAYMENT", "SAP_FR": "SAPFR", "CRM_DE": "CRMDE"},
            "routing": {"PAYMENT": "FRANKFURT", "SAP_FR": "PARIS", "CRM_DE": "BERLIN"},
        },
        "exchange": {"out": str(fr / "exchange_out"), "in": str(fr / "exchange_in")},
        "runtime": {"root": str(fr / "runtime")},
        "naming": {
            "pattern": "{flow}_{direction}_{timestamp}_{technical_id}.{extension}",
            "timestamp_format": "%Y%m%dT%H%M%S",
            "max_length": 120,
            "technical_id_strategy": "ulid",
            "charset": "portable",
            "meta_suffix": ".meta.json",
        },
        "hashing": {"algorithm": "SHA-256", "chunk_size_bytes": 65536,
                    "verify_inbound": True},
        "encryption": {"backend": backend, "require_signature_inbound": False,
                       "rules": []},
        "inclusion": {"patterns": ["**/*"]},
        "exclusion": {"patterns": ["**/*.tmp", "**/*.part", "**/~$*"]},
        "duplicates": {"outbound_policy": "skip", "inbound_policy": "skip"},
        "archival": {"source_policy": "archive", "archive_layout": "%Y/%m/%d"},
        "retention": {"archive_days": 30, "audit_days": 365, "logs_days": 90,
                      "error_days": 0},
        "scanning": {"interval_seconds": 0.1, "stability_checks": 1,
                     "stability_interval_seconds": 0.1,
                     "pair_grace_period_seconds": 5.0},
        "locking": {"lock_ttl_seconds": 300, "heartbeat_interval_seconds": 30},
        "logging": {"format": "jsonl", "streams": {}},
    }


@pytest.fixture
def config_dict(tmp_path: Path) -> dict:
    """A realistic config dict rooted in the test's tmp_path."""
    return _base_config(tmp_path)


@pytest.fixture
def make_config(tmp_path: Path):
    """Factory to build a config with overrides (role, backend, mutate dict)."""

    def _make(*, role: str = "both", backend: str = "noop", mutate=None) -> dict:
        cfg = _base_config(tmp_path, role=role, backend=backend)
        if mutate is not None:
            mutate(cfg)
        return cfg

    return _make


@pytest.fixture
def context(config_dict: dict):
    """A fully-wired Context using the no-op crypto backend and frozen clock."""
    config = load_config_dict(config_dict)
    ctx = build_context(config, quiet=True)
    # Swap in the deterministic clock for reproducible timestamps.
    object.__setattr__(ctx, "clock", FrozenClock())
    object.__setattr__(ctx.audit, "_clock", ctx.clock)
    return ctx


@pytest.fixture
def service(config_dict: dict) -> Service:
    """A ready-to-run Service (quiet logging) for e2e tests."""
    from filerouter.service.runner import build_service

    return build_service(load_config_dict(config_dict), quiet=True)


def write_file(path: Path, content: bytes) -> Path:
    """Create parent dirs and write ``content`` to ``path``; return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def build_complex_tree(base_root: Path) -> list[tuple[str, Path, bytes]]:
    """Create a deep, varied business tree and return (alias, path, content).

    Covers unlimited depth, multiple base_folders, and several extensions, as
    required to exercise the full functional scope.
    """
    files: list[tuple[str, Path, bytes]] = []
    specs = [
        ("sap_fr", "clients/contracts/v5/production/2026/06/exports/batch01/file.csv",
         b"id;amount\n1;100\n2;200\n"),
        ("sap_fr", "root_level.txt", b"top of SAP_FR\n"),
        ("crm_de", "leads/2026/q2/de/customers.json", b'{"k":"v"}'),
        ("payment", "confidential/sepa/2026/06/08/batch.xml",
         b"<sepa><tx>1</tx></sepa>"),
        ("payment", "a/very/deep/nested/path/that/keeps/going/deeper/file.dat",
         bytes(range(256)) * 32),
    ]
    for alias, rel, content in specs:
        p = write_file(base_root / "business" / alias / rel, content)
        files.append((alias.upper(), p, content))
    return files
