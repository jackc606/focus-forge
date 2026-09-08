"""Generated-icon post-processing: key out the magenta, trim, fit to 100×88.

Why here and not in core: Pillow isn't a dependency, so decoding, smooth
resampling and PNG encoding use QImage (the same decoder that renders
``iconData`` on the canvas and at export). The pixel maths itself lives in
``core.icon_image`` and stays Qt-free / unit-testable.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from core.icon_image import EMPTY_FRACTION, fit_size, key_image, padded_bbox

ICON_SIZE = (100, 88)   # what 1,869 of 2,954 vanilla goal icons are; MD matches
# Keying runs in pure Python; a 1024² image would take ~10 s per icon and hog
# the GIL, so the source is first smooth-downscaled to at most this — still
# 5× oversampled against the 100×88 result, so edges stay anti-aliased.
_KEY_MAX_PX = 512

EMPTY_IMAGE_TEXT = "the image came back empty"


class EmptyImageError(ValueError):
    """The model returned (almost) nothing but background."""


def _decode(png_bytes: bytes) -> QImage:
    img = QImage()
    if not png_bytes or not img.loadFromData(bytes(png_bytes)):
        raise ValueError("The image could not be decoded.")
    if max(img.width(), img.height()) > _KEY_MAX_PX:
        img = img.scaled(_KEY_MAX_PX, _KEY_MAX_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return img.convertToFormat(QImage.Format_RGBA8888)


def _rgba_bytes(img: QImage) -> bytes:
    """Tightly packed RGBA rows (QImage pads bytesPerLine to 4, so copy per row)."""
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    raw = bytes(img.constBits())
    if bpl == w * 4:
        return raw[:w * h * 4]
    return b"".join(raw[y * bpl:y * bpl + w * 4] for y in range(h))


def _keyed(png_bytes: bytes):
    img = _decode(png_bytes)
    w, h = img.width(), img.height()
    return key_image(_rgba_bytes(img), w, h), w, h


def is_mostly_background(png_bytes: bytes) -> bool:
    """True when the keyed background covers more than EMPTY_FRACTION of the
    image — the model returned nothing worth keeping."""
    try:
        result, _w, _h = _keyed(png_bytes)
    except ValueError:
        return True
    return result.bbox is None or result.background_fraction > EMPTY_FRACTION


def _png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def process_icon(png_bytes: bytes, target: tuple = ICON_SIZE) -> bytes:
    """Key, trim (4% pad), fit into ``target`` preserving aspect, centre on a
    transparent canvas; returns RGBA PNG bytes. Raises :class:`EmptyImageError`
    when the picture is essentially all background and ``ValueError`` when it
    can't be decoded."""
    result, w, h = _keyed(png_bytes)
    if result.bbox is None or result.background_fraction > EMPTY_FRACTION:
        raise EmptyImageError(EMPTY_IMAGE_TEXT)
    keyed = QImage(result.rgba, w, h, w * 4, QImage.Format_RGBA8888).copy()
    x0, y0, x1, y1 = padded_bbox(result.bbox, w, h)
    cropped = keyed.copy(QRect(x0, y0, x1 - x0, y1 - y0))
    # Premultiplied while resampling so transparent (zeroed) pixels don't
    # darken the subject's edge.
    fw, fh = fit_size(cropped.width(), cropped.height(), target)
    fitted = cropped.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(
        fw, fh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    canvas = QImage(target[0], target[1], QImage.Format_ARGB32_Premultiplied)
    canvas.fill(QColor(0, 0, 0, 0))
    painter = QPainter(canvas)
    painter.drawImage((target[0] - fw) // 2, (target[1] - fh) // 2, fitted)
    painter.end()
    return _png_bytes(canvas.convertToFormat(QImage.Format_ARGB32))
