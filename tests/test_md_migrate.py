"""Millennium Dawn 1.x -> 2.0 renames (core.md_migrate)."""
from __future__ import annotations

import pytest

from core.md_edition import BETA, LEGACY_MAIN, MAIN, set_active_edition
from core.md_migrate import describe_counts, md2_renames, migrate_project
from core.sample_project import make_sample_project
from core.types import (
    AiModifier,
    AvailabilityRule,
    CompletionReward,
    DecisionCategory,
    DecisionData,
    EventData,
    EventOption,
    FocusShortcut,
    RewardItem,
)
from core.validation import validate_project

OLD_HELPER = "add_relative_party_popularity"
NEW_HELPER = "change_relative_party_popularity"


@pytest.fixture(autouse=True)
def _reset_active_edition():
    set_active_edition("main")
    yield
    set_active_edition("main")


def _project_with_1x_script():
    p = make_sample_project()
    f = p.focuses[0]
    f.completionReward = CompletionReward(
        items=[RewardItem(kind="equipment_stockpile",
                          params={"type": "Inf_equipment", "amount": 500, "producer": "NOR"}),
               RewardItem(kind="puppet", params={"target": "GRL"}),
               RewardItem(kind="puppet", params={"target": "USA"})],
        rawLines=["set_temp_variable = { party_index = 1 }",
                  f"{OLD_HELPER} = yes",
                  "add_equipment_to_stockpile = { type = util_vehicle_equipment amount = 50 }",
                  "NOR = { add_opinion_modifier = { target = ROOT modifier = x } }",
                  "set_country_flag = NOR_friendship",      # a flag, not the tag
                  "TNOR = { }",                              # a different token
                  "NOR.some_var = 1"])                       # scope form: same tag
    f.available = AvailabilityRule(items=[RewardItem(kind="in_faction_with", params={"tag": "NOR"})],
                                   rawLines=["GRL = { exists = yes }"])
    f.bypass = AvailabilityRule(rawLines=[f"# {OLD_HELPER} in a comment"])
    f.aiModifiers = [AiModifier(factor=0, trigger=AvailabilityRule(rawLines=["has_war_with = NOR"]))]
    p.events = [EventData(id="mex.1", trigger=AvailabilityRule(rawLines=["country_exists = GRL"]),
                          options=[EventOption(key="a", effectRawLines=[f"{OLD_HELPER} = yes"],
                                               items=[RewardItem(kind="puppet", params={"target": "NOR"})],
                                               trigger=AvailabilityRule(rawLines=["tag = NOR"]))])]
    p.decisions = [DecisionData(id="mex_d", visible=AvailabilityRule(rawLines=["tag = GRL"]),
                                completeEffect=CompletionReward(rawLines=[f"{OLD_HELPER} = yes"]),
                                rawLines=["custom_cost_trigger = { NOR = { exists = yes } }"])]
    p.decisionCategories = [DecisionCategory(id="mex_c", visible=AvailabilityRule(rawLines=["tag = NOR"]),
                                             rawLines=["allowed = { tag = GRL }"])]
    p.shortcuts = [FocusShortcut(label="x", target=f.id, triggerRawLines=["NOR = { exists = yes }"])]
    return p


def test_renames_follow_the_edition():
    r = md2_renames(MAIN)
    assert r[OLD_HELPER] == NEW_HELPER
    assert r["Inf_equipment"] == "infantry_weapons_type"
    assert r["util_vehicle_equipment"] == "util_vehicle_type"
    assert r["NOR"] == "NRY" and r["GRL"] == "GRN"
    assert md2_renames(BETA) == r
    assert OLD_HELPER not in md2_renames(LEGACY_MAIN)   # nothing to rename the helper to


def test_dry_run_counts_without_changing():
    p = _project_with_1x_script()
    before = repr(p)
    counts = migrate_project(p, MAIN, dry_run=True)
    assert repr(p) == before
    assert counts[OLD_HELPER] == 4          # reward, bypass comment, event option, decision
    assert counts["Inf_equipment"] == 1 and counts["util_vehicle_equipment"] == 1
    assert counts["NOR"] == 10 and counts["GRL"] == 5


def test_migrates_every_site_and_only_whole_tokens():
    p = _project_with_1x_script()
    counts = migrate_project(p, MAIN)
    assert sum(counts.values()) == 21
    f = p.focuses[0]
    raw = f.completionReward.rawLines
    assert raw[1] == f"{NEW_HELPER} = yes"
    assert raw[2] == "add_equipment_to_stockpile = { type = util_vehicle_type amount = 50 }"
    assert raw[3].startswith("NRY = {")
    assert raw[4] == "set_country_flag = NOR_friendship"
    assert raw[5] == "TNOR = { }"
    assert raw[6] == "NRY.some_var = 1"
    items = f.completionReward.items
    assert items[0].params == {"type": "infantry_weapons_type", "amount": 500, "producer": "NRY"}
    assert items[1].params == {"target": "GRN"} and items[2].params == {"target": "USA"}
    assert f.available.items[0].params == {"tag": "NRY"}
    assert f.available.rawLines == ["GRN = { exists = yes }"]
    assert f.aiModifiers[0].trigger.rawLines == ["has_war_with = NRY"]
    ev = p.events[0]
    assert ev.trigger.rawLines == ["country_exists = GRN"]
    assert ev.options[0].effectRawLines == [f"{NEW_HELPER} = yes"]
    assert ev.options[0].items[0].params == {"target": "NRY"}
    assert ev.options[0].trigger.rawLines == ["tag = NRY"]
    d = p.decisions[0]
    assert d.visible.rawLines == ["tag = GRN"]
    assert d.completeEffect.rawLines == [f"{NEW_HELPER} = yes"]
    assert d.rawLines == ["custom_cost_trigger = { NRY = { exists = yes } }"]
    c = p.decisionCategories[0]
    assert c.visible.rawLines == ["tag = NRY"] and c.rawLines == ["allowed = { tag = GRN }"]
    assert p.shortcuts[0].triggerRawLines == ["NRY = { exists = yes }"]
    # idempotent
    assert migrate_project(p, MAIN) == {}


def test_validation_is_clean_of_1x_names_afterwards():
    p = _project_with_1x_script()
    kw = dict(known_country_tags={"MEX", "USA", "NRY", "GRN"},
              equipment_types=frozenset({"infantry_weapons_type", "util_vehicle_type"}))
    before = validate_project(p, edition=MAIN, **kw)
    assert any(OLD_HELPER in i.message for i in before)
    assert any("renamed it to" in i.message for i in before)
    migrate_project(p, MAIN)
    after = validate_project(p, edition=MAIN, **kw)
    assert not [i for i in after if OLD_HELPER in i.message or "renamed it to" in i.message]
    assert not [i for i in after if i.code.endswith("tag.unknown") or i.code == "script.equipment.unknown"]


def test_structured_dict_items_are_handled():
    p = make_sample_project()
    p.focuses[0].completionReward = CompletionReward(items=[{"kind": "puppet", "params": {"target": "NOR"}}])
    assert migrate_project(p, MAIN) == {"NOR": 1}
    assert p.focuses[0].completionReward.items[0]["params"]["target"] == "NRY"


def test_nothing_to_do_on_a_clean_project():
    assert migrate_project(make_sample_project(), MAIN) == {}


def test_describe_counts():
    lines = describe_counts(migrate_project(_project_with_1x_script(), MAIN, dry_run=True), MAIN)
    assert lines[0] == "NOR → NRY (10×)"
    assert f"{OLD_HELPER} → {NEW_HELPER} (4×)" in lines


def test_one_undo_step_in_the_model():
    pytest.importorskip("PySide6.QtCore")
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m.replace_project(_project_with_1x_script())
    with m.batch():
        migrate_project(m.project, MAIN)
    assert m.project.focuses[0].completionReward.rawLines[1] == f"{NEW_HELPER} = yes"
    assert m.is_dirty()
    assert m.undo()
    assert m.project.focuses[0].completionReward.rawLines[1] == f"{OLD_HELPER} = yes"
    assert m.project.focuses[0].completionReward.items[1].params == {"target": "GRL"}


def test_event_ids_and_own_tag_are_never_renamed():
    """A Norway submod (tag / prefix NOR) keeps its own event ids and its own tag;
    any project keeps NOR.3-style ids (event id, not the country)."""
    from core.md_migrate import own_legacy_tags
    from core.types import IdeaData
    p = make_sample_project()
    p.countryTag = "NOR"
    p.exportSettings.localisationPrefix = "NOR"
    p.focuses[0].completionReward = CompletionReward(rawLines=[
        "country_event = { id = NOR.3 }", "NOR = { add_stability = 0.1 }",
        "GRL = { add_stability = 0.1 }", f"{OLD_HELPER} = yes"])
    assert own_legacy_tags(p) == {"NOR"}
    counts = migrate_project(p, MAIN)
    assert counts == {"GRL": 1, OLD_HELPER: 1}
    assert p.focuses[0].completionReward.rawLines == [
        "country_event = { id = NOR.3 }", "NOR = { add_stability = 0.1 }",
        "GRN = { add_stability = 0.1 }", f"{NEW_HELPER} = yes"]

    q = make_sample_project()                      # not Norway: tag renamed, event id kept
    q.focuses[0].completionReward = CompletionReward(rawLines=[
        "NOR = { country_event = { id = NOR.3 } }", "custom_effect_tooltip = NOR.3.t"])
    q.ideas = [IdeaData(id="mex_i", modifierRawLines=["targeted_modifier = { tag = NOR attack_bonus_against = 0.1 }"])]
    q.decisions = [DecisionData(id="mex_d", modifierRawLines=["targeted_modifier = { tag = GRL }"])]
    assert migrate_project(q, MAIN) == {"NOR": 2, "GRL": 1}
    assert q.focuses[0].completionReward.rawLines == [
        "NRY = { country_event = { id = NOR.3 } }", "custom_effect_tooltip = NOR.3.t"]
    assert q.ideas[0].modifierRawLines == ["targeted_modifier = { tag = NRY attack_bonus_against = 0.1 }"]
    assert q.decisions[0].modifierRawLines == ["targeted_modifier = { tag = GRN }"]


def test_validation_covers_decision_and_category_raw_sites_and_items():
    p = make_sample_project()
    p.decisions = [DecisionData(id="mex_d", rawLines=[f"cancel_effect = {{ {OLD_HELPER} = yes }}"],
                                available=AvailabilityRule(items=[RewardItem(kind="in_faction_with",
                                                                             params={"tag": "NOR"})]))]
    p.decisionCategories = [DecisionCategory(id="mex_c", visible=AvailabilityRule(
        rawLines=[f"{OLD_HELPER} = yes"]))]
    p.events = [EventData(id="mex.1", trigger=AvailabilityRule(
        items=[RewardItem(kind="country_exists", params={"tag": "GRL"})]))]
    issues = validate_project(p, edition=MAIN, known_country_tags={"MEX", "NRY", "GRN"})
    helper = [i for i in issues if OLD_HELPER in i.message]
    assert {i.message.split(":")[0] for i in helper} == {
        "decision mex_d extra fields", "decision category mex_c visible"}
    codes = {i.code for i in issues}
    assert "decision.tag.unknown" in codes and "event.trigger.tag.unknown" in codes


def test_project_tag_hint_does_not_promise_the_migration():
    p = make_sample_project()
    p.countryTag = "NOR"
    msg = next(i.message for i in validate_project(p, edition=MAIN, known_country_tags={"NRY"})
               if i.code == "project.countryTag.unknown")
    assert "change the project's country tag" in msg and "Update for Millennium Dawn" not in msg


def test_removed_preset_message_does_not_suggest_switching_editions():
    from core.reward_presets import validate_reward_item
    msg = validate_reward_item({"kind": "radicalization", "params": {"amount": -5}})[0]
    assert msg.endswith("remove it.") and "switch" not in msg
