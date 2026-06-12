"""Preset-catalog correctness: fixes from the MD-verified review of every
reward and availability preset, plus an all-presets smoke loop."""
from __future__ import annotations

from core.availability_presets import (
    AVAILABILITY_PRESETS,
    GOVERNMENTS,
    build_availability_item_lines,
    create_availability_item,
    validate_availability_item,
)
from core.ideologies import IDEOLOGY_TREE
from core.reward_presets import (
    EQUIPMENT_TYPES,
    INTEREST_GROUP_EFFECTS,
    REWARD_PRESETS,
    build_reward_item_lines,
    create_reward_item,
    encode_leader,
    validate_reward_item,
)
from core.types import RewardItem


def _build(kind: str, **params) -> str:
    item = create_reward_item(kind)
    item["params"].update(params)
    return "\n".join(build_reward_item_lines(item))


# ----- smoke loop: every reward preset builds from its defaults without error -----
def test_every_reward_preset_builds():
    for preset in REWARD_PRESETS:
        item = create_reward_item(preset.kind)
        lines = build_reward_item_lines(item)
        assert isinstance(lines, list), preset.kind


def test_every_availability_preset_builds():
    for preset in AVAILABILITY_PRESETS:
        item = create_availability_item(preset.kind)
        lines = build_availability_item_lines(item)
        assert isinstance(lines, list), preset.kind


# ----- script-breaker fixes -----
def test_equipment_types_have_no_known_bad_ids():
    for bad in ("Arty_equipment", "Convoy", "fighter_equipment",
                "CAS_equipment", "naval_equipment"):
        assert bad not in EQUIPMENT_TYPES
    for good in ("artillery_equipment", "convoy", "small_plane_airframe"):
        assert good in EQUIPMENT_TYPES


def test_state_param_zero_is_invalid():
    item = create_reward_item("state_building")
    item["params"]["state"] = 0
    assert any("state id" in i for i in validate_reward_item(item))
    item["params"]["state"] = 123
    assert not any("state id" in i for i in validate_reward_item(item))
    avail = create_availability_item("state_controlled")
    avail["params"].update({"state": 0, "tag": "LBA"})
    assert any("state id" in i for i in validate_availability_item(avail))


def test_state_building_province_param():
    out = _build("state_building", state=43, building="naval_base",
                 level=2, province=9716)
    assert "type = naval_base province = 9716 level = 2" in out
    out = _build("state_building", state=43, building="infrastructure", level=1)
    assert "province" not in out


def test_legacy_state_ideology_normalizes_to_communist_state():
    assert "Communist-State" in IDEOLOGY_TREE["communism"]
    assert "State" not in IDEOLOGY_TREE["communism"]
    out = _build("promote_leader",
                 leader=encode_leader("Test Person", ideology="State"))
    assert "ideology = Communist-State" in out
    assert "ruling_party = communism" in out  # set_politics no longer dropped


# ----- semantic fixes -----
def test_md_shared_slot_set():
    # MD's renewable-energy "synthetic_refinery" has shares_slots = no
    out = _build("state_building", state=5, building="synthetic_refinery", level=1)
    assert "add_extra_state_shared_building_slots" not in out
    # MD's offices DO share slots
    out = _build("state_building", state=5, building="offices", level=1)
    assert "add_extra_state_shared_building_slots = 1" in out


def test_government_check_includes_nationalist():
    assert "nationalist" in GOVERNMENTS


def test_leader_name_check_is_ruling_only():
    item = create_availability_item("country_leader_name")
    item["params"]["name"] = "Muammar Gaddafi"
    out = "\n".join(build_availability_item_lines(item))
    assert out == 'has_country_leader = { name = "Muammar Gaddafi" ruling_only = yes }'


def test_hydroelectric_dam_is_additive():
    out = _build("hydroelectric_dam", state=677, production=0.8)
    assert "set_temp_variable = { electric_addition = 0.8 }" in out
    assert "add_hydroelectric_energy_production_effect = yes" in out
    assert "set_variable" not in out  # the old overwrite pattern


def test_interest_group_effect_is_a_closed_verified_list():
    preset = next(p for p in REWARD_PRESETS if p.kind == "interest_group_opinion")
    effect = next(p for p in preset.params if p.key == "effect")
    assert effect.type == "select"
    assert effect.options == INTEREST_GROUP_EFFECTS
    assert "change_the_military_opinion" in INTEREST_GROUP_EFFECTS


def test_country_event_days_coerced_to_int():
    out = _build("country_event", eventId="x.1", days=1.5)
    assert "days = 1" in out and "1.5" not in out


# ----- new presets -----
def test_news_event_puppet_annex():
    assert _build("news_event", eventId="x.2") == "news_event = { id = x.2 }"
    assert _build("puppet", target="LBA") == "puppet = LBA"
    out = _build("annex", target="LBA")
    assert out == "annex_country = { target = LBA transfer_troops = yes }"


def test_relative_party_popularity_defaults_to_pure_relative():
    item = create_reward_item("relative_party_popularity")
    assert item["params"]["outlook"] == 0
