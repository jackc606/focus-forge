"""Tests for the MD leader-portrait image index + export sprite generation."""
from __future__ import annotations

from core.portrait_index import build_leader_portraits, resolve_portrait


def _mod_root(tmp_path, tag, files, *, descriptor=True):
    root = tmp_path / ("mod" if descriptor else "vanilla")
    d = root / "gfx" / "leaders" / tag
    d.mkdir(parents=True)
    for fn in files:
        (d / fn).write_bytes(b"\x00")
    if descriptor:
        (root / "descriptor.mod").write_text('name="M"\n', encoding="utf-8")
    return str(root)


def test_lists_country_portraits(tmp_path):
    root = _mod_root(tmp_path, "USA", ["Donald_Trump.dds", "Joe_Biden.dds"])
    ports = build_leader_portraits([root], "USA")
    rels = {r for r, _a, _l in ports}
    assert rels == {"gfx/leaders/USA/Donald_Trump.dds", "gfx/leaders/USA/Joe_Biden.dds"}
    labels = [lbl for _r, _a, lbl in ports]
    assert labels == ["Donald_Trump", "Joe_Biden"]  # sorted by label


def test_skips_small_thumbnails(tmp_path):
    root = _mod_root(tmp_path, "USA", ["Trump.dds"])
    small = tmp_path / "mod" / "gfx" / "leaders" / "USA" / "small"
    small.mkdir()
    (small / "Trump_small.dds").write_bytes(b"\x00")
    ports = build_leader_portraits([root], "USA")
    assert [r for r, _a, _l in ports] == ["gfx/leaders/USA/Trump.dds"]  # small/ excluded


def test_excludes_vanilla_root_without_descriptor(tmp_path):
    vanilla = _mod_root(tmp_path, "USA", ["Vanilla_FDR.dds"], descriptor=False)
    mod = _mod_root(tmp_path, "USA", ["Donald_Trump.dds"])
    ports = build_leader_portraits([vanilla, mod], "USA")
    rels = {r for r, _a, _l in ports}
    assert rels == {"gfx/leaders/USA/Donald_Trump.dds"}  # vanilla (no descriptor.mod) excluded


def test_missing_country_and_blank_tag(tmp_path):
    root = _mod_root(tmp_path, "USA", ["Trump.dds"])
    assert build_leader_portraits([root], "ZZZ") == []
    assert build_leader_portraits([root], "") == []


def test_resolve_portrait(tmp_path):
    root = _mod_root(tmp_path, "USA", ["Trump.dds"])
    assert resolve_portrait([root], "gfx/leaders/USA/Trump.dds") is not None
    assert resolve_portrait([root], "gfx/leaders/USA/missing.dds") is None


def test_export_generates_sprite_for_path_pictureref():
    from core.exporters import (export_country_history,
                                export_leader_portrait_sprites)
    from core.types import (CountryData, ExportSettings, FocusForgeProject,
                            LeaderData)
    proj = FocusForgeProject(
        countryTag="USA", treeId="t",
        country=CountryData(leaders=[
            LeaderData(name="Donald Trump", ideology="conservatism",
                       pictureRef="gfx/leaders/USA/Donald_Trump.dds"),
            LeaderData(name="Legacy", ideology="conservatism",
                       pictureRef="GFX_old_sprite")]),
        exportSettings=ExportSettings(localisationPrefix="USA", includeCountry=True))
    hist = export_country_history(proj)
    assert 'picture = "GFX_USA_donald_trump"' in hist   # path -> generated sprite
    assert 'picture = "GFX_old_sprite"' in hist          # legacy GFX name unchanged
    gfx = export_leader_portrait_sprites(proj)
    assert 'name = "GFX_USA_donald_trump"' in gfx
    assert 'texturefile = "gfx/leaders/USA/Donald_Trump.dds"' in gfx
    assert "GFX_old_sprite" not in gfx                   # only path portraits wrapped


def test_export_no_sprites_when_no_path_portraits():
    from core.exporters import export_leader_portrait_sprites
    from core.types import CountryData, FocusForgeProject, LeaderData
    proj = FocusForgeProject(countryTag="USA", treeId="t",
                             country=CountryData(leaders=[
                                 LeaderData(name="X", pictureRef="GFX_x")]))
    assert export_leader_portrait_sprites(proj) is None
