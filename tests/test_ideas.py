"""Idea export + serialization (used by the New Idea editor flow)."""
from __future__ import annotations

from core.exporters import export_ideas, export_idea_localisation, export_project_files
from core.serialization import project_from_dict, project_to_dict
from core.types import ExportSettings, FocusForgeProject, IdeaData


def _project_with_idea():
    idea = IdeaData(
        id="LBA_oil_boom", title="Oil Boom", description="Black gold.",
        picture="GFX_idea_LBA_oil",
        modifierRawLines=["modifier = {", "\tstability_factor = 0.05",
                          "\tpolitical_power_gain = 0.25", "}"],
    )
    return FocusForgeProject(
        countryTag="LBA", treeId="t", ideas=[idea],
        exportSettings=ExportSettings(modPrefix="LBA", focusFileName="lba_focus",
                                      localisationPrefix="LBA", includeIdeas=True),
    )


def test_export_ideas_block():
    out = export_ideas(_project_with_idea())
    assert "LBA_oil_boom = {" in out
    assert "picture = GFX_idea_LBA_oil" in out
    assert "stability_factor = 0.05" in out
    assert "modifier = {" in out


def test_export_idea_localisation():
    loc = export_idea_localisation(_project_with_idea())
    assert 'LBA_oil_boom:0 "Oil Boom"' in loc
    assert 'LBA_oil_boom_desc:0 "Black gold."' in loc


def test_idea_export_files_present_when_included():
    files = {f.relativePath for f in export_project_files(_project_with_idea())}
    assert "common/ideas/LBA_ideas.txt" in files
    assert "localisation/english/LBA_ideas_l_english.yml" in files


def test_idea_round_trip():
    proj = _project_with_idea()
    restored = project_from_dict(project_to_dict(proj))
    assert restored.ideas[0].id == "LBA_oil_boom"
    assert restored.ideas[0].picture == "GFX_idea_LBA_oil"
    assert "\tstability_factor = 0.05" in restored.ideas[0].modifierRawLines


# ----- model idea management (Ideas manager: add / edit / delete) -----
def _model_with_idea_reward():
    from core.types import (CompletionReward, FocusNodeData, FocusPosition,
                            RewardItem)
    from ui.project_model import ProjectModel
    proj = FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[FocusNodeData(
            id="LBA_f", title="F", position=FocusPosition(0, 0),
            completionReward=CompletionReward(items=[
                RewardItem(kind="add_idea", enabled=True, params={"idea": "LBA_oil"})]))],
        ideas=[IdeaData(id="LBA_oil", title="Oil",
                        modifierRawLines=["modifier = {", "\tstability_factor = 0.05", "}"])],
        exportSettings=ExportSettings(),
    )
    m = ProjectModel()
    m.replace_project(proj, path=None)
    return m


def test_update_idea_renames_reward_references():
    m = _model_with_idea_reward()
    assert m.idea_reference_count("LBA_oil") == 1
    final = m.update_idea("LBA_oil", IdeaData(id="LBA_oil_v2", title="Oil v2"))
    assert final == "LBA_oil_v2"
    assert [i.id for i in m.project.ideas] == ["LBA_oil_v2"]
    # the focus's add_idea reward now points at the renamed idea
    assert m.project.focuses[0].completionReward.items[0].params["idea"] == "LBA_oil_v2"


def test_add_idea_dedupes_id():
    m = _model_with_idea_reward()
    fid = m.add_idea(IdeaData(id="LBA_oil", title="Another"))
    assert fid == "LBA_oil_2"
    assert m.project.exportSettings.includeIdeas is True


def test_delete_idea():
    m = _model_with_idea_reward()
    m.delete_idea("LBA_oil")
    assert m.project.ideas == []
