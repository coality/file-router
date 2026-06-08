"""Typed configuration model.

This module turns the validated YAML dict into small, immutable dataclasses that
the core consumes. Each ``from_dict`` helper is intentionally tiny and documented
so the mapping from YAML to objects stays obvious.

See docs/fr/05-configuration.md for the YAML contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

from filerouter.core.layout import RuntimeLayout
from filerouter.core.naming import NamingConfig
from filerouter.core.pathing import BaseFolder
from filerouter.core.rules import CompressionRule, EncryptionRule, RuleSet


@dataclass(frozen=True)
class InstanceConfig:
    """Host identity and concurrency settings (YAML ``instance``)."""

    site: str
    role: str  # "outbound" | "inbound" | "both"
    workers: int = 4
    worker_type: str = "thread"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstanceConfig":
        """Build the instance config; defaults keep small deployments simple."""
        return cls(
            site=data["site"],
            role=data.get("role", "both"),
            workers=int(data.get("workers", 4)),
            worker_type=data.get("worker_type", "thread"),
        )


@dataclass(frozen=True)
class HashingConfig:
    """Hashing options (YAML ``hashing``). Algorithm is always SHA-256."""

    chunk_size_bytes: int = 1 << 20
    verify_inbound: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HashingConfig":
        """Build hashing config; the algorithm field is fixed and not stored."""
        return cls(
            chunk_size_bytes=int(data.get("chunk_size_bytes", 1 << 20)),
            verify_inbound=bool(data.get("verify_inbound", True)),
        )


@dataclass(frozen=True)
class EncryptionConfig:
    """Encryption backend + key model (YAML ``encryption``)."""

    backend: str = "noop"  # "gnupg" | "pgpy" | "noop"
    gnupg_home: str | None = None
    signing_key_id: str | None = None
    require_signature_inbound: bool = True
    armored: bool = False
    rules: tuple[EncryptionRule, ...] = ()
    allowed_signers: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EncryptionConfig":
        """Build the encryption config and compile its rules list."""
        rules = tuple(_encryption_rule(r) for r in data.get("rules", []))
        return cls(
            backend=data.get("backend", "noop"),
            gnupg_home=data.get("gnupg_home"),
            signing_key_id=data.get("signing_key_id"),
            require_signature_inbound=bool(data.get("require_signature_inbound", True)),
            armored=bool(data.get("armored", False)),
            rules=rules,
            allowed_signers=tuple(data.get("allowed_signers", [])),
        )


def _encryption_rule(data: dict[str, Any]) -> EncryptionRule:
    """Map one YAML encryption rule entry to an EncryptionRule."""
    return EncryptionRule(
        base_folder_alias=data["base_folder_alias"],
        path_pattern=data["path_pattern"],
        enabled=bool(data["enabled"]),
        recipient_key_ids=tuple(data.get("recipient_key_ids", [])),
    )


@dataclass(frozen=True)
class CompressionConfig:
    """Payload compression options (YAML ``compression``)."""

    algorithm: str = "gzip"  # "gzip" | "none"
    level: int = 6

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompressionConfig":
        """Build compression config; rules live in the shared RuleSet."""
        return cls(
            algorithm=data.get("algorithm", "gzip"),
            level=int(data.get("level", 6)),
        )


@dataclass(frozen=True)
class ScanningConfig:
    """Detection cadence and stability/pairing windows (YAML ``scanning``)."""

    interval_seconds: float = 5.0
    stability_checks: int = 3
    stability_interval_seconds: float = 2.0
    pair_grace_period_seconds: float = 30.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScanningConfig":
        """Build scanning config; these windows drive inbound readiness."""
        return cls(
            interval_seconds=float(data.get("interval_seconds", 5.0)),
            stability_checks=int(data.get("stability_checks", 3)),
            stability_interval_seconds=float(data.get("stability_interval_seconds", 2.0)),
            pair_grace_period_seconds=float(data.get("pair_grace_period_seconds", 30.0)),
        )


@dataclass(frozen=True)
class RetryConfig:
    """Retry/backoff settings for transient IO errors (YAML ``retry``)."""

    max_attempts: int = 5
    base_delay_seconds: float = 2.0
    backoff: str = "exponential"
    jitter: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetryConfig":
        """Build retry config used only for transient errors."""
        return cls(
            max_attempts=int(data.get("max_attempts", 5)),
            base_delay_seconds=float(data.get("base_delay_seconds", 2.0)),
            backoff=data.get("backoff", "exponential"),
            jitter=bool(data.get("jitter", True)),
        )


@dataclass(frozen=True)
class ArchivalConfig:
    """Source-file policy after a successful outbound (YAML ``archival``)."""

    source_policy: str = "archive"  # "archive" | "delete"
    archive_layout: str = "%Y/%m/%d"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArchivalConfig":
        """Build archival config controlling source disposition."""
        return cls(
            source_policy=data.get("source_policy", "archive"),
            archive_layout=data.get("archive_layout", "%Y/%m/%d"),
        )


@dataclass(frozen=True)
class DuplicatesConfig:
    """Duplicate policies (YAML ``duplicates``)."""

    outbound_policy: str = "skip"
    inbound_policy: str = "skip"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DuplicatesConfig":
        """Build duplicate-handling policies for both directions."""
        return cls(
            outbound_policy=data.get("outbound_policy", "skip"),
            inbound_policy=data.get("inbound_policy", "skip"),
        )


@dataclass(frozen=True)
class Config:
    """Aggregate, validated configuration consumed by the core."""

    instance: InstanceConfig
    base_folders: tuple[BaseFolder, ...]
    flows: dict[str, str]
    routing: dict[str, str]
    layout: RuntimeLayout
    naming: NamingConfig
    hashing: HashingConfig
    encryption: EncryptionConfig
    compression: CompressionConfig
    ruleset: RuleSet
    scanning: ScanningConfig
    retry: RetryConfig
    archival: ArchivalConfig
    duplicates: DuplicatesConfig
    logging: dict[str, Any] = field(default_factory=dict)
    retention: dict[str, int] = field(default_factory=dict)
    id_strategy: str = "ulid"  # technical_id generator: "ulid" | "uuid4"

    def base_folder_by_alias(self, alias: str) -> BaseFolder | None:
        """Return the base_folder with this alias, or None (host-local mapping)."""
        for bf in self.base_folders:
            if bf.alias == alias:
                return bf
        return None

    def flow_for(self, alias: str) -> str:
        """Return the flow label for an alias, defaulting to the alias itself."""
        return self.flows.get(alias, alias)


def build_config(data: dict[str, Any]) -> Config:
    """Assemble the typed Config from an already schema-validated dict.

    Kept small by delegating each section to its own ``from_dict`` helper.
    """
    base_folders = _base_folders(data["base_folders"])
    mappings = data.get("mappings", {})
    layout = _layout(data)
    ruleset = _ruleset(data)
    return Config(
        instance=InstanceConfig.from_dict(data["instance"]),
        base_folders=base_folders,
        flows=dict(mappings.get("flows", {})),
        routing=dict(mappings.get("routing", {})),
        layout=layout,
        naming=_naming(data["naming"]),
        hashing=HashingConfig.from_dict(data.get("hashing", {})),
        encryption=EncryptionConfig.from_dict(data.get("encryption", {})),
        compression=CompressionConfig.from_dict(data.get("compression", {})),
        ruleset=ruleset,
        scanning=ScanningConfig.from_dict(data.get("scanning", {})),
        retry=RetryConfig.from_dict(data.get("retry", {})),
        archival=ArchivalConfig.from_dict(data.get("archival", {})),
        duplicates=DuplicatesConfig.from_dict(data.get("duplicates", {})),
        logging=data.get("logging", {}),
        retention=data.get("retention", {}),
        id_strategy=data["naming"].get("technical_id_strategy", "ulid"),
    )


def _base_folders(entries: list[dict[str, Any]]) -> tuple[BaseFolder, ...]:
    """Map YAML base_folder entries to BaseFolder objects (alias + path)."""
    return tuple(
        BaseFolder(alias=e["alias"], path=PurePath(e["path"])) for e in entries
    )


def _layout(data: dict[str, Any]) -> RuntimeLayout:
    """Build the runtime/exchange layout from the YAML paths."""
    return RuntimeLayout(
        runtime_root=Path(data["runtime"]["root"]),
        exchange_out=Path(data["exchange"]["out"]),
        exchange_in=Path(data["exchange"]["in"]),
    )


def _naming(data: dict[str, Any]) -> NamingConfig:
    """Build the naming config from the YAML ``naming`` section."""
    return NamingConfig(
        pattern=data["pattern"],
        timestamp_format=data.get("timestamp_format", "%Y%m%dT%H%M%S"),
        max_length=int(data.get("max_length", 120)),
        charset=data.get("charset", "portable"),
        meta_suffix=data.get("meta_suffix", ".meta.json"),
    )


def _ruleset(data: dict[str, Any]) -> RuleSet:
    """Compile inclusion/exclusion globs and encryption rules into a RuleSet."""
    inclusion = list(data.get("inclusion", {}).get("patterns", ["**/*"]))
    exclusion = list(data.get("exclusion", {}).get("patterns", []))
    rules = [_encryption_rule(r) for r in data.get("encryption", {}).get("rules", [])]
    comp = [_compression_rule(r) for r in data.get("compression", {}).get("rules", [])]
    return RuleSet(inclusion=inclusion, exclusion=exclusion, encryption_rules=rules,
                   compression_rules=comp)


def _compression_rule(data: dict[str, Any]) -> CompressionRule:
    """Map one YAML compression rule entry to a CompressionRule."""
    return CompressionRule(
        base_folder_alias=data["base_folder_alias"],
        path_pattern=data["path_pattern"],
        enabled=bool(data["enabled"]),
    )
