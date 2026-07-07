"""Opening the icon picker for a focus that already has an icon must show the
FULL browsable catalogue (with the current icon pinned + pre-selected), not
collapse to just the current icon."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.icon_picker import _NAME_ROLE, IconPickerDialog


def _app():
    return QApplication.instance() or QApplication([])


def _names(dlg):
    return [dlg._list.item(r).data(_NAME_ROLE) for r in range(dlg._list.count())]


def test_premade_focus_icon_does_not_collapse_grid():
    _app()
    sprites = [("CUB_black_wasp", "/x/a.dds")] + [
        (f"OTHER_{i}", f"/x/{i}.dds") for i in range(50)]
    dlg = IconPickerDialog(current="CUB_black_wasp", sprites=sprites)
    assert dlg._list.count() == 51            # whole catalogue, not 1
    sel = dlg._list.selectedItems()
    assert sel and sel[0].data(_NAME_ROLE) == "CUB_black_wasp"
    assert _names(dlg)[0] == "CUB_black_wasp"  # pinned to the front


def test_current_beyond_display_cap_is_pinned_and_selected():
    _app()
    sprites = [(f"GFX_focus_{i:04d}", f"/x/{i}.dds") for i in range(1000)]
    cur = "GFX_focus_0700"                     # would fall outside the 600 cap
    dlg = IconPickerDialog(current=cur, sprites=sprites)
    assert dlg._list.count() == 600
    assert _names(dlg)[0] == cur
    sel = dlg._list.selectedItems()
    assert sel and sel[0].data(_NAME_ROLE) == cur


def test_no_current_shows_catalogue_unpinned():
    _app()
    sprites = [(f"GFX_focus_{i}", f"/x/{i}.dds") for i in range(10)]
    dlg = IconPickerDialog(current="", sprites=sprites)
    assert dlg._list.count() == 10
    assert not dlg._list.selectedItems()


def test_search_still_filters():
    _app()
    sprites = [("GFX_army_reform", "/x/a.dds"), ("GFX_navy_reform", "/x/b.dds"),
               ("GFX_trade_deal", "/x/c.dds")]
    dlg = IconPickerDialog(current="GFX_army_reform", sprites=sprites)
    dlg._search.setText("navy")
    names = _names(dlg)
    assert names == ["GFX_navy_reform"]
