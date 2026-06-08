"""Human-readable transfer journal — a support-friendly history file.

Appends ONE readable line per completed transfer to ``logs/transfers.log``:
the UTC date, the direction, the business alias, the original name and its
business sub-path, the technical name used on the wire, the original/target
path, the site route and the ``technical_id``.

This is a convenience artifact for operators/support who want to answer "what
was transferred, when, from/to where?" at a glance. The AUTHORITATIVE record
remains the per-file audit trail; writing here is therefore best-effort and
never fails a transfer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from filerouter.ports.clock import Clock


def _rel(relative_path: str, original_filename: str) -> str:
    """Join the business sub-path and the original file name (POSIX-style)."""
    return f"{relative_path}/{original_filename}" if relative_path else original_filename


def _flags(*, encrypted: bool, signed: bool, compressed: bool,
           compression_algo: str | None) -> str:
    """Compact, readable security/transform summary, e.g. 'encrypted+signed+gzip'."""
    parts: list[str] = []
    if compressed:
        parts.append(compression_algo or "compressed")
    if encrypted:
        parts.append("encrypted")
    if signed:
        parts.append("signed")
    return "+".join(parts) if parts else "clear"


class TransferJournal:
    """Appends readable transfer lines to a single text file."""

    def __init__(self, path: Path, clock: "Clock") -> None:
        self._path = path
        self._clock = clock

    def outbound(self, *, technical_id: str, alias: str, relative_path: str,
                 original_filename: str, technical_filename: str,
                 source_site: str, target_site: str, source_path: str,
                 encrypted: bool = False, signed: bool = False,
                 compressed: bool = False, compression_algo: str | None = None,
                 signer_key_id: str | None = None,
                 clear_sha256: str | None = None) -> None:
        """Record a file routed OUT (business -> exchange_out)."""
        flags = _flags(encrypted=encrypted, signed=signed, compressed=compressed,
                       compression_algo=compression_algo)
        signer = f"  signer={signer_key_id}" if (signed and signer_key_id) else ""
        sha = f"  sha256(clear)={clear_sha256}" if clear_sha256 else ""
        self._append(
            f"OUT  {alias:<12} {_rel(relative_path, original_filename)}"
            f"  ->  {technical_filename}"
            f"  | {flags}{signer}{sha}"
            f"  from={source_path}  route={source_site}->{target_site}"
            f"  id={technical_id}")

    def inbound(self, *, technical_id: str, alias: str, relative_path: str,
                original_filename: str, technical_filename: str,
                source_site: str, target_site: str, target_path: str,
                encrypted: bool = False, signed: bool = False,
                compressed: bool = False, compression_algo: str | None = None,
                signer_key_id: str | None = None,
                clear_sha256: str | None = None) -> None:
        """Record a file delivered IN (exchange_in -> business)."""
        flags = _flags(encrypted=encrypted, signed=signed, compressed=compressed,
                       compression_algo=compression_algo)
        signer = f"  signer={signer_key_id}" if (signed and signer_key_id) else ""
        sha = f"  sha256(clear)={clear_sha256}" if clear_sha256 else ""
        self._append(
            f"IN   {alias:<12} {technical_filename}"
            f"  ->  {_rel(relative_path, original_filename)}"
            f"  | {flags}{signer}{sha}"
            f"  to={target_path}  route={source_site}->{target_site}"
            f"  id={technical_id}")

    def read(self) -> list[str]:
        """Return every journal line (oldest first); empty if no file yet."""
        if not self._path.exists():
            return []
        return self._path.read_text(encoding="utf-8").splitlines()

    def _append(self, body: str) -> None:
        """Append one timestamped line; best-effort (never raises)."""
        line = f"{self._clock.now_utc_iso()}  {body}\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except OSError:
            pass  # the audit trail remains authoritative; do not fail a transfer
