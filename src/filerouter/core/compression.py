"""Payload compression (gzip, streaming, constant memory).

Compression sits between the clear file and encryption on outbound, and is
reversed after decryption on inbound:

    clear -> [compress] -> [encrypt] -> payload        (outbound)
    payload -> [decrypt] -> [decompress] -> clear      (inbound)

The clear_file_hash is always computed on the ORIGINAL clear bytes, so integrity
is verified end-to-end regardless of compression. See docs/fr/04-data-formats.md.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

ALGORITHM = "gzip"
_CHUNK = 1 << 20  # 1 MiB streaming buffer


def compress_file(src: Path, dst: Path, level: int = 6) -> None:
    """Gzip-compress ``src`` into ``dst`` in a streaming, constant-memory way."""
    with open(src, "rb") as fin, gzip.open(dst, "wb", compresslevel=level) as fout:
        shutil.copyfileobj(fin, fout, length=_CHUNK)


def decompress_file(src: Path, dst: Path) -> None:
    """Gzip-decompress ``src`` into ``dst`` in a streaming, constant-memory way."""
    with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout, length=_CHUNK)
