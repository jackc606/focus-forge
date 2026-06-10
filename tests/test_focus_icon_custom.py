"""Custom imported focus icons: icon = generated sprite, .gfx emission, round-trip."""
from __future__ import annotations

from core.exporters import (
    export_focus_icon_sprites,
    export_focus_tree,
    export_project_files,
)
from core.serialization import project_from_dict, project_to_dict
from core.types import ExportSettings, FocusForgeProject, FocusNodeData


def _project(*focuses: FocusNodeData) -> FocusForgeProject:
    return FocusForgeProject(
        countryTag="LBA", projectName="Libya Expanded", treeId="lba_focus",
        focuses=list(focuses),
        exportSettings=ExportSettings(modPrefix="LBA", focusFileName="lba_focus",
                                      localisationPrefix="LBA_forge"),
    )


def _custom_icon_focus() -> FocusNodeData:
    return FocusNodeData(id="LBA_new_dawn", title="New Dawn",
                         icon="GFX_goal_generic_construct_civilian",
                         iconData="ZmFrZWltYWdl")


def _named_icon_focus() -> FocusNodeData:
    return FocusNodeData(id="LBA_old_ways", title="Old Ways",
                         icon="GFX_goal_generic_construct_civilian")


def test_custom_icon_uses_generated_sprite():
    text = export_focus_tree(_project(_custom_icon_focus()))
    # the icon points at the generated sprite, not the named GFX
    assert "icon = GFX_LBA_new_dawn_focus_icon" in text
    assert "icon = GFX_goal_generic_construct_civilian" not in text


def test_named_icon_unaffected():
    text = export_focus_tree(_project(_named_icon_focus()))
    assert "icon = GFX_goal_generic_construct_civilian" in text


def test_focus_icon_sprite_gfx_generated():
    gfx = export_focus_icon_sprites(_project(_custom_icon_focus(), _named_icon_focus()))
    assert gfx is not None
    assert 'name = "GFX_LBA_new_dawn_focus_icon"' in gfx
    assert 'texturefile = "gfx/interface/goals/LBA_new_dawn.dds"' in gfx
    # the matching shine sprite the game expects for every focus icon
    assert 'name = "GFX_LBA_new_dawn_focus_icon_shine"' in gfx
    assert 'animationtexturefile = "gfx/interface/goals/shine_overlay.dds"' in gfx
    # the named-icon focus contributes nothing
    assert "LBA_old_ways" not in gfx
    # no custom icons → no .gfx
    assert export_focus_icon_sprites(_project(_named_icon_focus())) is None


def test_focus_icon_gfx_file_present_only_with_custom():
    custom = {f.relativePath for f in export_project_files(_project(_custom_icon_focus()))}
    assert "interface/LBA_forge_focus_icons.gfx" in custom
    named = {f.relativePath for f in export_project_files(_project(_named_icon_focus()))}
    assert not any("focus_icons.gfx" in f for f in named)


def test_round_trip_preserves_icon_data():
    restored = project_from_dict(project_to_dict(_project(_custom_icon_focus())))
    assert restored.focuses[0].iconData == "ZmFrZWltYWdl"
    assert restored.focuses[0].icon == "GFX_goal_generic_construct_civilian"
