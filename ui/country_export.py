"""Write a country's binary assets at export time: flag TGAs (large/medium/small
+ ideology variants) and custom leader portrait DDS files."""
from __future__ import annotations

import base64
import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage

from core.exporters import _leader_slug
from core.image_write import dds_bgra32, tga_bgra32


def _qimage_from_b64(data: str):
    if not data:
        return None
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None
    img = QImage()
    if not img.loadFromData(QByteArray(raw)):
        return None
    return img


def _argb32_bytes(img: QImage):
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    return bytes(img.constBits())[:w * h * 4], w, h


def _write_tga(img: QImage, w: int, h: int, path: str) -> None:
    scaled = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bgra, sw, sh = _argb32_bytes(scaled)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(tga_bgra32(bgra, sw, sh))


def export_country_assets(project, mod_dir: str) -> int:
    """Returns the number of asset files written."""
    c = getattr(project, "country", None)
    if not c:
        return 0
    tag = project.countryTag or "TAG"
    written = 0

    flags = {tag: c.flagMain}
    for ideo, data in (c.flagVariants or {}).items():
        if data:
            flags[f"{tag}_{ideo}"] = data
    for fname, b64 in flags.items():
        img = _qimage_from_b64(b64)
        if img is None:
            continue
        _write_tga(img, 82, 52, os.path.join(mod_dir, "gfx", "flags", f"{fname}.tga"))
        _write_tga(img, 41, 26, os.path.join(mod_dir, "gfx", "flags", "medium", f"{fname}.tga"))
        _write_tga(img, 10, 7, os.path.join(mod_dir, "gfx", "flags", "small", f"{fname}.tga"))
        written += 3

    for leader in c.leaders:
        if not leader.pictureData:
            continue
        img = _qimage_from_b64(leader.pictureData)
        if img is None:
            continue
        bgra, w, h = _argb32_bytes(img)
        ld = os.path.join(mod_dir, "gfx", "leaders", tag)
        os.makedirs(ld, exist_ok=True)
        with open(os.path.join(ld, f"{_leader_slug(leader)}.dds"), "wb") as f:
            f.write(dds_bgra32(bgra, w, h))
        written += 1

    return written
