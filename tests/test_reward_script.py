"""Tests for the raw-reward-script parser (core/reward_script.py)."""
from __future__ import annotations

from core.reward_presets import build_reward_item_lines
from core.reward_script import parse_reward_lines


def _kinds(items):
    return [i["kind"] for i in items]


def test_simple_single_line_effects():
    items, rem = parse_reward_lines([
        "add_political_power = 150",
        "add_stability = 0.05",
        "add_war_support = -0.02",
        "army_experience = 25",
        "add_manpower = 25000",
        "add_ideas = EGY_ex_arab_shield",
        "remove_ideas = EGY_ex_gerd_anxiety",
        "set_country_flag = EGY_ex_covert_ready",
    ])
    assert rem == []
    assert _kinds(items) == ["political_power", "stability", "war_support",
                             "army_experience", "add_manpower", "add_idea",
                             "remove_idea", "set_country_flag"]
    assert items[0]["params"]["amount"] == "150"
    assert items[5]["params"]["idea"] == "EGY_ex_arab_shield"


def test_md_treasury_and_opinion_idioms():
    items, rem = parse_reward_lines([
        "set_temp_variable = { treasury_change = -6.56 }",
        "modify_treasury_effect = yes",
        "set_temp_variable = { temp_opinion = 10 }",
        "change_The_Military_opinion = yes",
        "set_temp_variable = { debt_change = -25 }",
        "modify_debt_effect = yes",
    ])
    assert rem == []
    assert _kinds(items) == ["treasury_change", "interest_group_opinion", "national_debt"]
    assert items[0]["params"]["amount"] == "-6.56"
    # Case preserved so round-trip output matches the source exactly.
    assert items[1]["params"]["effect"] == "change_The_Military_opinion"


def test_multiline_block_and_event():
    items, rem = parse_reward_lines([
        "country_event = { id = EGY.104 }",
        "create_wargoal = {",
        "target = ETH",                      # source order: target before type
        "type = puppet_wargoal_focus",
        "}",
        "add_timed_idea = {",
        "idea = idea_focus_generic_national_heritage",
        "days = 365",
        "}",
    ])
    assert rem == []
    assert _kinds(items) == ["country_event", "create_wargoal", "timed_idea"]
    # create_wargoal parses key-order-insensitively (the game ignores order).
    assert items[1]["params"] == {"type": "puppet_wargoal_focus", "target": "ETH"}


def test_foreign_influence_four_statement_idiom():
    items, rem = parse_reward_lines([
        "set_temp_variable = { percent_change = 10 }",
        "set_temp_variable = { tag_index = USA }",
        "set_temp_variable = { influence_target = EGY }",
        "change_influence_percentage = yes",
    ])
    assert rem == []
    assert _kinds(items) == ["foreign_influence"]
    assert items[0]["params"] == {"percent": "10", "influencerTag": "USA",
                                  "targetTag": "EGY"}


def test_repeats_and_bare_effects():
    items, rem = parse_reward_lines([
        "increase_economic_growth = yes",
        "increase_economic_growth = yes",
        "decrease_corruption = yes",
        "increase_policing_budget = yes",
    ])
    assert rem == []
    assert _kinds(items) == ["economic_growth", "corruption", "national_budget"]
    assert items[0]["params"]["times"] == 2
    assert items[2]["params"] == {"direction": "increase", "budget": "policing_budget"}


def test_unrecognized_stays_in_remainder_in_order():
    src = [
        "add_political_power = 50",
        "216 = {",                            # state-scoped block: not liftable
        "if = {",
        "limit = { is_controlled_by = EGY }",
        "}",
        "}",
        "add_stability = 0.02",
    ]
    items, rem = parse_reward_lines(src)
    assert _kinds(items) == ["political_power", "stability"]
    assert rem == src[1:6]


def test_round_trip_verification_rejects_lossy_matches():
    # 5.0 would rebuild as "5" — not token-identical, so it must stay raw.
    items, rem = parse_reward_lines([
        "set_temp_variable = { treasury_change = 5.0 }",
        "modify_treasury_effect = yes",
    ])
    assert items == []
    assert len(rem) == 2


def test_parsed_items_rebuild_to_source_tokens():
    src = [
        "add_tech_bonus = {",
        "name = EGY_ex_nuclear_tech",
        "bonus = 0.5",
        "uses = 1",
        "category = CAT_nuclear_reactors",
        "}",
    ]
    items, rem = parse_reward_lines(src)
    assert rem == [] and len(items) == 1
    rebuilt = " ".join(" ".join(build_reward_item_lines(items[0])).split())
    assert "category = CAT_nuclear_reactors" in rebuilt


def test_empty_and_blank_lines():
    assert parse_reward_lines([]) == ([], [])
    items, rem = parse_reward_lines(["", "   "])
    assert items == [] and rem == []


def test_structure_all_rewards_mixed_project():
    from core.reward_script import structure_all_rewards
    from core.types import CompletionReward, FocusForgeProject, FocusNodeData

    full = FocusNodeData(id="a", completionReward=CompletionReward(rawLines=[
        "add_political_power = 50",
        "set_temp_variable = { treasury_change = 8 }",
        "modify_treasury_effect = yes",
    ]))
    partial = FocusNodeData(id="b", completionReward=CompletionReward(rawLines=[
        "add_stability = 0.02",
        "some_unknown_scripted_effect = yes",
    ]))
    none = FocusNodeData(id="c", completionReward=CompletionReward(
        politicalPower=25))
    project = FocusForgeProject(countryTag="EGY",
                                focuses=[full, partial, none])

    converted, effects, skipped = structure_all_rewards(project)
    assert (converted, effects, skipped) == (1, 2, ["b"])
    # Converted focus: raw gone, items in source order.
    assert not full.completionReward.rawLines
    assert [i.kind for i in full.completionReward.items] == [
        "political_power", "treasury_change"]
    # Partial focus untouched — all-or-nothing per focus.
    assert partial.completionReward.rawLines == [
        "add_stability = 0.02",
        "some_unknown_scripted_effect = yes"]
    assert not partial.completionReward.items
