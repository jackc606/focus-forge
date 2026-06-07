"""Steam library discovery for auto-detecting HOI4 + Millennium Dawn."""
from __future__ import annotations

from ui.icon_provider import _find_millennium_dawn, _parse_libraryfolders

_VDF = r'''
"libraryfolders"
{
    "0"
    {
        "path"		"C:\\Program Files (x86)\\Steam"
        "label"		""
    }
    "1"
    {
        "path"		"F:\\Games\\SteamLibrary"
    }
}
'''


def test_parse_libraryfolders():
    paths = _parse_libraryfolders(_VDF)
    assert paths == ["C:\\Program Files (x86)\\Steam", "F:\\Games\\SteamLibrary"]


def _workshop_item(tmp_path, lib, item_id, descriptor_name=None):
    d = tmp_path / lib / "steamapps" / "workshop" / "content" / "394360" / item_id
    d.mkdir(parents=True)
    if descriptor_name is not None:
        (d / "descriptor.mod").write_text(f'name="{descriptor_name}"\n', encoding="utf-8")
    return str(tmp_path / lib / "steamapps")


def test_find_md_known_id(tmp_path):
    sa = _workshop_item(tmp_path, "lib", "2777392649", "Millennium Dawn: A Modern Day Mod")
    md = _find_millennium_dawn([sa])
    assert md.endswith("2777392649")


def test_find_md_by_descriptor_for_fork(tmp_path):
    # a different workshop id, but the descriptor names Millennium Dawn
    sa = _workshop_item(tmp_path, "lib", "9999999999", "Millennium Dawn Expanded")
    md = _find_millennium_dawn([sa])
    assert md.endswith("9999999999")


def test_find_md_prefers_known_id(tmp_path):
    base = tmp_path / "lib" / "steamapps" / "workshop" / "content" / "394360"
    (base / "2777392649").mkdir(parents=True)
    (base / "1111").mkdir()
    (base / "1111" / "descriptor.mod").write_text('name="Millennium Dawn fork"\n', encoding="utf-8")
    md = _find_millennium_dawn([str(tmp_path / "lib" / "steamapps")])
    assert md.endswith("2777392649")   # canonical id wins over a fork


def test_find_md_none(tmp_path):
    sa = _workshop_item(tmp_path, "lib", "12345", "Some Other Mod")
    assert _find_millennium_dawn([sa]) is None
