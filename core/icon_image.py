"""Chroma-key maths for generated focus icons — Qt-free, pure Python on raw RGBA.

Why raw bytes and no image library: Pillow is not a Focus Forge dependency
(images are decoded by Qt in the UI layer and written by ``core.image_write``),
and core must stay Qt-free so this is unit-testable without a QApplication.
The UI wrapper (``ui/icon_image.py``) decodes / resizes / encodes with QImage
and hands the pixel work here. Input ``rgba`` is top-down R,G,B,A bytes.

The image model is asked for a flat pure-magenta background; a pixel is
"magenta-like" when its HSV hue is within ±25° of 300°, saturation ≥ 0.35 and
value ≥ 0.25. Only magenta-like pixels connected to the border are treated as
background, so a magenta accent inside the subject (a flag stripe) survives.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

# Opaque pixels this close (Chebyshev) to background get their magenta spill
# desaturated; anti-aliased edges otherwise keep a pink halo in-game.
SPILL_RADIUS_PX = 2
SPILL_DESATURATE = 0.4
# ">97% background" means the model returned an empty canvas.
EMPTY_FRACTION = 0.97
TRIM_PAD_FRACTION = 0.04


@dataclass
class KeyResult:
    rgba: bytes                       # background pixels fully transparent (RGB zeroed)
    bbox: Optional[tuple]             # (x0, y0, x1, y1) exclusive, of opaque pixels; None if empty
    background_fraction: float        # keyed-and-border-connected pixels / all pixels


def is_magenta_like(r: int, g: int, b: int) -> bool:
    """HSV test rewritten in integers. Magenta sits between blue (240°) and
    red (360°): with blue dominant hue = 240 + 60*(r-g)/d, with red dominant
    hue = 360 - 60*(b-g)/d, so 275°..325° is 12*(min(r,b) - g) >= 7*d in both
    cases once green is not the dominant channel. S ≥ 0.35 is
    100*(max-min) >= 35*max and V ≥ 0.25 is max >= 64."""
    hi = b if b >= r else r
    if g > hi or hi < 64:
        return False
    lo = g if g < r and g < b else (r if r < b else b)
    d = hi - lo
    if 100 * d < 35 * hi:
        return False
    return 12 * ((r if r < b else b) - g) >= 7 * d


def key_mask(rgba: bytes, w: int, h: int) -> bytearray:
    """1 per pixel that is magenta-like (or already transparent)."""
    n = w * h
    mask = bytearray(n)
    magenta = is_magenta_like
    for i in range(n):
        o = i * 4
        if rgba[o + 3] < 128 or magenta(rgba[o], rgba[o + 1], rgba[o + 2]):
            mask[i] = 1
    return mask


def background_mask(mask: bytearray, w: int, h: int) -> bytearray:
    """Keyed pixels reachable from the border (4-connected flood fill seeded
    from every keyed edge pixel — a superset of the four corners, so a subject
    that touches one edge still keys the rest of the border)."""
    n = w * h
    bg = bytearray(n)
    todo = deque()
    for x in range(w):
        todo.append(x)
        todo.append((h - 1) * w + x)
    for y in range(1, h - 1):
        todo.append(y * w)
        todo.append(y * w + w - 1)
    while todo:
        i = todo.popleft()
        if bg[i] or not mask[i]:
            continue
        bg[i] = 1
        x = i % w
        if x > 0:
            todo.append(i - 1)
        if x < w - 1:
            todo.append(i + 1)
        if i >= w:
            todo.append(i - w)
        if i + w < n:
            todo.append(i + w)
    return bg


def _desaturate(out: bytearray, o: int) -> None:
    r, g, b = out[o], out[o + 1], out[o + 2]
    grey = (r * 299 + g * 587 + b * 114) // 1000
    k = int(SPILL_DESATURATE * 10)
    out[o] = r + ((grey - r) * k) // 10
    out[o + 1] = g + ((grey - g) * k) // 10
    out[o + 2] = b + ((grey - b) * k) // 10


def _suppress_spill(out: bytearray, bg: bytearray, w: int, h: int) -> None:
    """Walk only the background pixels that border the subject (perimeter-sized)
    and desaturate the opaque pixels within SPILL_RADIUS_PX of each — far
    cheaper than testing every pixel's neighbourhood."""
    n = w * h
    done = bytearray(n)
    rad = SPILL_RADIUS_PX
    for i in range(n):
        if not bg[i]:
            continue
        x, y = i % w, i // w
        if not ((x > 0 and not bg[i - 1]) or (x < w - 1 and not bg[i + 1])
                or (y > 0 and not bg[i - w]) or (y < h - 1 and not bg[i + w])):
            continue
        for yy in range(max(0, y - rad), min(h, y + rad + 1)):
            row = yy * w
            for xx in range(max(0, x - rad), min(w, x + rad + 1)):
                j = row + xx
                if bg[j] or done[j]:
                    continue
                done[j] = 1
                _desaturate(out, j * 4)


def _opaque_bbox(bg: bytearray, w: int, h: int) -> Optional[tuple]:
    """Bounding box of non-background pixels, using C-speed find/rfind per row."""
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        row = bytes(bg[y * w:(y + 1) * w])
        first = row.find(b"\x00")
        if first < 0:
            continue
        last = row.rfind(b"\x00")
        x0, x1 = min(x0, first), max(x1, last)
        y0, y1 = min(y0, y), max(y1, y)
    if x1 < 0:
        return None
    return (x0, y0, x1 + 1, y1 + 1)


def key_image(rgba: bytes, w: int, h: int) -> KeyResult:
    """Key, flood-fill, spill-suppress and measure in one pass over the pixels."""
    mask = key_mask(rgba, w, h)
    bg = background_mask(mask, w, h)
    out = bytearray(rgba)
    for i in range(w * h):
        if bg[i]:
            o = i * 4
            out[o] = out[o + 1] = out[o + 2] = out[o + 3] = 0
    _suppress_spill(out, bg, w, h)
    fraction = bg.count(1) / float(w * h) if w * h else 1.0
    return KeyResult(rgba=bytes(out), bbox=_opaque_bbox(bg, w, h),
                     background_fraction=fraction)


def padded_bbox(bbox: tuple, w: int, h: int, pad: float = TRIM_PAD_FRACTION) -> tuple:
    """Grow the trim box by ``pad`` of its own size each side, clamped to the image."""
    x0, y0, x1, y1 = bbox
    px = max(1, int(round((x1 - x0) * pad)))
    py = max(1, int(round((y1 - y0) * pad)))
    return (max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py))


def fit_size(src_w: int, src_h: int, target: tuple) -> tuple:
    """Largest size with the source aspect that fits inside ``target``."""
    tw, th = target
    scale = min(tw / float(src_w), th / float(src_h))
    return (max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale))))
