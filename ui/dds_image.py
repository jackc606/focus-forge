"""Load a HOI4 .dds into a QImage via the pure-Python decoder in core.dds_decode."""
from __future__ import annotations

from PySide6.QtGui import QImage

from core.dds_decode import decode_dds


def load_dds_qimage(path: str):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    res = decode_dds(data)
    if not res:
        return None
    w, h, bgra = res
    # Format_ARGB32 reads each word as 0xAARRGGBB → little-endian bytes B,G,R,A,
    # which is exactly what decode_dds produces. copy() detaches from the buffer.
    return QImage(bytes(bgra), w, h, QImage.Format_ARGB32).copy()
