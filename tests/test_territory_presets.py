"""Territory reward presets: Add Core / Add Claim / Core All Owned States —
builders, raw-script round-trip, state validation and the all-states picker."""
from __future__ import annotations

from core.reward_presets import (
    build_reward_item_lines,
    create_reward_item,
    validate_reward_item,
)
from core.reward_script import parse_reward_lines, structure_completion_reward
from core.sample_project import make_sample_project
from core.state_index import resolve_all_states
from core.types import CompletionReward, RewardItem
from core.validation import validate_project


def _lines(kind: str, **params) -> list:
    item = create_reward_item(kind)
    item["params"].update(params)
    return build_reward_item_lines(item)


def test_add_core_builds_both_forms():
    assert _lines("add_core", state=800) == ["add_state_core = 800"]
    assert _lines("add_core", state=800, country="MEX") == ["800 = { add_core_of = MEX }"]
    assert _lines("add_core", state="800", country="  ") == ["add_state_core = 800"]


def test_add_claim_builds_both_forms():
    assert _lines("add_claim", state=803) == ["add_state_claim = 803"]
    assert _lines("add_claim", state=803, country="GUA") == ["803 = { add_claim_by = GUA }"]


def test_core_owned_states_builds_md_idiom():
    assert _lines("core_owned_states") == [
        "every_owned_state = {", "\tadd_core_of = ROOT", "}"]


def test_state_is_required_and_must_be_real():
    assert any("missing State" in m for m in validate_reward_item(create_reward_item("add_core")))
    item = create_reward_item("add_claim")
    item["params"]["state"] = 0
    assert any("real state id" in m for m in validate_reward_item(item))
    item["params"]["state"] = 12
    assert validate_reward_item(item) == []


def test_raw_script_structures_into_territory_cards():
    raw = ["add_state_core = 800",
           "801 = { add_core_of = MEX }",
           "add_state_claim = 802",
           "803 = { add_claim_by = GUA }",
           "every_owned_state = {", "\tadd_core_of = ROOT", "}"]
    items, rem = parse_reward_lines(raw)
    assert rem == []
    assert [i["kind"] for i in items] == ["add_core", "add_core", "add_claim",
                                         "add_claim", "core_owned_states"]
    assert items[1]["params"] == {"state": "801", "country": "MEX"}
    assert items[2]["params"] == {"state": "802", "country": ""}
    rebuilt = [ln for it in items for ln in build_reward_item_lines(it)]
    assert rebuilt == raw


def test_every_owned_state_with_extra_effects_stays_raw():
    raw = ["every_owned_state = {", "\tadd_core_of = ROOT", "\tadd_manpower = 100", "}"]
    items, rem = parse_reward_lines(raw)
    assert items == [] and rem == raw
    reward = CompletionReward(rawLines=list(raw))
    assert structure_completion_reward(reward) == 0 and reward.rawLines == raw


_STATES = {
    835: {"owner": "MEX", "name": "Chihuahua"},
    800: {"owner": "USA", "name": "Texas"},
}


def _issues_for(items):
    project = make_sample_project()
    project.countryTag = "MEX"
    f = project.focuses[0]
    f.completionReward = CompletionReward(items=items)
    return [i for i in validate_project(project, state_index=_STATES) if i.focusId == f.id]


def test_core_on_foreign_state_does_not_warn_but_missing_state_errors():
    issues = _issues_for([RewardItem(kind="add_core", params={"state": 800, "country": ""}),
                          RewardItem(kind="add_claim", params={"state": 800, "country": "MEX"})])
    assert not [i for i in issues if i.code == "script.state.notOwned"]
    issues = _issues_for([RewardItem(kind="add_core", params={"state": 999, "country": ""})])
    assert [i.code for i in issues if i.code.startswith("script.state")] == ["script.state.missing"]
    # A building on that same foreign state still warns — only territory cards are exempt.
    issues = _issues_for([RewardItem(kind="state_building",
                                     params={"state": 800, "building": "arms_factory", "level": 1})])
    assert [i.code for i in issues if i.code == "script.state.notOwned"] == ["script.state.notOwned"]


def test_resolve_all_states_lists_every_owner(tmp_path):
    sd = tmp_path / "history" / "states"
    sd.mkdir(parents=True)
    (sd / "a.txt").write_text(
        'state = { id = 1 name = "STATE_1" history = { owner = MEX } }\n'
        'state = { id = 2 name = "STATE_2" history = { owner = USA } }\n'
        'state = { id = 3 history = { } }\n', encoding="utf-8")
    loc = tmp_path / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "state_names_l_english.yml").write_text(
        'l_english:\n STATE_1:0 "Chihuahua"\n STATE_2:0 "Texas"\n', encoding="utf-8")
    labels = dict(resolve_all_states([str(tmp_path)]))
    assert labels == {1: "1 — Chihuahua (MEX)", 2: "2 — Texas (USA)", 3: "3 — STATE_3"}
