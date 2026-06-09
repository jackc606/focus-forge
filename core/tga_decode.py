"""Minimal pure-Python TGA reader for HOI4 flags.

Qt's built-in TGA plugin only reliably reads 32-bpp bottom-origin images and
fails on the 24-bpp, top-origin, and RLE variants that appear throughout MD's
gfx/flags (~11% of them). This decoder covers uncompressed (type 2) and
run-length-encoded (type 10) truecolor TGAs at 24 or 32 bpp, honoring the origin
bit. Returns ``(width, height, bgra_bytes)`` (top-to-bottom, B,G,R,A per pixel —
matching ``QImage.Format_ARGB32``), or None if unsupported/unreadable.
"""
from __future__ import annotations

import struct


def _rle_decode(data: bytes, off: int, total: int, bpp: int):
    out = bytearray(total)
    i, o, n = off, 0, len(data)
    while o < total and i < n:
        packet = data[i]
        i += 1
        count = (packet & 0x7F) + 1
        if packet & 0x80:  # run-length packet: one pixel repeated
            if i + bpp > n:
                break
            px = data[i:i + bpp]
            i += bpp
            for _ in range(count):
                if o + bpp > total:
                    break
                out[o:o + bpp] = px
                o += bpp
        else:  # raw packet: `count` literal pixels
            length = count * bpp
            if i + length > n:
                length = n - i
            out[o:o + length] = data[i:i + length]
            i += length
            o += length
    return out if o >= total else None


def decode_tga(path: str):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) < 18:
        return None
    idlen, cmaptype, imgtype = data[0], data[1], data[2]
    w = struct.unpack_from("<H", data, 12)[0]
    h = struct.unpack_from("<H", data, 14)[0]
    bpp, desc = data[16], data[17]
    if cmaptype != 0 or imgtype not in (2, 10) or bpp not in (24, 32) or not w or not h:
        return None

    off = 18 + idlen
    bytespp = bpp // 8
    total = w * h * bytespp
    if imgtype == 2:
        raw = data[off:off + total]
        if len(raw) < total:
            return None
    else:
        raw = _rle_decode(data, off, total, bytespp)
        if raw is None:
            return None

    # Normalise to BGRA (TGA truecolor is already B,G,R[,A]); force opaque alpha
    # since HOI4 flag alpha is unused and sometimes zero (which would render blank).
    npx = w * h
    bgra = bytearray(npx * 4)
    if bytespp == 4:
        bgra[:] = raw
        for i in range(3, npx * 4, 4):
            bgra[i] = 255
    else:
        j = 0
        for i in range(0, total, 3):
            bgra[j] = raw[i]
            bgra[j + 1] = raw[i + 1]
            bgra[j + 2] = raw[i + 2]
            bgra[j + 3] = 255
            j += 4

    # TGA rows are bottom-to-top unless the origin bit (desc bit 5) is set.
    if not (desc & 0x20):
        rowbytes = w * 4
        flipped = bytearray(npx * 4)
        for y in range(h):
            s = (h - 1 - y) * rowbytes
            flipped[y * rowbytes:(y + 1) * rowbytes] = bgra[s:s + rowbytes]
        bgra = flipped
    return w, h, bytes(bgra)
