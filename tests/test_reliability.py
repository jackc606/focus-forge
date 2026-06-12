"""Reliability hardening: atomic writes, corrupt-input handling, decoder
bounds, parser guards, and the focus-id index."""
from __future__ import annotations

import struct

import pytest

from core.dds_decode import decode_dds
from core.file_io import atomic_write_bytes, atomic_write_text
from core.gfx_index import parse_gfx_file
from core.pdx_loc import load_english_localisation
from core.types import ExportSettings, FocusForgeProject


# ----- atomic writes -----
def test_atomic_write_creates_and_overwrites(tmp_path):
    target = tmp_path / "out.json"
    atomic_write_bytes(target, b"first")
    assert target.read_bytes() == b"first"
    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    # no temp sibling left behind
    assert list(tmp_path.iterdir()) == [target]


# ----- project save/load -----
def _model():
    from ui.project_model import ProjectModel
    return ProjectModel()


def test_save_load_round_trip(tmp_path):
    m = _model()
    path = tmp_path / "proj.focusforge.json"
    m.save_to_file(path)
    assert not (tmp_path / "proj.focusforge.json.tmp").exists()
    m2 = _model()
    m2.load_from_file(path)
    assert m2.project.treeId == m.project.treeId


def test_corrupt_project_load_raises_friendly_error(tmp_path):
    path = tmp_path / "broken.focusforge.json"
    path.write_bytes(b'{"projectName": "tru')  # truncated mid-save (old behavior)
    m = _model()
    with pytest.raises(ValueError) as exc:
        m.load_from_file(path)
    assert "corrupt" in str(exc.value)


# ----- DDS decoder bounds -----
def _dds_header(width: int, height: int, fourcc: bytes = b"DXT1") -> bytes:
    h = bytearray(128)
    h[0:4] = b"DDS "
    struct.pack_into("<I", h, 12, height)
    struct.pack_into("<I", h, 16, width)
    struct.pack_into("<I", h, 80, 0x4)  # DDPF_FOURCC
    h[84:88] = fourcc
    return bytes(h)


def test_truncated_bc1_returns_none_instead_of_crashing():
    # Header claims 64x64 (needs 2048 payload bytes) but carries none.
    assert decode_dds(_dds_header(64, 64, b"DXT1")) is None
    assert decode_dds(_dds_header(64, 64, b"DXT5")) is None


def test_valid_tiny_bc1_still_decodes():
    # 4x4 BC1 = one 8-byte block.
    block = struct.pack("<HHI", 0xFFFF, 0x0000, 0)  # palette idx 0 everywhere
    out = decode_dds(_dds_header(4, 4) + block)
    assert out is not None
    w, h, bgra = out
    assert (w, h) == (4, 4)
    assert len(bgra) == 4 * 4 * 4


# ----- gfx parser: unbalanced braces don't pollute the index -----
def test_unbalanced_gfx_block_is_skipped(tmp_path):
    gfx = tmp_path / "broken.gfx"
    gfx.write_text(
        'spriteTypes = {\n'
        '  spriteType = {\n'
        '    name = "GFX_good"\n'
        '    texturefile = "gfx/good.dds"\n'
        '  }\n'
        '  spriteType = {\n'                       # never closed
        '    name = "GFX_dangling"\n'
        '    texturefile = "gfx/dangling.dds"\n',
        encoding="utf-8")
    out = parse_gfx_file(str(gfx))
    assert "GFX_good" in out
    assert "GFX_dangling" not in out


# ----- localisation encoding fallback -----
def test_cp1252_localisation_survives(tmp_path):
    loc = tmp_path / "localisation"
    loc.mkdir()
    (loc / "old_l_english.yml").write_bytes(
        'l_english:\n my_key:0 "François"\n'.encode("cp1252"))
    found = load_english_localisation([str(tmp_path)], {"my_key"})
    assert found.get("my_key") == "François"


# ----- focus-id index -----
def test_find_focus_index_tracks_add_rename_delete():
    m = _model()
    new_id = m.add_focus()
    assert m.find_focus(new_id) is not None
    final = m.rename_focus(new_id, "ZZZ_renamed")
    assert m.find_focus(final) is not None
    assert m.find_focus(new_id) is None
    m.delete_focus(final)
    assert m.find_focus(final) is None


def test_export_to_directory_is_atomic_per_file(tmp_path):
    m = _model()
    m.project.exportSettings = ExportSettings(
        focusFileName="t_focus", localisationPrefix="t_forge")
    count = m.export_to_directory(tmp_path)
    assert count >= 2
    leftovers = [p for p in tmp_path.rglob("*.tmp")]
    assert leftovers == []


# ----- state-building reward: slot line only for slot-consuming factories -----
def test_state_building_infrastructure_has_no_free_slot():
    from core.reward_presets import build_reward_item_lines
    from core.types import RewardItem
    lines = build_reward_item_lines(RewardItem(
        kind="state_building", enabled=True,
        params={"state": 123, "building": "infrastructure", "level": 2}))
    text = "\n".join(lines)
    assert "123 = {" in text
    assert "add_building_construction = { type = infrastructure level = 2 instant_build = yes }" in text
    assert "add_extra_state_shared_building_slots" not in text


def test_state_building_factory_still_gets_slot():
    from core.reward_presets import build_reward_item_lines
    from core.types import RewardItem
    lines = build_reward_item_lines(RewardItem(
        kind="state_building", enabled=True,
        params={"state": 5, "building": "industrial_complex", "level": 1}))
    text = "\n".join(lines)
    assert "add_extra_state_shared_building_slots = 1" in text
    assert "type = industrial_complex" in text


# ----- localisation: later roots still override earlier ones (early-exit walk) -----
def test_localisation_later_root_still_wins(tmp_path):
    base = tmp_path / "base" / "localisation"
    mod = tmp_path / "mod" / "localisation"
    base.mkdir(parents=True)
    mod.mkdir(parents=True)
    (base / "a_l_english.yml").write_text(
        'l_english:\n k1:0 "base"\n k2:0 "base-only"\n', encoding="utf-8")
    (mod / "b_l_english.yml").write_text(
        'l_english:\n k1:0 "mod"\n', encoding="utf-8")
    found = load_english_localisation(
        [str(tmp_path / "base"), str(tmp_path / "mod")], {"k1", "k2"})
    assert found == {"k1": "mod", "k2": "base-only"}


# ----- bulk event reference counts match the per-event counter -----
def test_event_reference_counts_bulk_matches_single():
    from core.types import CompletionReward, EventReward, FocusNodeData, FocusPosition
    m = _model()
    m.project.focuses.append(FocusNodeData(
        id="X_f", title="F", position=FocusPosition(0, 9),
        completionReward=CompletionReward(events=[
            EventReward(id="ns.1"), EventReward(id="ns.1"), EventReward(id="ns.2")])))
    counts = m.event_reference_counts()
    assert counts["ns.1"] == m.event_reference_count("ns.1") == 2
    assert counts["ns.2"] == m.event_reference_count("ns.2") == 1
