"""Crash-safe file writes.

Write to a temporary sibling, flush to disk, then atomically replace the
target — so a crash, kill, or full disk mid-save never leaves a truncated
project file or half-written mod asset behind. ``os.replace`` is atomic on
both Windows (NTFS) and POSIX.
"""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))
