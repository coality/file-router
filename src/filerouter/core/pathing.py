"""Business-path logic: base_folder identification and relative path computation.

Relative paths are stored POSIX-normalized so they transport between Windows and
Linux hosts (see docs/fr/04-data-formats.md). Depth is unlimited.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath

from filerouter.core.errors import ConfigError, DataError


@dataclass(frozen=True)
class BaseFolder:
    """A declared business root: stable alias + host-local absolute path."""

    alias: str
    path: PurePath


def identify_base_folder(abs_path: PurePath, base_folders: list[BaseFolder]) -> BaseFolder:
    """Return the base_folder owning ``abs_path`` (longest-prefix match).

    Raises ``ConfigError`` if the path belongs to no declared base_folder.
    """
    best: BaseFolder | None = None
    best_len = -1
    for bf in base_folders:
        try:
            abs_path.relative_to(bf.path)
        except ValueError:
            continue
        depth = len(bf.path.parts)
        if depth > best_len:
            best = bf
            best_len = depth
    if best is None:
        raise ConfigError(f"no base_folder owns path: {abs_path}")
    return best


def relative_path(abs_path: PurePath, base: BaseFolder) -> str:
    """Compute the POSIX-normalized directory path of a file relative to ``base``.

    Returns the parent directory relative path (without the filename), as used in
    metadata. An empty string means the file sits at the base_folder root.
    """
    rel = abs_path.relative_to(base.path)
    parent_parts = rel.parts[:-1]  # drop the filename
    return PurePosixPath(*parent_parts).as_posix() if parent_parts else ""


def business_target(base_path: PurePath, rel_dir: str, original_filename: str) -> PurePath:
    """Rebuild the final business path from base + relative dir + original name.

    Validates that ``rel_dir`` is safe: not absolute and free of '..' traversal.
    """
    safe = _validate_relative(rel_dir)
    target = base_path
    for part in safe.parts:
        target = target / part
    return target / original_filename


def _validate_relative(rel_dir: str) -> PurePosixPath:
    """Reject absolute paths and '..' traversal; return a normalized PurePosixPath."""
    if rel_dir in ("", "."):
        return PurePosixPath()
    posix = PurePosixPath(rel_dir)
    if posix.is_absolute():
        raise DataError(f"relative_path must not be absolute: {rel_dir!r}")
    for part in posix.parts:
        if part == "..":
            raise DataError(f"relative_path must not contain '..': {rel_dir!r}")
    return posix
