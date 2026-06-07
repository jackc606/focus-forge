"""Tests for default-flag resolution."""
from __future__ import annotations

from ui.flag_files import default_flag


def _flags(tmp_path, names):
    fd = tmp_path / "gfx" / "flags"
    fd.mkdir(parents=True)
    for n in names:
        (fd / n).write_bytes(b"\x00")
    return str(tmp_path)


def test_prefers_ruling_ideology_variant(tmp_path):
    root = _flags(tmp_path, ["USA.tga", "USA_democratic.tga", "USA_communism.tga"])
    p = default_flag([root], "USA", "communism")
    assert p.endswith("USA_communism.tga")


def test_falls_back_to_base_then_any_ideology(tmp_path):
    root = _flags(tmp_path, ["USA.tga"])
    assert default_flag([root], "USA", "communism").endswith("USA.tga")
    root2 = _flags(tmp_path / "b", ["LBA_neutrality.tga"])
    assert default_flag([root2], "LBA", "fascism").endswith("LBA_neutrality.tga")


def test_later_root_wins(tmp_path):
    base = _flags(tmp_path / "vanilla", ["USA_democratic.tga"])
    mod = _flags(tmp_path / "mod", ["USA_democratic.tga"])
    p = default_flag([base, mod], "USA", "democratic")
    assert "mod" in p   # mod override


def test_missing_returns_none(tmp_path):
    root = _flags(tmp_path, ["USA_democratic.tga"])
    assert default_flag([root], "ZZZ", "neutrality") is None
    assert default_flag([root], "", "neutrality") is None
