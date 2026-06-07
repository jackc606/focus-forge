"""Parse HOI4 ``interface/*.gfx`` sprite definitions into a name → .dds map.

A sprite definition looks like::

    spriteType = {
        name = "GFX_focus_xyz"
        texturefile = "gfx/interface/goals/focus_xyz.dds"
    }

``build_sprite_index(roots)`` scans every ``.gfx`` under each root's ``interface``
folder and returns ``{lowercased_sprite_name: absolute_dds_path}``. Roots are
applied in order, so a later root (e.g. a submod) overrides an earlier one
(e.g. the base game) — matching HOI4 mod load order.
"""
from __future__ import annotations

import os
import re

_COMMENT = re.compile(r"#.*")
# Match the sprite's own name whether or not it carries a GFX_ prefix — Millennium
# Dawn names focus sprites bare (name = "CUB_black_wasp") and references them bare
# (icon = CUB_black_wasp). \b avoids matching keys like animation_name/maskfile.
_NAME = re.compile(r'\bname\s*=\s*"?([A-Za-z0-9_.\-]+)"?', re.IGNORECASE)
_TEX = re.compile(r'texturefile\s*=\s*(?:"([^"]+)"|([^\s}]+))', re.IGNORECASE)
# \b ensures the singular `spriteType` and not the `spriteTypes = {` wrapper
# (no word boundary between "spriteType" and the trailing "s").
_BLOCK_START = re.compile(r"\bspriteType\b\s*=\s*\{", re.IGNORECASE)


def _iter_sprite_blocks(text: str):
    """Yield the inner text of each ``spriteType = { ... }`` (brace-balanced)."""
    n = len(text)
    for m in _BLOCK_START.finditer(text):
        brace = m.end() - 1  # the "{" of this spriteType
        depth = 0
        j = brace
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield text[brace + 1:j]


def parse_gfx_file(path: str) -> dict:
    """Return {sprite_name(original case): texturefile(relative)} for one file."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError:
        return out
    text = _COMMENT.sub("", raw)
    for block in _iter_sprite_blocks(text):
        nm = _NAME.search(block)
        tx = _TEX.search(block)
        if not nm or not tx:
            continue
        tex = tx.group(1) or tx.group(2)
        out[nm.group(1)] = tex.replace("\\", "/").strip()
    return out


def build_sprite_index(roots) -> dict:
    """{lowercased GFX name: (original_name, absolute .dds path)}, later roots
    overriding earlier (HOI4 mod load order)."""
    index: dict = {}
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        interface = os.path.join(root, "interface")
        if not os.path.isdir(interface):
            continue
        for dirpath, _dirs, files in os.walk(interface):
            for fn in files:
                if fn.lower().endswith(".gfx"):
                    for name, tex in parse_gfx_file(os.path.join(dirpath, fn)).items():
                        index[name.lower()] = (name, os.path.normpath(os.path.join(root, tex)))
    return index


def resolve_sprite(index: dict, icon_value: str):
    """Map a focus's ``icon`` value to an absolute .dds path, trying common
    prefix variants. Returns the path (which may or may not exist) or None."""
    if not icon_value:
        return None
    v = icon_value.strip()
    candidates = [v, f"GFX_{v}", f"GFX_focus_{v}", f"GFX_goal_{v}"]
    if v.lower().startswith("gfx_"):
        candidates.append(v[4:])  # sprite may be named bare even if focus says GFX_
    for cand in candidates:
        hit = index.get(cand.lower())
        if hit:
            return hit[1]
    return None
