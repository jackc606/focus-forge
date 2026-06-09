"""Load a HOI4 .dds / .tga into a QImage via the pure-Python decoders in core."""
from __future__ import annotations

from PySide6.QtGui import QImage

from core.dds_decode import decode_dds
from core.tga_decode import decode_tga


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


def load_tga_qimage(path: str):
    """Decode a TGA via our reader (handles the 24-bpp / top-origin / RLE variants
    Qt's plugin can't). Returns a QImage, or a null QImage on failure."""
    res = decode_tga(path)
    if not res:
        return QImage()
    w, h, bgra = res
    return QImage(bytes(bgra), w, h, QImage.Format_ARGB32).copy()


def load_flag_qimage(path: str):
    """Robust loader for flag images: handles .dds, lets Qt try .png/.jpg/.tga,
    and falls back to our TGA decoder for the TGA variants Qt rejects."""
    low = (path or "").lower()
    if low.endswith(".dds"):
        return load_dds_qimage(path)
    img = QImage(path)
    if img is not None and not img.isNull():
        return img
    if low.endswith(".tga"):
        return load_tga_qimage(path)
    return img
