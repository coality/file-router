"""SHA-256 hashing engine (streaming, constant memory).

See docs/fr/07-hashing.md. Comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from filerouter.core.models import FileHash

ALGORITHM = "SHA-256"
DEFAULT_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: Path, chunk_size: int = DEFAULT_CHUNK) -> FileHash:
    """Compute the SHA-256 of a file by streaming it in fixed-size chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return FileHash(algorithm=ALGORITHM, value=digest.hexdigest())


def sha256_bytes(data: bytes) -> FileHash:
    """Compute the SHA-256 of an in-memory byte string."""
    return FileHash(algorithm=ALGORITHM, value=hashlib.sha256(data).hexdigest())


def hashes_match(expected: FileHash, actual: FileHash) -> bool:
    """Constant-time comparison of two digests (algorithm + value)."""
    if expected.algorithm != actual.algorithm:
        return False
    return hmac.compare_digest(expected.value, actual.value)
