"""Write a country's binary assets at export time: flag TGAs (large/medium/small
+ ideology variants) and custom leader portrait DDS files."""
from __future__ import annotations

import base64
import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage

from core.exporters import (
    _country_leaders_for_assets,
    _decision_icon_relpath,
    _event_picture_relpath,
    _focus_icon_relpath,
    _leader_slug,
    _party_logo_relpath,
)
from core.file_io import atomic_write_bytes
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
    atomic_write_bytes(path, tga_bgra32(bgra, sw, sh))


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

    for leader in _country_leaders_for_assets(c):
        if not leader.pictureData:
            continue
        img = _qimage_from_b64(leader.pictureData)
        if img is None:
            continue
        bgra, w, h = _argb32_bytes(img)
        ld = os.path.join(mod_dir, "gfx", "leaders", tag)
        os.makedirs(ld, exist_ok=True)
        atomic_write_bytes(os.path.join(ld, f"{_leader_slug(leader)}.dds"),
                           dds_bgra32(bgra, w, h))
        written += 1

    for party in c.parties:
        if not party.logoData or not party.subIdeology:
            continue
        img = _qimage_from_b64(party.logoData)
        if img is None:
            continue
        bgra, w, h = _argb32_bytes(img)
        rel = _party_logo_relpath(tag, party.subIdeology)
        path = os.path.join(mod_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, dds_bgra32(bgra, w, h))
        written += 1

    return written


def export_focus_icon_assets(project, mod_dir: str) -> int:
    """Write the .dds for each focus that uses a CUSTOM imported icon. Returns
    the number of files written. Always runs (the focus tree is always part of
    the export)."""
    written = 0
    for focus in project.focuses:
        if not getattr(focus, "iconData", ""):
            continue
        img = _qimage_from_b64(focus.iconData)
        if img is None:
            continue
        bgra, w, h = _argb32_bytes(img)
        rel = _focus_icon_relpath(focus)
        path = os.path.join(mod_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, dds_bgra32(bgra, w, h))
        written += 1
    return written


def export_event_assets(project, mod_dir: str) -> int:
    """Write the .dds for each event that uses a CUSTOM imported picture. Returns
    the number of files written. Independent of country export (events are their
    own export section)."""
    written = 0
    for event in getattr(project, "events", None) or []:
        if not getattr(event, "pictureData", ""):
            continue
        img = _qimage_from_b64(event.pictureData)
        if img is None:
            continue
        bgra, w, h = _argb32_bytes(img)
        rel = _event_picture_relpath(event)
        path = os.path.join(mod_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, dds_bgra32(bgra, w, h))
        written += 1
    return written


def export_decision_assets(project, mod_dir: str) -> int:
    """Write the .dds for each decision that uses a CUSTOM imported icon. Returns
    the number of files written. Independent (decisions are their own section)."""
    written = 0
    for decision in getattr(project, "decisions", None) or []:
        if not getattr(decision, "iconData", ""):
            continue
        img = _qimage_from_b64(decision.iconData)
        if img is None:
            continue
        bgra, w, h = _argb32_bytes(img)
        rel = _decision_icon_relpath(decision)
        path = os.path.join(mod_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, dds_bgra32(bgra, w, h))
        written += 1
    return written
