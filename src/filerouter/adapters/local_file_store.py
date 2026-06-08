"""LocalFileStore: filesystem adapter with atomic publish semantics.

See docs/03-state-management.md §4 for the atomicity rules.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Iterator

from filerouter.core.errors import TransientError


class LocalFileStore:
    """FileStore backed by the local filesystem (os/pathlib)."""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def size(self, path: Path) -> int:
        return path.stat().st_size

    def mtime(self, path: Path) -> float:
        return path.stat().st_mtime

    def iter_files(self, root: Path, recursive: bool = True) -> Iterator[Path]:
        if not root.exists():
            return
        it = root.rglob("*") if recursive else root.glob("*")
        for p in it:
            if p.is_file():
                yield p

    def is_stable(self, path: Path, checks: int, interval: float) -> bool:
        try:
            prev = path.stat()
        except FileNotFoundError:
            return False
        signature = (prev.st_size, prev.st_mtime_ns)
        # checks=1 means a single stat with no waiting; checks=N adds N-1 polls.
        for _ in range(max(0, checks - 1)):
            time.sleep(interval)
            try:
                cur = path.stat()
            except FileNotFoundError:
                return False
            cur_sig = (cur.st_size, cur.st_mtime_ns)
            if cur_sig != signature:
                return False
            signature = cur_sig
        return self._exclusive_open_ok(path)

    @staticmethod
    def _exclusive_open_ok(path: Path) -> bool:
        """Probe whether the file is still held open by a writer.

        On Windows an exclusive open fails while a writer holds the file. On
        POSIX this is a best-effort no-op that simply confirms readability.
        """
        try:
            with open(path, "rb"):
                return True
        except (PermissionError, OSError):
            return False

    def atomic_move(self, src: Path, dst: Path) -> None:
        self.makedirs(dst.parent)
        try:
            os.replace(src, dst)  # atomic within a volume (NTFS and POSIX)
            return
        except OSError:
            # Cross-volume: copy to a temp file on the destination volume,
            # fsync, then atomic rename.
            self._cross_volume_move(src, dst)

    def _cross_volume_move(self, src: Path, dst: Path) -> None:
        tmp = dst.with_name(dst.name + ".partial")
        try:
            shutil.copyfile(src, tmp)
            self._fsync_file(tmp)
            os.replace(tmp, dst)
            self._fsync_dir(dst.parent)
            os.unlink(src)
        except OSError as exc:  # pragma: no cover - environment dependent
            if tmp.exists():
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise TransientError(f"cross-volume move failed: {exc}") from exc

    def atomic_write_bytes(self, dst: Path, data: bytes) -> None:
        self.makedirs(dst.parent)
        tmp = dst.with_name(dst.name + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dst)

    def append_line(self, dst: Path, line: str) -> None:
        self.makedirs(dst.parent)
        with open(dst, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def makedirs(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def remove(self, path: Path) -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with open(path, "rb") as fh:
            os.fsync(fh.fileno())

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        # Directory fsync is POSIX-only; ignore where unsupported (e.g. Windows).
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)
