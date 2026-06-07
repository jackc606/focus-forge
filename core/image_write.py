"""Minimal uncompressed-image writers for HOI4 assets (Qt can read but not write
TGA, and there's no DDS writer). Input is raw BGRA8 (B,G,R,A per pixel, top-down
row order) — exactly what QImage.Format_ARGB32 exposes on a little-endian host."""
from __future__ import annotations

import struct


def tga_bgra32(bgra: bytes, width: int, height: int) -> bytes:
    """Uncompressed 32-bit TGA matching HOI4's flags: image type 2, BGRA, 8 alpha
    bits, bottom-left origin (descriptor 0x08), with the TrueVision 2.0 footer.
    Input ``bgra`` is top-down (QImage order); rows are flipped to bottom-up."""
    row = width * 4
    mv = memoryview(bgra)
    flipped = bytearray()
    for y in range(height - 1, -1, -1):
        flipped += mv[y * row:(y + 1) * row]
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0, 0, 2, 0, 0, 0, 0, 0, width, height, 32, 0x08)
    footer = struct.pack("<II", 0, 0) + b"TRUEVISION-XFILE.\x00"
    return header + bytes(flipped) + footer


def dds_bgra32(bgra: bytes, width: int, height: int) -> bytes:
    """Uncompressed A8R8G8B8 DDS (the format base-game HOI4 art uses)."""
    DDSD = 0x1 | 0x2 | 0x4 | 0x1000 | 0x8  # caps|height|width|pixelformat|pitch
    pitch = width * 4
    DDPF_RGB = 0x40
    DDPF_ALPHAPIXELS = 0x1
    # dwSize, dwFlags, dwHeight, dwWidth, dwPitch, dwDepth, dwMipMapCount, 11×reserved
    header = b"DDS " + struct.pack(
        "<7I11I",
        124, DDSD, height, width, pitch, 0, 0, *([0] * 11))
    pf = struct.pack(
        "<I I 4s I I I I I",
        32, DDPF_RGB | DDPF_ALPHAPIXELS, b"\x00\x00\x00\x00", 32,
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)  # R,G,B,A masks (BGRA mem)
    caps = struct.pack("<I I I I I", 0x1000, 0, 0, 0, 0)  # DDSCAPS_TEXTURE
    return header + pf + caps + bytes(bgra)
