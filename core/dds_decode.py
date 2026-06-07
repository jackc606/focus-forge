"""Minimal pure-Python DDS decoder for HOI4 focus icons.

Supports the only formats HOI4 ships: uncompressed 24/32-bit RGB(A) (base game)
and BC1/BC2/BC3 (DXT1/3/5) block compression (mods). No third-party deps, so it
works inside the frozen .exe.

``decode_dds(data) -> (width, height, bgra)`` where ``bgra`` is a ``bytearray`` of
width*height*4 bytes in B, G, R, A order — i.e. ready to hand to a Qt
``QImage.Format_ARGB32`` on a little-endian machine.
"""
from __future__ import annotations

import struct

_DDPF_ALPHAPIXELS = 0x1
_DDPF_FOURCC = 0x4
_DDPF_RGB = 0x40


def decode_dds(data: bytes):
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    pf_flags = struct.unpack_from("<I", data, 80)[0]
    fourcc = data[84:88]
    rgb_bits = struct.unpack_from("<I", data, 88)[0]
    masks = struct.unpack_from("<IIII", data, 92)  # R, G, B, A
    if width <= 0 or height <= 0 or width * height > 8192 * 8192:
        return None

    off = 128
    if fourcc == b"DX10":
        return None  # DX10 header / BC7 etc. not supported

    if pf_flags & _DDPF_FOURCC:
        if fourcc == b"DXT1":
            return width, height, _decode_bc1(data, off, width, height)
        if fourcc == b"DXT3":
            return width, height, _decode_bc2(data, off, width, height)
        if fourcc == b"DXT5":
            return width, height, _decode_bc3(data, off, width, height)
        return None
    if pf_flags & _DDPF_RGB:
        return width, height, _decode_uncompressed(
            data, off, width, height, rgb_bits, masks, bool(pf_flags & _DDPF_ALPHAPIXELS))
    return None


# ---------------------------------------------------------------------------
# Uncompressed RGB / RGBA
# ---------------------------------------------------------------------------
def _mask_shift_scale(mask: int):
    if mask == 0:
        return 0, 0
    shift = (mask & -mask).bit_length() - 1   # trailing zero count
    bits = bin(mask >> shift).count("1")
    return shift, bits


def _decode_uncompressed(data, off, w, h, rgb_bits, masks, has_alpha):
    bpp = rgb_bits // 8
    if bpp not in (3, 4):
        return None
    rmask, gmask, bmask, amask = masks
    rs, rb = _mask_shift_scale(rmask)
    gs, gb = _mask_shift_scale(gmask)
    bs, bb = _mask_shift_scale(bmask)
    as_, ab = _mask_shift_scale(amask)
    out = bytearray(w * h * 4)
    pitch = w * bpp
    for y in range(h):
        row = off + y * pitch
        o = y * w * 4
        for x in range(w):
            p = row + x * bpp
            if bpp == 4:
                px = data[p] | (data[p + 1] << 8) | (data[p + 2] << 16) | (data[p + 3] << 24)
            else:
                px = data[p] | (data[p + 1] << 8) | (data[p + 2] << 16)
            r = ((px & rmask) >> rs)
            g = ((px & gmask) >> gs)
            b = ((px & bmask) >> bs)
            if rb and rb != 8:
                r = (r * 255) // ((1 << rb) - 1)
            if gb and gb != 8:
                g = (g * 255) // ((1 << gb) - 1)
            if bb and bb != 8:
                b = (b * 255) // ((1 << bb) - 1)
            a = 255
            if has_alpha and amask:
                a = ((px & amask) >> as_)
                if ab and ab != 8:
                    a = (a * 255) // ((1 << ab) - 1)
            out[o] = b; out[o + 1] = g; out[o + 2] = r; out[o + 3] = a
            o += 4
    return out


# ---------------------------------------------------------------------------
# Block-compressed BC1 / BC2 / BC3
# ---------------------------------------------------------------------------
def _rgb565(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return (r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31


def _color_palette(c0, c1, punchthrough):
    r0, g0, b0 = _rgb565(c0)
    r1, g1, b1 = _rgb565(c1)
    pal = [(r0, g0, b0, 255), (r1, g1, b1, 255), None, None]
    if c0 > c1 or not punchthrough:
        pal[2] = ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255)
        pal[3] = ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255)
    else:
        pal[2] = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255)
        pal[3] = (0, 0, 0, 0)  # transparent (BC1 1-bit alpha)
    return pal


def _put(out, w, h, bx, by, x, y, r, g, b, a):
    px = bx + x
    py = by + y
    if px >= w or py >= h:
        return
    o = (py * w + px) * 4
    out[o] = b; out[o + 1] = g; out[o + 2] = r; out[o + 3] = a


def _decode_bc1(data, off, w, h):
    out = bytearray(w * h * 4)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            c0, c1, bits = struct.unpack_from("<HHI", data, p)
            p += 8
            pal = _color_palette(c0, c1, punchthrough=True)
            for i in range(16):
                r, g, b, a = pal[(bits >> (2 * i)) & 0x3]
                _put(out, w, h, bx, by, i & 3, i >> 2, r, g, b, a)
    return out


def _decode_bc2(data, off, w, h):
    out = bytearray(w * h * 4)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alpha = struct.unpack_from("<Q", data, p)[0]
            c0, c1, bits = struct.unpack_from("<HHI", data, p + 8)
            p += 16
            pal = _color_palette(c0, c1, punchthrough=False)
            for i in range(16):
                r, g, b, _ = pal[(bits >> (2 * i)) & 0x3]
                a = ((alpha >> (4 * i)) & 0xF) * 17
                _put(out, w, h, bx, by, i & 3, i >> 2, r, g, b, a)
    return out


def _decode_bc3(data, off, w, h):
    out = bytearray(w * h * 4)
    p = off
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            a0 = data[p]
            a1 = data[p + 1]
            abits = int.from_bytes(data[p + 2:p + 8], "little")
            c0, c1, bits = struct.unpack_from("<HHI", data, p + 8)
            p += 16
            apal = _alpha_palette(a0, a1)
            pal = _color_palette(c0, c1, punchthrough=False)
            for i in range(16):
                r, g, b, _ = pal[(bits >> (2 * i)) & 0x3]
                a = apal[(abits >> (3 * i)) & 0x7]
                _put(out, w, h, bx, by, i & 3, i >> 2, r, g, b, a)
    return out


def _alpha_palette(a0, a1):
    pal = [a0, a1, 0, 0, 0, 0, 0, 0]
    if a0 > a1:
        for i in range(1, 7):
            pal[i + 1] = ((7 - i) * a0 + i * a1) // 7
    else:
        for i in range(1, 5):
            pal[i + 1] = ((5 - i) * a0 + i * a1) // 5
        pal[6] = 0
        pal[7] = 255
    return pal
