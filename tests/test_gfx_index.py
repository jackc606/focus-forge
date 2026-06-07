"""Tests for the .gfx sprite-definition parser and icon resolution."""
from __future__ import annotations

import os

from core.gfx_index import build_sprite_index, parse_gfx_file, resolve_sprite

GFX = """
spriteTypes = {
\tspriteType = {
\t\tname = "GFX_focus_alpha"
\t\ttexturefile = "gfx/interface/goals/focus_alpha.dds"
\t}
\t# a commented-out sprite must be ignored
\t# spriteType = { name = "GFX_focus_ghost" texturefile = "x.dds" }
\tspriteType = {
\t\tname = GFX_focus_beta
\t\ttexturefile = gfx/interface/goals/focus_beta.dds
\t}
\tspriteType = {
\t\tname = "GFX_ARG_rw_gamma"
\t\ttexturefile = "gfx/interface/goals/argentina/ARG_rw_gamma.dds"
\t}
}
"""


def _write(tmp_path, rel, content):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_all_sprites_not_just_first(tmp_path):
    # Regression: the `spriteTypes = {` wrapper must not swallow the file into
    # one block (which previously yielded only the first sprite).
    f = _write(tmp_path, "interface/test.gfx", GFX)
    parsed = parse_gfx_file(str(f))
    assert set(parsed) == {"GFX_focus_alpha", "GFX_focus_beta", "GFX_ARG_rw_gamma"}


def test_comment_sprite_ignored(tmp_path):
    f = _write(tmp_path, "interface/test.gfx", GFX)
    parsed = parse_gfx_file(str(f))
    assert "GFX_focus_ghost" not in parsed


def test_quoted_and_unquoted_values(tmp_path):
    f = _write(tmp_path, "interface/test.gfx", GFX)
    parsed = parse_gfx_file(str(f))
    assert parsed["GFX_focus_beta"] == "gfx/interface/goals/focus_beta.dds"


def test_build_index_keeps_original_case_and_load_order(tmp_path):
    root_a = tmp_path / "base"
    root_b = tmp_path / "mod"
    _write(root_a, "interface/a.gfx",
           'spriteTypes = { spriteType = { name = "GFX_X" texturefile = "gfx/a.dds" } }')
    _write(root_b, "interface/b.gfx",
           'spriteTypes = { spriteType = { name = "GFX_X" texturefile = "gfx/b.dds" } }')
    idx = build_sprite_index([str(root_a), str(root_b)])
    orig, path = idx["gfx_x"]            # keyed lowercase, value keeps original case
    assert orig == "GFX_X"
    assert path == os.path.normpath(str(root_b / "gfx/b.dds"))  # later root wins


def test_resolve_prefix_variants(tmp_path):
    f = _write(tmp_path, "interface/test.gfx", GFX)
    idx = build_sprite_index([str(tmp_path)])
    # exact, and bare name resolved via the GFX_ prefix variant
    assert resolve_sprite(idx, "GFX_focus_alpha")
    assert resolve_sprite(idx, "ARG_rw_gamma")          # -> GFX_ARG_rw_gamma
    assert resolve_sprite(idx, "nope_missing") is None


# Millennium Dawn names focus sprites WITHOUT a GFX_ prefix and references them
# bare; the index must capture these (regression for ~98% icons not appearing).
BARE_GFX = """
spriteTypes = {
\tspriteType = {
\t\tname = "CUB_black_wasp"
\t\ttexturefile = "gfx/interface/goals/cuba/CUB_black_wasp.dds"
\t}
\tspriteType = {
\t\tname = "CUB_black_wasp_shine"
\t\ttexturefile = "gfx/interface/goals/cuba/CUB_black_wasp.dds"
\t\teffectfile = "gfx/FX/buttonstate.lua"
\t}
}
"""


def test_bare_named_sprite_indexed_and_resolves(tmp_path):
    f = _write(tmp_path, "interface/goals.gfx", BARE_GFX)
    parsed = parse_gfx_file(str(f))
    assert "CUB_black_wasp" in parsed                    # bare name captured
    idx = build_sprite_index([str(tmp_path)])
    path = resolve_sprite(idx, "CUB_black_wasp")         # focus references it bare
    assert path and path.endswith(os.path.normpath("goals/cuba/CUB_black_wasp.dds"))
