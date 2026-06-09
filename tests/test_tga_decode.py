"""Pure-Python TGA reader — the variants Qt's plugin rejects (24-bpp, top-origin,
RLE) must decode, since ~11% of MD's flag TGAs use them."""
from __future__ import annotations

import struct

from core.tga_decode import decode_tga


def _header(imgtype, w, h, bpp, desc):
    return struct.pack("<BBBHHBHHHHBB", 0, 0, imgtype, 0, 0, 0, 0, 0, w, h, bpp, desc)


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_bytes(payload)
    return str(p)


def test_uncompressed_32bpp_bottom_origin(tmp_path):
    # 2x1: pixel0 = blue, pixel1 = red (TGA stores B,G,R,A). Bottom origin (desc=0).
    body = bytes([255, 0, 0, 0]) + bytes([0, 0, 255, 0])
    path = _write(tmp_path, "a.tga", _header(2, 2, 1, 32, 0) + body)
    w, h, bgra = decode_tga(path)
    assert (w, h) == (2, 1)
    # alpha forced opaque; order preserved (single row)
    assert bgra[0:4] == bytes([255, 0, 0, 255])   # blue, opaque
    assert bgra[4:8] == bytes([0, 0, 255, 255])   # red, opaque


def test_uncompressed_24bpp(tmp_path):
    body = bytes([10, 20, 30]) + bytes([40, 50, 60])  # BGR, BGR
    path = _write(tmp_path, "b.tga", _header(2, 2, 1, 24, 0) + body)
    w, h, bgra = decode_tga(path)
    assert (w, h) == (2, 1)
    assert bgra[0:4] == bytes([10, 20, 30, 255])
    assert bgra[4:8] == bytes([40, 50, 60, 255])


def test_top_origin_flips(tmp_path):
    # 1x2, top origin (desc bit5). Row0 = green, row1 = blue, top-to-bottom as stored.
    row0 = bytes([0, 255, 0, 0])
    row1 = bytes([255, 0, 0, 0])
    path = _write(tmp_path, "c.tga", _header(2, 1, 2, 32, 0x20) + row0 + row1)
    w, h, bgra = decode_tga(path)
    assert (w, h) == (1, 2)
    assert bgra[0:4] == bytes([0, 255, 0, 255])   # top row stays top
    assert bgra[4:8] == bytes([255, 0, 0, 255])


def test_rle_32bpp(tmp_path):
    # RLE run of 3 identical red pixels: packet 0x82 (run, count 3) + one pixel.
    body = bytes([0x82]) + bytes([0, 0, 255, 0])
    path = _write(tmp_path, "d.tga", _header(10, 3, 1, 32, 0) + body)
    w, h, bgra = decode_tga(path)
    assert (w, h) == (3, 1)
    assert bgra == bytes([0, 0, 255, 255]) * 3


def test_unsupported_returns_none(tmp_path):
    # colormapped (cmaptype=1) → unsupported
    bad = struct.pack("<BBBHHBHHHHBB", 0, 1, 1, 0, 256, 24, 0, 0, 2, 1, 8, 0)
    path = _write(tmp_path, "e.tga", bad + b"\x00" * 64)
    assert decode_tga(path) is None
    assert decode_tga(str(tmp_path / "missing.tga")) is None
