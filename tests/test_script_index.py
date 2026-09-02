"""Script-token validation: vocabulary / state / equipment indexes built from
roots, the raw-script scanner, and the validation issues they drive."""
from __future__ import annotations

import pytest

from core.sample_project import make_sample_project
from core.script_index import (
    build_equipment_archetypes,
    build_equipment_types,
    build_script_vocabulary,
    build_state_index,
    clear_script_index_cache,
    iter_keys,
    scan_raw_script,
)
from core.types import AvailabilityRule, CompletionReward, RewardItem
from core.validation import validate_project


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_script_index_cache()
    yield
    clear_script_index_cache()


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _roots(tmp_path):
    """A tiny 'vanilla' root and an 'MD' root that replaces scripted_effects,
    history/states and common/units/equipment."""
    game = tmp_path / "game"
    md = tmp_path / "md"
    _write(game / "common/national_focus/generic.txt",
           "focus_tree = {\n\tfocus = {\n\t\tid = G_a\n\t\tcompletion_reward = {\n"
           "\t\t\tadd_political_power = 50\n\t\t\tadd_stability = 0.05\n\t\t\tcountry_event = { id = g.1 days = 3 }\n"
           "\t\t\t1 = { add_core_of = USA }\n\t\t\tadd_equipment_to_stockpile = { type = infantry_equipment amount = 1 }\n"
           "\t\t}\n\t\tavailable = { has_war = no }\n\t}\n}\n")
    _write(game / "common/scripted_effects/vanilla_fx.txt",
           "vanilla_only_helper = { add_political_power = 1 }\n")
    _write(game / "history/states/1-Vanilla.txt", "state = {\n\tid = 1\n\tname = \"STATE_1\"\n\thistory = { owner = USA }\n}\n")
    _write(game / "history/states/999-Gone.txt", "state = {\n\tid = 999\n\tname = \"STATE_999\"\n\thistory = { owner = USA }\n}\n")
    _write(game / "common/units/equipment/inf.txt",
           "equipments = {\n\tinfantry_equipment = {\n\t\tis_archetype = yes\n\t}\n\tinfantry_equipment_1 = {\n\t\tarchetype = infantry_equipment\n\t}\n}\n")
    _write(md / "descriptor.mod",
           'name="MD"\nreplace_path="common/scripted_effects"\nreplace_path="history/states"\n'
           'replace_path="common/units/equipment"\n')
    _write(md / "common/scripted_effects/md_fx.txt",
           "modify_treasury_effect = {\n\tadd_to_variable = { treasury = treasury_change }\n}\n"
           "change_relative_party_popularity = { log = \"x\" }\n")
    _write(md / "common/national_focus/usa.txt",
           "focus_tree = {\n\tfocus = {\n\t\tid = USA_x\n\t\tcompletion_reward = {\n"
           "\t\t\tset_temp_variable = { treasury_change = 5 }\n\t\t\tmodify_treasury_effect = yes\n"
           "\t\t\t771 = { add_building_construction = { type = industrial_complex level = 1 instant_build = yes } }\n"
           "\t\t}\n\t\tai_will_do = { base = 1 modifier = { factor = 0 is_historical_focus_on = yes } }\n\t}\n}\n")
    _write(md / "history/states/1-Vanilla.txt", "state = {\n\tid = 1\n\tname = \"STATE_1\"\n\thistory = { owner = USA }\n}\n")
    _write(md / "history/states/835-Mexico.txt", "state = {\n\tid = 835\n\tname = \"STATE_835\"\n\thistory = {\n\t\towner = MEX\n\t}\n}\n")
    _write(md / "history/states/800-Texas.txt", "state = {\n\tid = 800\n\tname = \"STATE_800\"\n\thistory = { owner = USA }\n}\n")
    _write(md / "common/units/equipment/md_inf.txt",
           "equipments = {\n\tinfantry_weapons_type = {\n\t\tis_archetype = yes\n\t}\n"
           "\tinfantry_weapons_1 = {\n\t\tarchetype = infantry_weapons_type\n\t}\n}\n")
    return [str(game), str(md)]


# ----- iter_keys / scanner ------------------------------------------------------

def test_iter_keys_reports_parent_and_values():
    text = 'a = { b = 1 c = { d = "x y" } } e > 3'
    got = list(iter_keys(text))
    assert ("a", None, None) in got and ("b", "a", "1") in got
    assert ("c", "a", None) in got and ("d", "c", "x y") in got
    assert ("e", None, "3") in got                      # comparison operators count as statements


def test_scan_raw_script_classifies_tokens():
    found = scan_raw_script([
        "set_temp_variable = { cart_strength_change = -8 }",
        "modify_cartel_variables_effect = yes",
        "835 = { add_building_construction = { type = industrial_complex level = 2 } }",
        "800 = { add_core_of = MEX }",
        "if = { limit = { has_war_support > 0.5 NOT = { has_country_flag = x } } "
        "add_equipment_to_stockpile = { type = Inf_equipment amount = 100 producer = USA } }",
        "typo_effect = yes",
        "random_list = { 50 = { add_stability = 0.1 } 50 = { add_war_support = 0.1 } }",
        "every_owned_state = { add_extra_state_shared_building_slots = 1 }",
        "set_state_owner = 803",
    ])
    assert "typo_effect" in found["keys"] and "add_building_construction" in found["keys"]
    assert "add_extra_state_shared_building_slots" in found["keys"]
    assert "cart_strength_change" not in found["keys"]          # variable name, not an effect
    assert "type" not in found["keys"] and "level" not in found["keys"]   # block params
    assert found["states"] == [835, 800, 803]                   # random_list weights are not states
    assert found["tags"] == ["MEX", "USA"]                      # NOT is a keyword, not a tag
    assert found["equipment"] == ["Inf_equipment"]


# ----- indexes ----------------------------------------------------------------------

def test_vocabulary_honours_replace_path_for_helper_names(tmp_path):
    vocab = build_script_vocabulary(_roots(tmp_path))
    assert {"add_political_power", "add_stability", "country_event", "has_war",
            "modify_treasury_effect", "change_relative_party_popularity",
            "add_building_construction", "is_historical_focus_on"} <= vocab
    assert "vanilla_only_helper" not in vocab       # MD replaced scripted_effects
    assert "nonsense_effect" not in vocab


def test_state_and_equipment_indexes_follow_replace_path(tmp_path):
    roots = _roots(tmp_path)
    states = build_state_index(roots)
    assert set(states) == {1, 835, 800}             # 999 was vanilla-only
    assert states[835] == {"name": "STATE_835", "owner": "MEX"}
    assert build_equipment_types(roots) == {"infantry_weapons_type", "infantry_weapons_1"}
    assert build_equipment_archetypes(roots) == ["infantry_weapons_type"]


# ----- validation ----------------------------------------------------------------

def _project_with_raw(lines, items=None):
    project = make_sample_project()
    project.countryTag = "MEX"
    f = project.focuses[0]
    f.completionReward = CompletionReward(items=items, rawLines=lines)
    return project, f


def test_validation_flags_unknown_tokens_states_equipment(tmp_path):
    roots = _roots(tmp_path)
    vocab, states, equip = build_script_vocabulary(roots), build_state_index(roots), build_equipment_types(roots)
    project, f = _project_with_raw(
        ["set_temp_variable = { treasury_change = 5 }",
         "modify_treasury_effect = yes",
         "add_relative_party_popularityy = yes",            # typo
         "835 = { add_building_construction = { type = industrial_complex level = 1 } }",
         "800 = { add_core_of = MEX }",                     # not owned, but cores only -> silent
         "1 = { add_building_construction = { type = arms_factory level = 1 } }",    # not owned -> warned
         "999 = { add_building_construction = { type = arms_factory level = 1 } }",  # gone
         "add_equipment_to_stockpile = { type = Inf_equipment amount = 100 }"],
        items=[RewardItem(kind="state_building", params={"state": "999", "building": "arms_factory", "level": 1}),
               RewardItem(kind="equipment_stockpile", params={"type": "infantry_weapons_type", "amount": 10})])
    issues = validate_project(project, script_vocab=vocab, state_index=states, equipment_types=equip)
    mine = [i for i in issues if i.focusId == f.id]
    codes = [i.code for i in mine]
    unknown = [i for i in mine if i.code == "script.unknownToken"]
    assert len(unknown) == 1 and "add_relative_party_popularityy" in unknown[0].message
    assert codes.count("script.state.missing") == 2            # raw 999 scope + structured state param
    assert all(i.severity == "error" for i in mine if i.code == "script.state.missing")
    not_owned = [i for i in mine if i.code == "script.state.notOwned"]
    assert len(not_owned) == 1 and "state 1 (" in not_owned[0].message and not_owned[0].severity == "warning"
    assert set(scan_raw_script(["800 = { add_core_of = MEX }", "add_state_claim = 803"])["claim_only"]) == {800, 803}
    eq = [i for i in mine if i.code == "script.equipment.unknown"]
    assert len(eq) == 1 and "Inf_equipment" in eq[0].message   # structured item used a valid archetype


def test_validation_skips_checks_without_indexes():
    project, f = _project_with_raw(["totally_made_up = yes", "999 = { add_core_of = MEX }"])
    issues = validate_project(project)
    assert not [i for i in issues if i.code.startswith("script.")]


def test_validation_covers_triggers_events_and_ai_modifiers(tmp_path):
    from core.types import AiModifier, EventData, EventOption
    roots = _roots(tmp_path)
    vocab = build_script_vocabulary(roots)
    project = make_sample_project()
    f = project.focuses[0]
    f.available = AvailabilityRule(rawLines=["has_warr = yes"])
    f.aiModifiers = [AiModifier(factor=0, trigger=AvailabilityRule(rawLines=["is_historicl_focus_on = yes"]))]
    project.events.append(EventData(id="MEX.9", title="t", description="d",
                                    options=[EventOption(key="a", text="x", effectRawLines=["add_stabilty = 0.1"])]))
    issues = validate_project(project, script_vocab=vocab)
    # only this focus and the event — the sample project's other focuses carry
    # raw script the tiny fixture vocabulary doesn't know
    msgs = [i.message for i in issues if i.code == "script.unknownToken" and i.focusId in (f.id, None)]
    assert any("has_warr" in m and "availability" in m for m in msgs)
    assert any("is_historicl_focus_on" in m and "AI modifier" in m for m in msgs)
    assert any("add_stabilty" in m and "event MEX.9" in m for m in msgs)
    # known tokens produce nothing
    f.available = AvailabilityRule(rawLines=["has_war = yes"])
    f.aiModifiers = None
    project.events.clear()
    assert not [i for i in validate_project(project, script_vocab=vocab)
                if i.code == "script.unknownToken" and i.focusId in (f.id, None)]


def test_other_edition_helper_is_not_double_reported(tmp_path):
    from core.md_edition import edition_context
    roots = _roots(tmp_path)
    vocab = build_script_vocabulary(roots)
    project, f = _project_with_raw(["add_relative_party_popularity = yes"])   # main-only name
    with edition_context("beta"):
        issues = validate_project(project, script_vocab=vocab)
    codes = [i.code for i in issues if i.focusId == f.id]
    assert "focus.reward.editionHelper" in codes
    assert "script.unknownToken" not in codes
