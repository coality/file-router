"""Inclusion/exclusion and encryption-rule matching.

Exclusion wins over inclusion. Encryption rules match on (base_folder_alias,
path_pattern). See docs/05-configuration.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath


def _match(pattern: str, rel_posix: str) -> bool:
    """Glob-match a POSIX relative path against a pattern.

    Supports a trailing ``**`` meaning "this directory and anything below".
    """
    if pattern in ("**", "**/*"):
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return rel_posix == prefix or rel_posix.startswith(prefix + "/")
    return fnmatch(rel_posix, pattern)


@dataclass(frozen=True)
class EncryptionRule:
    """A single encryption rule from config."""

    base_folder_alias: str
    path_pattern: str
    enabled: bool
    recipient_key_ids: tuple[str, ...] = ()


class RuleSet:
    """Compiled inclusion/exclusion and encryption rules."""

    def __init__(
        self,
        inclusion: list[str],
        exclusion: list[str],
        encryption_rules: list[EncryptionRule],
    ) -> None:
        self._inclusion = inclusion or ["**/*"]
        self._exclusion = exclusion or []
        self._encryption = encryption_rules or []

    def is_eligible(self, rel_file_posix: str) -> bool:
        """Return True if a file (relative POSIX path incl. filename) is eligible."""
        if any(_match(p, rel_file_posix) for p in self._exclusion):
            return False
        return any(_match(p, rel_file_posix) for p in self._inclusion)

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


def _dir_of(rel_file_posix: str) -> str:
    parent = PurePosixPath(rel_file_posix).parent
    return "" if str(parent) == "." else parent.as_posix()
