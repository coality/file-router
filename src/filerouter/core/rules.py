"""Inclusion/exclusion and encryption-rule matching.

Exclusion wins over inclusion. Encryption rules match on (base_folder_alias,
path_pattern). See docs/fr/05-configuration.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath


def _match(pattern: str, rel_posix: str) -> bool:
    """Glob-match a POSIX relative path against a pattern (CASE-INSENSITIVE).

    Matching is deliberately case-insensitive AND OS-independent. ``fnmatch``
    folds case on Windows but not on Linux, which would make FileRouter behave
    differently per host (e.g. ``*.csv`` matching ``DATA.CSV`` on Windows only).
    We normalize both sides to lower case and use ``fnmatchcase`` so the result
    is the SAME everywhere: ``*.csv`` matches ``data.csv`` and ``DATA.CSV`` on
    Linux and Windows alike.

    Supports a trailing ``**`` meaning "this directory and anything below".
    """
    pat = pattern.lower()
    rel = rel_posix.lower()
    if pat in ("**", "**/*"):
        return True
    if pat.endswith("/**"):
        prefix = pat[:-3]
        return rel == prefix or rel.startswith(prefix + "/")
    return fnmatchcase(rel, pat)


@dataclass(frozen=True)
class EncryptionRule:
    """A single encryption rule from config."""

    base_folder_alias: str
    path_pattern: str
    enabled: bool
    recipient_key_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompressionRule:
    """A single compression rule from config (which files to compress)."""

    base_folder_alias: str
    path_pattern: str
    enabled: bool


class RuleSet:
    """Compiled inclusion/exclusion and encryption rules."""

    def __init__(
        self,
        inclusion: list[str],
        exclusion: list[str],
        encryption_rules: list[EncryptionRule],
        compression_rules: list[CompressionRule] | None = None,
    ) -> None:
        self._inclusion = inclusion or ["**/*"]
        self._exclusion = exclusion or []
        self._encryption = encryption_rules or []
        self._compression = compression_rules or []

    def is_eligible(self, rel_file_posix: str) -> bool:
        """Return True if a file (relative POSIX path incl. filename) is eligible."""
        if any(_match(p, rel_file_posix) for p in self._exclusion):
            return False
        return any(_match(p, rel_file_posix) for p in self._inclusion)

    def eligibility(self, rel_file_posix: str) -> tuple[bool, str]:
        """Like ``is_eligible`` but also return WHY (for the ``preview`` command).

        Returns ``(eligible, reason)``. Exclusion wins, so it is checked first.
        """
        for pattern in self._exclusion:
            if _match(pattern, rel_file_posix):
                return False, f"excluded by '{pattern}'"
        for pattern in self._inclusion:
            if _match(pattern, rel_file_posix):
                return True, f"included by '{pattern}'"
        return False, "no inclusion pattern matched"

    def encryption_for(
        self, base_folder_alias: str, rel_file_posix: str
    ) -> EncryptionRule | None:
        """Return the first matching enabled encryption rule, or None.

        ``rel_file_posix`` is matched against ``path_pattern``; the file's
        directory and full path are both considered so that patterns like
        ``confidential/**`` match files under that directory.
        """
        for rule in self._encryption:
            if rule.base_folder_alias != base_folder_alias:
                continue
            if not rule.enabled:
                continue
            if _match(rule.path_pattern, rel_file_posix) or _match(
                rule.path_pattern, _dir_of(rel_file_posix)
            ):
                return rule
        return None

    def compresses(self, base_folder_alias: str, rel_file_posix: str) -> bool:
        """Return True if an enabled compression rule matches this file."""
        for rule in self._compression:
            if rule.base_folder_alias != base_folder_alias:
                continue
            if not rule.enabled:
                continue
            if _match(rule.path_pattern, rel_file_posix) or _match(
                rule.path_pattern, _dir_of(rel_file_posix)
            ):
                return True
        return False


def _dir_of(rel_file_posix: str) -> str:
    parent = PurePosixPath(rel_file_posix).parent
    return "" if str(parent) == "." else parent.as_posix()
