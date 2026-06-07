"""Mirrors src/core/exporters.test.ts."""
from __future__ import annotations

from core.exporters import (
    export_completion_reward_lines,
    export_focus_localisation,
    export_focus_tree,
    export_project_files,
)
from core.sample_project import make_sample_project
from core.types import CompletionReward, RewardItem


def test_focus_tree_has_header_and_id() -> None:
    project = make_sample_project()
    out = export_focus_tree(project)
    assert "focus_tree = {" in out
    assert "id = mexico_focus" in out
    assert "prerequisite = { focus = MEX_forge_national_assessment }" in out


def test_focus_tree_ends_with_newline() -> None:
    out = export_focus_tree(make_sample_project())
    assert out.endswith("\n")
    assert out.count("\n}") >= 1  # outer close


def test_localisation_has_title_line() -> None:
    out = export_focus_localisation(make_sample_project())
    assert 'MEX_forge_national_assessment:0 "Assess the National Situation"' in out


def test_localisation_yml_files_have_bom_flag() -> None:
    files = export_project_files(make_sample_project())
    yml_files = [f for f in files if f.relativePath.endswith("_focus_l_english.yml")]
    assert yml_files
    assert all(f.bom for f in yml_files)


def test_export_includes_idea_and_event_files_when_present() -> None:
    project = make_sample_project()
    files = export_project_files(project)
    paths = [f.relativePath for f in files]
    # ideas list is empty in the sample, so no idea files
    assert not any("ideas" in p for p in paths)
    # events list has one entry, so event files appear
    assert any(p.endswith("_events.txt") for p in paths)
    assert any(p.endswith("_events_l_english.yml") for p in paths)


def test_reward_items_emit_expected_lines() -> None:
    reward = CompletionReward(items=[
        RewardItem(kind="treasury_change", params={"amount": 2.5}),
        RewardItem(kind="tech_bonus", params={"name": "MEX_test_bonus", "bonus": 0.5, "uses": 1, "category": "CAT_industry"}),
        RewardItem(kind="equipment_stockpile", params={"type": "Inf_equipment", "amount": 2000, "producer": "SOV"}),
    ])
    lines = export_completion_reward_lines(reward)
    text = "\n".join(lines)
    assert "set_temp_variable = { treasury_change = 2.5 }" in text
    assert "modify_treasury_effect = yes" in text
    assert "add_tech_bonus = {" in text
    assert "producer = SOV" in text


def test_md_parties_index_complete() -> None:
    from core.md_parties import MD_PARTIES
    idxs = [i for i, _n in MD_PARTIES]
    assert idxs == list(range(24))           # global 0..23, no gaps
    assert dict(MD_PARTIES)[1] == "Western Conservatives"
    assert dict(MD_PARTIES)[9] == "Vilayat-e Faqih"


def test_relative_party_popularity_uses_party_picker() -> None:
    from core.reward_presets import get_reward_preset
    p = next(pr for pr in get_reward_preset("relative_party_popularity").params
             if pr.key == "partyIndex")
    assert p.type == "party_index"
    reward = CompletionReward(items=[RewardItem(
        kind="relative_party_popularity",
        params={"partyIndex": 1, "popularity": 0.05, "outlook": 0.02})])
    text = "\n".join(export_completion_reward_lines(reward))
    assert "set_temp_variable = { party_index = 1 }" in text


def test_timed_resource_reward() -> None:
    reward = CompletionReward(items=[
        RewardItem(kind="timed_resource",
                   params={"type": "oil", "amount": 8, "state": 391, "days": 730})])
    text = "\n".join(export_completion_reward_lines(reward))
    assert "add_resource = { type = oil amount = 8 state = 391 days = 730 }" in text


def test_focus_tree_sort_order_is_y_then_x_then_id() -> None:
    """Sorted by (y, x, id) — ensures deterministic output regardless of input order."""
    project = make_sample_project()
    out = export_focus_tree(project)
    # national_assessment (y=0) should appear before industrial_plan (y=1)
    assert out.index("MEX_forge_national_assessment") < out.index("MEX_forge_industrial_plan")
