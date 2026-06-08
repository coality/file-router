"""Unit tests for inclusion/exclusion and encryption-rule matching."""

from __future__ import annotations

from filerouter.core.rules import EncryptionRule, RuleSet


def _ruleset(**over) -> RuleSet:
    """Build a RuleSet with defaults for tests."""
    return RuleSet(
        inclusion=over.get("inclusion", ["**/*"]),
        exclusion=over.get("exclusion", []),
        encryption_rules=over.get("encryption_rules", []),
    )


def test_default_inclusion_accepts_everything() -> None:
    """With default inclusion and no exclusion, any file is eligible."""
    rs = _ruleset()
    assert rs.is_eligible("a/b/c/file.csv") is True


def test_exclusion_wins_over_inclusion() -> None:
    """Exclusion takes precedence over inclusion."""
    rs = _ruleset(exclusion=["**/*.tmp"])
    assert rs.is_eligible("a/b/work.tmp") is False
    assert rs.is_eligible("a/b/work.csv") is True


def test_office_temp_excluded() -> None:
    """Office lock files (~$...) are excluded."""
    rs = _ruleset(exclusion=["**/~$*"])
    assert rs.is_eligible("docs/~$report.docx") is False


def test_encryption_rule_matches_directory_glob() -> None:
    """A confidential/** rule matches files under that directory at any depth."""
    rule = EncryptionRule("PAYMENT", "confidential/**", True, ("0xKEY",))
    rs = _ruleset(encryption_rules=[rule])
    match = rs.encryption_for("PAYMENT", "confidential/sepa/2026/file.xml")
    assert match is not None
    assert match.recipient_key_ids == ("0xKEY",)


def test_encryption_rule_respects_alias() -> None:
    """A rule only applies to its declared base_folder alias."""
    rule = EncryptionRule("PAYMENT", "**", True, ("0xKEY",))
    rs = _ruleset(encryption_rules=[rule])
    assert rs.encryption_for("SAP_FR", "anything.csv") is None


def test_disabled_rule_is_ignored() -> None:
    """A disabled rule never matches."""
    rule = EncryptionRule("PAYMENT", "**", False, ("0xKEY",))
    rs = _ruleset(encryption_rules=[rule])
    assert rs.encryption_for("PAYMENT", "x.csv") is None


def test_non_matching_path_returns_none() -> None:
    """A file outside the rule's path pattern is not encrypted."""
    rule = EncryptionRule("PAYMENT", "confidential/**", True, ("0xKEY",))
    rs = _ruleset(encryption_rules=[rule])
    assert rs.encryption_for("PAYMENT", "public/info.txt") is None
