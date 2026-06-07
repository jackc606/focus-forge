"""Availability (focus `available = { }`) condition presets.

Mirrors the reward-preset system (``core/reward_presets.py``): each preset turns a
small param dict into HOI4 / Millennium Dawn trigger lines. Reuses
``RewardParamDef`` for params and ``RewardItem`` (kind/params/enabled) as the
stored item shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .reward_presets import RewardParamDef, _number_value, _value

# MD ruling-party scripted triggers (common/scripted_triggers/01_political_triggers.txt)
MD_RULING_PARTIES = [
    "western_autocrats_are_in_power",
    "western_conservatism_are_in_power",
    "western_liberals_are_in_power",
    "western_social_democrats_are_in_power",
    "emerging_communist_state_are_in_power",
    "emerging_anarchist_communism_are_in_power",
    "emerging_reactionaries_are_in_power",
    "emerging_autocracy_are_in_power",
    "emerging_moderate_shiite_are_in_power",
    "emerging_hardline_shiite_are_in_power",
    "salafist_kingdom_are_in_power",
    "salafist_caliphate_are_in_power",
    "neutrality_neutral_muslim_brotherhood_are_in_power",
    "neutrality_neutral_autocracy_are_in_power",
    "neutrality_neutral_conservatism_are_in_power",
    "neutrality_neutral_oligarch_are_in_power",
    "neutrality_neutral_libertarians_are_in_power",
    "neutrality_neutral_green_are_in_power",
    "neutrality_neutral_social_are_in_power",
    "neutrality_neutral_communism_are_in_power",
    "nationalist_right_wing_populists_are_in_power",
    "nationalist_fascist_are_in_power",
    "nationalist_military_junta_are_in_power",
    "nationalist_monarchists_are_in_power",
]

GOVERNMENTS = ["democratic", "communism", "fascism", "neutrality"]


@dataclass
class AvailabilityPreset:
    kind: str
    group: str
    label: str
    description: str
    params: list = field(default_factory=list)  # list[RewardParamDef]
    build: Callable[[dict], list] = field(default=lambda p: [])


def _p(*a, **k):
    return RewardParamDef(*a, **k)


# ----- builders ----------------------------------------------------------------
def _b_has_completed_focus(p): return [f"has_completed_focus = {_value(p, 'focus')}"]
def _b_has_country_flag(p): return [f"has_country_flag = {_value(p, 'flag')}"]
def _b_lacks_country_flag(p): return [f"NOT = {{ has_country_flag = {_value(p, 'flag')} }}"]
def _b_government(p): return [f"has_government = {_value(p, 'ideology')}"]
def _b_ruling_party(p): return [f"{_value(p, 'party')} = yes"]
def _b_has_idea(p): return [f"has_idea = {_value(p, 'idea')}"]
def _b_elections(p): return [f"has_elections = {_value(p, 'value')}"]
def _b_nato(p): return ["has_idea = NATO_member"]
def _b_eu(p): return ["has_idea = EU_member"]
def _b_in_faction_with(p): return [f"is_in_faction_with = {_value(p, 'tag')}"]
def _b_is_subject_of(p): return [f"is_subject_of = {_value(p, 'tag')}"]
def _b_not_subject_of(p): return [f"NOT = {{ is_subject_of = {_value(p, 'tag')} }}"]
def _b_country_exists(p): return [f"country_exists = {_value(p, 'tag')}"]
def _b_has_opinion(p): return [f"has_opinion = {{ target = {_value(p, 'tag')} value > {_number_value(p, 'value')} }}"]
def _b_at_war(p): return ["has_war = yes"]
def _b_at_peace(p): return ["has_war = no"]
def _b_war_with(p): return [f"has_war_with = {_value(p, 'tag')}"]
def _b_leader_name(p): return [f'has_country_leader = {{ name = "{_value(p, "name")}" }}']
def _b_date_after(p): return [f"date > {_value(p, 'date')}"]
def _b_date_before(p): return [f"date < {_value(p, 'date')}"]
def _b_gdp(p): return [f"check_variable = {{ gdp_total > {_number_value(p, 'amount')} }}"]
def _b_stability(p): return [f"has_stability > {_number_value(p, 'amount')}"]
def _b_war_support(p): return [f"has_war_support > {_number_value(p, 'amount')}"]
def _b_political_power(p): return [f"has_political_power > {_number_value(p, 'amount')}"]
def _b_has_tech(p): return [f"has_tech = {_value(p, 'tech')}"]
def _b_building_count(p): return [f"{_value(p, 'building')} > {_number_value(p, 'count')}"]


def _b_state_controlled(p):
    return [f"{_number_value(p, 'state')} = {{ is_owned_and_controlled_by = {_value(p, 'tag')} }}"]


_RAW = [
    AvailabilityPreset("has_completed_focus", "Focus & Flags", "Completed focus",
                       "Requires another focus to be completed (without being a tree prerequisite).",
                       [_p("focus", "Focus", "focus", "", required=True)], _b_has_completed_focus),
    AvailabilityPreset("has_country_flag", "Focus & Flags", "Has country flag",
                       "Requires a country flag to be set.",
                       [_p("flag", "Flag", "string", "", required=True)], _b_has_country_flag),
    AvailabilityPreset("lacks_country_flag", "Focus & Flags", "Lacks country flag",
                       "Requires a country flag to NOT be set.",
                       [_p("flag", "Flag", "string", "", required=True)], _b_lacks_country_flag),

    AvailabilityPreset("government", "Politics", "Government (ideology)",
                       "Requires a ruling ideology group.",
                       [_p("ideology", "Ideology", "select", "democratic", required=True, options=GOVERNMENTS)],
                       _b_government),
    AvailabilityPreset("ruling_party", "Politics", "Ruling party (MD)",
                       "Requires a specific Millennium Dawn ruling party to be in power.",
                       [_p("party", "Party", "select", MD_RULING_PARTIES[0], required=True, options=MD_RULING_PARTIES)],
                       _b_ruling_party),
    AvailabilityPreset("has_idea", "Politics", "Has idea / spirit",
                       "Requires a national spirit or idea.",
                       [_p("idea", "Idea ID", "string", "", required=True)], _b_has_idea),
    AvailabilityPreset("elections", "Politics", "Elections",
                       "Requires elections to be active or not.",
                       [_p("value", "Has elections", "select", "yes", required=True, options=["yes", "no"])],
                       _b_elections),

    AvailabilityPreset("nato_member", "Diplomacy", "NATO member",
                       "Requires NATO membership (has_idea = NATO_member).", [], _b_nato),
    AvailabilityPreset("eu_member", "Diplomacy", "EU member",
                       "Requires EU membership (has_idea = EU_member).", [], _b_eu),
    AvailabilityPreset("in_faction_with", "Diplomacy", "In faction with",
                       "In the same faction as a country (NATO = USA, CSTO = RUS).",
                       [_p("tag", "Country", "country_tag", "", required=True,
                           helpText="Faction leader tag, e.g. USA for NATO, RUS for CSTO.")],
                       _b_in_faction_with),
    AvailabilityPreset("is_subject_of", "Diplomacy", "Is subject of",
                       "Is a subject/puppet of a country.",
                       [_p("tag", "Overlord", "country_tag", "", required=True)], _b_is_subject_of),
    AvailabilityPreset("not_subject_of", "Diplomacy", "Not subject of",
                       "Is NOT a subject of a country.",
                       [_p("tag", "Overlord", "country_tag", "", required=True)], _b_not_subject_of),
    AvailabilityPreset("country_exists", "Diplomacy", "Country exists",
                       "Requires a country to still exist.",
                       [_p("tag", "Country", "country_tag", "", required=True)], _b_country_exists),
    AvailabilityPreset("has_opinion", "Diplomacy", "Opinion of country above",
                       "Requires relation/opinion of a target country above a value.",
                       [_p("tag", "Country", "country_tag", "", required=True),
                        _p("value", "Opinion >", "number", 50, required=True)], _b_has_opinion),
    AvailabilityPreset("at_war", "Diplomacy", "At war", "Requires being at war.", [], _b_at_war),
    AvailabilityPreset("at_peace", "Diplomacy", "At peace", "Requires not being at war.", [], _b_at_peace),
    AvailabilityPreset("war_with", "Diplomacy", "At war with",
                       "Requires being at war with a specific country.",
                       [_p("tag", "Country", "country_tag", "", required=True)], _b_war_with),

    AvailabilityPreset("country_leader_name", "Leaders", "Country leader (by name)",
                       "Requires a specific leader to be in power (exact name).",
                       [_p("name", "Leader name", "string", "", required=True,
                           placeholder="Muammar Gaddafi")], _b_leader_name),

    AvailabilityPreset("date_after", "Time & Economy", "Date after",
                       "Requires the date to be after a point.",
                       [_p("date", "Date", "string", "2010.1.1", required=True)], _b_date_after),
    AvailabilityPreset("date_before", "Time & Economy", "Date before",
                       "Requires the date to be before a point.",
                       [_p("date", "Date", "string", "2010.1.1", required=True)], _b_date_before),
    AvailabilityPreset("gdp_threshold", "Time & Economy", "GDP above",
                       "Requires total GDP above a value (MD gdp_total variable).",
                       [_p("amount", "GDP >", "number", 2000, required=True)], _b_gdp),
    AvailabilityPreset("stability", "Time & Economy", "Stability above",
                       "Requires stability above a fraction (0–1).",
                       [_p("amount", "Stability >", "number", 0.5, required=True, step=0.05)], _b_stability),
    AvailabilityPreset("war_support", "Time & Economy", "War support above",
                       "Requires war support above a fraction (0–1).",
                       [_p("amount", "War support >", "number", 0.5, required=True, step=0.05)], _b_war_support),
    AvailabilityPreset("political_power", "Time & Economy", "Political power above",
                       "Requires available political power above a value.",
                       [_p("amount", "Political power >", "number", 150, required=True)], _b_political_power),

    AvailabilityPreset("has_tech", "Tech & State", "Has technology",
                       "Requires a technology to be researched (pick by research category).",
                       [_p("tech", "Technology", "tech", "", required=True, placeholder="internet1")], _b_has_tech),
    AvailabilityPreset("state_controlled", "Tech & State", "Controls state",
                       "Requires owning and controlling a state.",
                       [_p("state", "State", "state", 0, required=True),
                        _p("tag", "Owner tag", "string", "", required=True)], _b_state_controlled),
    AvailabilityPreset("building_count", "Tech & State", "Building count",
                       "Requires more than N of a building (across the country).",
                       [_p("building", "Building", "building", "industrial_complex", required=True),
                        _p("count", "More than", "number", 0, required=True)], _b_building_count),
]


def _attach_help(preset: AvailabilityPreset) -> AvailabilityPreset:
    for param in preset.params:
        if not param.helpText:
            param.helpText = f"{param.label} for the {preset.label} requirement."
    return preset


AVAILABILITY_PRESETS = [_attach_help(p) for p in _RAW]

AVAILABILITY_PRESET_GROUPS = []
_seen = set()
for _p_ in AVAILABILITY_PRESETS:
    if _p_.group not in _seen:
        AVAILABILITY_PRESET_GROUPS.append(
            (_p_.group, [q for q in AVAILABILITY_PRESETS if q.group == _p_.group]))
        _seen.add(_p_.group)


def get_availability_preset(kind: str) -> Optional[AvailabilityPreset]:
    for preset in AVAILABILITY_PRESETS:
        if preset.kind == kind:
            return preset
    return None


def create_availability_item(kind: str) -> dict:
    preset = get_availability_preset(kind)
    params = {p.key: p.defaultValue for p in (preset.params if preset else [])}
    return {"kind": kind, "enabled": True, "params": params}


def build_availability_item_lines(item) -> list:
    enabled = item.get("enabled") if isinstance(item, dict) else getattr(item, "enabled", True)
    if enabled is False:
        return []
    kind = item["kind"] if isinstance(item, dict) else getattr(item, "kind", "")
    params = item.get("params", {}) if isinstance(item, dict) else getattr(item, "params", {})
    preset = get_availability_preset(kind)
    return preset.build(params) if preset else []


def validate_availability_item(item) -> list:
    enabled = item.get("enabled") if isinstance(item, dict) else getattr(item, "enabled", True)
    if enabled is False:
        return []
    kind = item["kind"] if isinstance(item, dict) else getattr(item, "kind", "")
    params = item.get("params", {}) if isinstance(item, dict) else getattr(item, "params", {})
    preset = get_availability_preset(kind)
    if not preset:
        return [f"Unknown availability preset {kind}."]
    issues = []
    for param in preset.params:
        cur = params.get(param.key)
        s = "" if cur is None else str(cur).strip()
        if param.required and s == "":
            issues.append(f"{preset.label} is missing {param.label}.")
    return issues
