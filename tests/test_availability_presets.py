"""Tests for availability condition presets + export integration."""
from __future__ import annotations

from core.availability_presets import (
    build_availability_item_lines,
    create_availability_item,
    get_availability_preset,
    validate_availability_item,
)
from core.exporters import export_focus_tree
from core.types import (
    AvailabilityRule,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    RewardItem,
)


def _item(kind, **params):
    base = create_availability_item(kind)
    base["params"].update(params)
    return base


def test_build_lines_for_key_presets():
    assert build_availability_item_lines(_item("has_completed_focus", focus="LBA_x")) == [
        "has_completed_focus = LBA_x"]
    assert build_availability_item_lines(_item("nato_member")) == ["has_idea = NATO_member"]
    assert build_availability_item_lines(_item("date_after", date="2010.1.1")) == ["date > 2010.1.1"]
    assert build_availability_item_lines(_item("gdp_threshold", amount=2000)) == [
        "check_variable = { gdp_total > 2000 }"]
    assert build_availability_item_lines(_item("ruling_party", party="western_liberals_are_in_power")) == [
        "western_liberals_are_in_power = yes"]
    assert build_availability_item_lines(_item("country_leader_name", name="Muammar Gaddafi")) == [
        'has_country_leader = { name = "Muammar Gaddafi" ruling_only = yes }']
    assert build_availability_item_lines(_item("in_faction_with", tag="RUS")) == [
        "is_in_faction_with = RUS"]
    assert build_availability_item_lines(_item("has_opinion", tag="USA", value=50)) == [
        "has_opinion = { target = USA value > 50 }"]
    assert build_availability_item_lines(_item("lacks_country_flag", flag="done")) == [
        "NOT = { has_country_flag = done }"]
    assert build_availability_item_lines(_item("state_controlled", state=391, tag="LBA")) == [
        "391 = { is_owned_and_controlled_by = LBA }"]


def test_disabled_item_emits_nothing():
    it = _item("nato_member")
    it["enabled"] = False
    assert build_availability_item_lines(it) == []


def test_validate_required():
    assert validate_availability_item(_item("has_tech", tech="")) != []
    assert validate_availability_item(_item("has_tech", tech="internet1")) == []


def test_all_presets_build_without_error():
    from core.availability_presets import AVAILABILITY_PRESETS
    for preset in AVAILABILITY_PRESETS:
        build_availability_item_lines(create_availability_item(preset.kind))  # no exception


def test_export_emits_availability_block():
    focus = FocusNodeData(id="LBA_a", title="A", position=FocusPosition(0, 0))
    focus.available = AvailabilityRule(items=[
        RewardItem(kind="nato_member", enabled=True, params={}),
        RewardItem(kind="date_after", enabled=True, params={"date": "2011.1.1"}),
    ])
    proj = FocusForgeProject(countryTag="LBA", treeId="t", focuses=[focus])
    out = export_focus_tree(proj)
    assert "available = {" in out
    assert "has_idea = NATO_member" in out
    assert "date > 2011.1.1" in out
