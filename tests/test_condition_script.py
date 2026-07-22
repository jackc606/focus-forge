"""Tests for the raw availability-trigger parser (core/condition_script.py)."""
from __future__ import annotations

from core.condition_script import (
    parse_condition_lines,
    structure_all_conditions,
    structure_availability_rule,
)
from core.types import AvailabilityRule, CompletionReward, FocusForgeProject, FocusNodeData


def _kinds(items):
    return [i["kind"] for i in items]


def test_egypt_idioms_parse_completely():
    # The exact availability trio our Egypt content leans on, plus dates.
    items, rem = parse_condition_lines([
        "date > 2015.8.1",
        "country_exists = ETH",
        "NOT = { has_war_with = ETH }",
        "NOT = { has_completed_focus = EGY_ex_friend_to_all }",
        "western_autocrats_are_in_power = yes",
    ])
    assert rem == []
    assert _kinds(items) == ["date_after", "country_exists", "not_war_with",
                             "not_completed_focus", "ruling_party"]
    assert items[2]["params"] == {"tag": "ETH"}
    assert items[4]["params"] == {"party": "western_autocrats_are_in_power"}


def test_multiline_not_block_and_leader():
    items, rem = parse_condition_lines([
        "NOT = {",
        "has_war_with = SUD",
        "}",
        'has_country_leader = { name = "Abdel Fattah el-Sisi" ruling_only = yes }',
        "has_stability > 0.6",
    ])
    assert rem == []
    assert _kinds(items) == ["not_war_with", "country_leader_name", "stability"]
    assert items[1]["params"]["name"] == "Abdel Fattah el-Sisi"


def test_unknown_scripted_trigger_stays_raw():
    # OR blocks and unknown scripted triggers must survive untouched.
    src = [
        "OR = {",
        "emerging_autocracy_are_in_power = yes",
        "nationalist_fascist_are_in_power = yes",
        "}",
        "country_exists = SUD",
    ]
    items, rem = parse_condition_lines(src)
    assert _kinds(items) == ["country_exists"]
    assert rem == src[:4]


def test_unlisted_party_trigger_is_not_lifted():
    # "X = yes" only parses as ruling_party for the KNOWN MD party triggers —
    # arbitrary scripted calls must not be misfiled.
    items, rem = parse_condition_lines(["some_random_trigger = yes"])
    assert items == [] and len(rem) == 1


def test_structure_rule_all_or_nothing():
    rule = AvailabilityRule(rawLines=["date > 2020.1.1", "mystery = yes"])
    assert structure_availability_rule(rule) == 0
    assert rule.rawLines == ["date > 2020.1.1", "mystery = yes"]
    rule2 = AvailabilityRule(rawLines=["date > 2020.1.1", "country_exists = ETH"])
    assert structure_availability_rule(rule2) == 2
    assert rule2.rawLines is None
    assert [i.kind for i in rule2.items] == ["date_after", "country_exists"]


def test_structure_all_conditions_covers_available_and_bypass():
    a = FocusNodeData(id="a", available=AvailabilityRule(
        rawLines=["country_exists = ETH"]))
    b = FocusNodeData(id="b", bypass=AvailabilityRule(
        rawLines=["has_war = yes"]))
    c = FocusNodeData(id="c", available=AvailabilityRule(
        rawLines=["unknown_trigger_thing = yes"]))
    project = FocusForgeProject(countryTag="EGY", focuses=[a, b, c])
    converted, conditions, skipped = structure_all_conditions(project)
    assert (converted, conditions, skipped) == (2, 2, ["c"])
    assert a.available.rawLines is None and a.available.items[0].kind == "country_exists"
    assert b.bypass.rawLines is None and b.bypass.items[0].kind == "at_war"
    assert c.available.rawLines == ["unknown_trigger_thing = yes"]
