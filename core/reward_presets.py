"""Reward presets — the catalog of focus completion-reward kinds, grouped for
the picker. Each preset pairs param definitions with a pure params→lines
builder; MD scripted-effect contracts are verified against MD's own files."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from .ideologies import IDEOLOGY_TREE
from .presets import MD_TECH_CATEGORIES

# sub-ideology -> top ideology, for putting a leader's party in power.
_SUB_TOP = {sub: top for top, subs in IDEOLOGY_TREE.items() for sub in subs}


def encode_leader(name: str, ideology: str = "", picture: str = "", traits=None) -> str:
    """Pack a leader's data into one opaque param value (base64 JSON) so the pure
    reward builder can emit a full create_country_leader block from params alone."""
    payload = {"name": name or "", "ideology": ideology or "",
               "picture": picture or "", "traits": list(traits or [])}
    return base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")


def decode_leader(value) -> Optional[dict]:
    try:
        return json.loads(base64.b64decode(str(value or "")).decode("utf-8"))
    except Exception:
        return None

# ----- helpers -----------------------------------------------------------------

BUILDING_TYPES = [
    "industrial_complex",
    "arms_factory",
    "infrastructure",
    "air_base",
    "dockyard",
    "naval_base",
    "bunker",
    "coastal_bunker",
    "anti_air_building",
    "radar_station",
    "synthetic_refinery",
    "nuclear_reactor",
]

# Equipment archetypes verified against MD's common/units/equipment files
# (ids are case-sensitive; the widget stays typable for anything not listed).
EQUIPMENT_TYPES = [
    "Inf_equipment",
    "util_vehicle_equipment",
    "artillery_equipment",
    "AA_Equipment",
    "L_AT_Equipment",
    "train_equipment",
    "convoy",
    "small_plane_airframe",
    "medium_plane_airframe",
    "corvette",
    "frigate",
    "medium_tank_chassis",
    "heavy_tank_chassis",
]

RESOURCE_TYPES = ["oil", "aluminium", "rubber", "tungsten", "steel", "chromium", "coal"]

# MD internal-faction opinion helpers (common/scripted_effects/
# 00_internal_faction_effects.txt) — each reads temp_opinion and no-ops unless
# the country has the matching faction idea.
INTEREST_GROUP_EFFECTS = [
    "change_all_internal_faction_opinion",
    "change_chaebols_opinion",
    "change_communist_cadres_opinion",
    "change_defense_industry_opinion",
    "change_farmers_opinion",
    "change_foreign_jihadis_opinion",
    "change_fossil_fuel_industry_opinion",
    "change_industrial_conglomerates_opinion",
    "change_intelligence_community_opinion",
    "change_international_bankers_opinion",
    "change_iranian_quds_force_opinion",
    "change_labour_unions_opinion",
    "change_landowners_opinion",
    "change_maritime_industry_opinion",
    "change_oligarchs_opinion",
    "change_saudi_royal_family_opinion",
    "change_small_medium_business_owners_opinion",
    "change_the_clergy_opinion",
    "change_the_donju_opinion",
    "change_the_military_opinion",
    "change_the_priesthood_opinion",
    "change_the_ulema_opinion",
    "change_the_wahabi_ulema_opinion",
    "change_wall_street_opinion",
]

WARGOAL_TYPES = [
    "take_state_focus",
    "puppet_wargoal_focus",
    "annex_everything",
    "topple_government",
    "civil_war",
]


def format_number(value) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "0"
    if f.is_integer():
        return str(int(f))
    s = f"{f:.3f}".rstrip("0").rstrip(".")
    return s


def _value(params: dict, key: str) -> str:
    raw = params.get(key, "")
    if raw is None:
        raw = ""
    return str(raw).strip()


def _number_value(params: dict, key: str) -> str:
    raw = params.get(key, 0)
    if raw is None or raw == "":
        raw = 0
    return format_number(raw)


def _maybe_line(line: str, predicate: bool) -> list:
    return [line] if predicate else []


def _block(name: str, lines: list) -> list:
    return [f"{name} = {{", *[f"\t{ln}" for ln in lines], "}"]


# ----- tooltip help text -------------------------------------------------------

CONTEXTUAL_PARAM_HELP: dict = {
    "tech_bonus.name": "Internal name for this research bonus. It can be any stable ID-like text and is mainly useful for debugging or repeated bonuses.",
    "tech_bonus.bonus": "Research speed multiplier. 0.5 means a 50% research bonus, 1 means a 100% bonus.",
    "tech_bonus.uses": "How many technologies can consume this research bonus.",
    "tech_bonus.category": "Millennium Dawn technology category affected by the bonus.",
    "promote_leader.leader": "The leader to install. The list is grouped into this country's preset Millennium Dawn leaders and your own custom leaders (from the Country editor).",
    "promote_leader.setRuling": "When yes, also switches the ruling party to this leader's ideology so they actually take power. Set to no to just (re)define the leader without changing who governs.",
    "treasury_change.amount": "Money added to or removed from the Millennium Dawn treasury helper. Positive values add funds; negative values spend funds.",
    "domestic_influence.percent": "Percent change applied to domestic influence through Millennium Dawn scripted effects.",
    "foreign_influence.percent": "Percent influence gained or lost by the influencer country over the target country.",
    "foreign_influence.influencerTag": "Country tag receiving influence, such as USA, SOV, CHI, or MEX.",
    "foreign_influence.targetTag": "Country tag being influenced, usually the country whose focus is completing.",
    "relative_party_popularity.partyIndex": "Which MD party's popularity to shift. MD uses one global party list (the same index = the same party in every country), so this picks from all 24 MD parties by name.",
    "relative_party_popularity.popularity": "Relative popularity added to that party or outlook. Use decimals such as 0.05 for a modest shift.",
    "relative_party_popularity.outlook": "Optional outlook movement. Leave 0 for a pure "
                                         "relative shift; any nonzero value switches the MD "
                                         "helper to its additive mode, also moving the whole "
                                         "ideology group's popularity.",
    "interest_group_opinion.amount": "Opinion shift stored before calling the selected Millennium Dawn interest-group helper.",
    "interest_group_opinion.effect": "Scripted MD helper to call, such as change_farmers_opinion or change_the_military_opinion.",
    "add_resource.state": "Numeric HOI4 state ID where the resource will be added.",
    "add_resource.type": "Resource type to add to the selected state.",
    "add_resource.amount": "Amount of the resource added to the selected state.",
    "timed_resource.type": "Resource type granted for the duration.",
    "timed_resource.amount": "Amount of the resource granted while the deal lasts.",
    "timed_resource.state": "One of YOUR state IDs that receives the resource.",
    "timed_resource.days": "How many days the resource lasts before it expires (e.g. 730 = 2 years).",
    "state_building.state": "Numeric HOI4 state ID where construction is added.",
    "state_building.building": "Building type to construct instantly in the selected state "
                               "— infrastructure, factories, air bases, or any MD building id. "
                               "Slot-consuming factories also get a free shared building slot.",
    "state_building.level": "Number of building levels to add.",
    "state_building.province": "Province id inside the state — required for province-level "
                               "buildings (naval base, bunker, coastal bunker); leave blank "
                               "for normal state buildings like infrastructure or factories.",
    "equipment_stockpile.type": "Equipment archetype added to the country stockpile. The ID must exist in Millennium Dawn.",
    "equipment_stockpile.amount": "Number of equipment pieces added to the stockpile.",
    "equipment_stockpile.producer": "Optional country tag credited as the equipment source or manufacturer, such as USA, SOV, CHI, or MEX. Leave blank to avoid assigning a foreign producer.",
    "opinion_modifier.target": "Country the opinion modifier is applied toward (the country that 'gains' the opinion), usually a three-letter HOI4 tag.",
    "opinion_modifier.modifier": "Named opinion modifier from common/opinion_modifiers — the dropdown shows each one's opinion value (e.g. declaration_of_friendship is +25). The value lives in the modifier definition, not here.",
    "reverse_opinion_modifier.target": "Country tag that will add the opinion modifier toward ROOT.",
    "reverse_opinion_modifier.modifier": "Named opinion modifier the target adds toward ROOT; the dropdown shows each one's value.",
    "create_wargoal.target": "Country tag that the wargoal is created against.",
    "create_wargoal.type": "Wargoal type used by HOI4 or Millennium Dawn, such as puppet_wargoal_focus.",
    "productivity_growth.amount": "Flat productivity change added to every state (MD), in percentage points on a 100 base. ~25 is a solid boost, 50 is large; negative cuts it (e.g. a crisis).",
    "state_productivity.state": "Numeric HOI4 state id whose productivity is changed.",
    "state_productivity.amount": "Productivity points added to that one state (MD, base 100). ~25 solid, 50 large; negative reduces.",
    "economic_growth.times": "How many times to trigger Millennium Dawn's one-shot GDP growth boost.",
    "agriculture_district.count": "How many random agriculture districts to build, raising farming output (MD).",
    "corporate_tax.amount": "Percentage-point change to the corporate tax rate. Positive raises taxes, negative cuts them (e.g. -5).",
    "radicalization.amount": "Change to national radicalization. Negative values reduce unrest (e.g. -5).",
    "hydroelectric_dam.state": "Numeric HOI4 state id where the dam sits (the state containing the reservoir).",
    "hydroelectric_dam.production": "Hydroelectric power added to that state's grid, in gigawatts (MD energy system). Tabqa Dam is about 0.8.",
    "hydroelectric_dam.tooltip": "Optional localization key for a readable tooltip; when set, the raw variable changes are hidden behind it (the MD convention).",
    "income_tax.amount": "Change to the personal/population income tax rate (MD). Positive raises taxes (more revenue, less consumer spending); negative cuts them.",
    "national_debt.amount": "Change to national debt (MD). Negative pays debt down; positive takes on debt.",
    "international_investment.amount": "Change to international investment inflow (MD). Positive attracts more foreign investment.",
    "government_expenses.amount": "Change to recurring government expenses (MD budget). Positive raises spending.",
    "urban_development_fund.amount": "Amount added to the urban development fund (MD).",
}

SHARED_PARAM_HELP: dict = {
    "amount": "Numeric value used by this reward. Negative values usually remove or spend the same thing.",
    "idea": "Idea or national spirit ID from common/ideas.",
    "removeIdea": "Existing idea ID to remove from the country.",
    "addIdea": "New idea ID to add to the country.",
    "days": "Delay or duration in in-game days.",
    "eventId": "Country event ID, including namespace, such as MEX_forge.1.",
    "tooltipId": "Localization key for the custom effect tooltip shown to the player.",
    "flag": "Country flag ID used by later triggers, events, or availability rules.",
    "target": "Country tag affected by this reward, usually a three-letter HOI4 tag.",
    "modifier": "Modifier ID from the game or mod files.",
    "variable": "Variable name exactly as expected by the script or MD helper.",
}

# ----- preset shape ------------------------------------------------------------


@dataclass
class RewardParamDef:
    key: str
    label: str
    type: str  # 'string' | 'number' | 'select' | 'textarea'
    defaultValue: object = ""
    required: bool = False
    step: Optional[float] = None
    options: Optional[list] = None
    placeholder: Optional[str] = None
    helpText: Optional[str] = None


@dataclass
class RewardPreset:
    kind: str
    group: str
    label: str
    description: str
    params: list = field(default_factory=list)  # list[RewardParamDef]
    build: Callable[[dict], list] = field(default=lambda p: [])


# ----- preset builders ---------------------------------------------------------

def _b_political_power(p): return [f"add_political_power = {_number_value(p, 'amount')}"]
def _b_stability(p): return [f"add_stability = {_number_value(p, 'amount')}"]
def _b_war_support(p): return [f"add_war_support = {_number_value(p, 'amount')}"]
def _b_command_power(p): return [f"add_command_power = {_number_value(p, 'amount')}"]
def _b_army_xp(p): return [f"army_experience = {_number_value(p, 'amount')}"]
def _b_air_xp(p): return [f"air_experience = {_number_value(p, 'amount')}"]
def _b_navy_xp(p): return [f"navy_experience = {_number_value(p, 'amount')}"]
def _b_promote_leader(p):
    """Install a specific leader (create_country_leader) and optionally make their
    ideology the ruling party — i.e. put them in power."""
    data = decode_leader(p.get("leader", ""))
    if not data or not (data.get("name") or "").strip():
        return []
    inner = [f'name = "{data["name"]}"']
    if data.get("picture"):
        inner.append(f'picture = "{data["picture"]}"')
    ideo = (data.get("ideology") or "").strip()
    if ideo == "State":  # legacy token from before the rename — MD's id is Communist-State
        ideo = "Communist-State"
    if ideo:
        inner.append(f"ideology = {ideo}")
    traits = [t for t in (data.get("traits") or []) if t]
    if traits:
        inner.append("traits = { " + " ".join(traits) + " }")
    lines = _block("create_country_leader", inner)
    if str(p.get("setRuling", "yes")).strip().lower() in ("yes", "true", "1"):
        top = _SUB_TOP.get(ideo)
        if top:
            lines += _block("set_politics", [f"ruling_party = {top}"])
    return lines


def _b_add_idea(p): return [f"add_ideas = {_value(p, 'idea')}"]
def _b_remove_idea(p): return [f"remove_ideas = {_value(p, 'idea')}"]


def _b_timed_idea(p):
    return [f"add_timed_idea = {{ idea = {_value(p, 'idea')} days = {_number_value(p, 'days')} }}"]


def _b_swap_idea(p):
    return _block(
        "swap_ideas",
        [f"remove_idea = {_value(p, 'removeIdea')}", f"add_idea = {_value(p, 'addIdea')}"],
    )


def _event_days_suffix(p) -> str:
    raw_days = p.get("days", 0)
    try:
        days = int(float(raw_days)) if raw_days not in ("", None) else 0
    except (TypeError, ValueError):
        days = 0
    return f" days = {days}" if days > 0 else ""


def _b_country_event(p):
    return [f"country_event = {{ id = {_value(p, 'eventId')}{_event_days_suffix(p)} }}"]


def _b_news_event(p):
    return [f"news_event = {{ id = {_value(p, 'eventId')}{_event_days_suffix(p)} }}"]


def _b_custom_tooltip(p): return [f"custom_effect_tooltip = {_value(p, 'tooltipId')}"]
def _b_set_country_flag(p): return [f"set_country_flag = {_value(p, 'flag')}"]
def _b_clear_country_flag(p): return [f"clr_country_flag = {_value(p, 'flag')}"]


def _b_tech_bonus(p):
    return _block(
        "add_tech_bonus",
        [
            *_maybe_line(f"name = {_value(p, 'name')}", bool(_value(p, "name"))),
            f"bonus = {_number_value(p, 'bonus')}",
            f"uses = {_number_value(p, 'uses')}",
            f"category = {_value(p, 'category')}",
        ],
    )


def _b_treasury_change(p):
    return [
        f"set_temp_variable = {{ treasury_change = {_number_value(p, 'amount')} }}",
        "modify_treasury_effect = yes",
    ]


def _repeat_count(p, key, default=1):
    raw = p.get(key, default)
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        return 1


def _b_productivity_growth(p):
    return [
        f"set_temp_variable = {{ temp_productivity_change = {_number_value(p, 'amount')} }}",
        "flat_productivity_change_effect = yes",
    ]


def _b_state_productivity(p):
    return [f"set_temp_variable = {{ temp_productivity_change = {_number_value(p, 'amount')} }}",
            f"{_number_value(p, 'state')} = {{ state_flat_productivity_change_effect = yes }}"]


def _b_economic_growth(p):
    return ["increase_economic_growth = yes"] * _repeat_count(p, "times")


def _b_agriculture_district(p):
    return ["one_random_agriculture_district = yes"] * _repeat_count(p, "count")


def _b_corporate_tax(p):
    return [
        f"set_temp_variable = {{ corp_change = {_number_value(p, 'amount')} }}",
        "modify_corporate_tax_rate_effect = yes",
    ]


def _b_radicalization(p):
    return [
        f"set_temp_variable = {{ rad_change = {_number_value(p, 'amount')} }}",
        "modify_radicalization_effect = yes",
    ]


def _b_income_tax(p):
    return [f"set_temp_variable = {{ pop_change = {_number_value(p, 'amount')} }}",
            "modify_population_tax_rate_effect = yes"]


def _b_national_debt(p):
    return [f"set_temp_variable = {{ debt_change = {_number_value(p, 'amount')} }}",
            "modify_debt_effect = yes"]


def _b_intl_investment(p):
    return [f"set_temp_variable = {{ int_investment_change = {_number_value(p, 'amount')} }}",
            "modify_international_investment_effect = yes"]


def _b_govt_expenses(p):
    return [f"set_temp_variable = {{ additional_expenses_change = {_number_value(p, 'amount')} }}",
            "modify_additional_expenses_effect = yes"]


def _b_urban_dev_fund(p):
    return [f"set_temp_variable = {{ temp_change = {_number_value(p, 'amount')} }}",
            "modify_urban_development_fund_effect = yes"]


def _b_hydroelectric_dam(p):
    # MD's additive helper (!_energy_effects.txt) adds to the state's existing
    # hydro production and guards the modifier add — a plain set_variable would
    # overwrite any dams the state already has.
    inner = [
        f"{_number_value(p, 'state')} = {{",
        f"\tset_temp_variable = {{ electric_addition = {_number_value(p, 'production')} }}",
        "\tset_temp_variable = { storage_addition = 0 }",
        "\tadd_hydroelectric_energy_production_effect = yes",
        "}",
    ]
    tt = _value(p, "tooltip")
    if tt:
        return [f"custom_effect_tooltip = {tt}", "hidden_effect = {",
                *[f"\t{ln}" for ln in inner], "}"]
    return inner


def _b_domestic_influence(p):
    return [
        f"set_temp_variable = {{ percent_change = {_number_value(p, 'percent')} }}",
        "change_domestic_influence_percentage = yes",
    ]


def _b_foreign_influence(p):
    return [
        f"set_temp_variable = {{ percent_change = {_number_value(p, 'percent')} }}",
        f"set_temp_variable = {{ tag_index = {_value(p, 'influencerTag')} }}",
        f"set_temp_variable = {{ influence_target = {_value(p, 'targetTag')} }}",
        "change_influence_percentage = yes",
    ]


def _b_relative_party_popularity(p):
    return [
        f"set_temp_variable = {{ party_index = {_number_value(p, 'partyIndex')} }}",
        f"set_temp_variable = {{ party_popularity_increase = {_number_value(p, 'popularity')} }}",
        f"set_temp_variable = {{ temp_outlook_increase = {_number_value(p, 'outlook')} }}",
        "add_relative_party_popularity = yes",
    ]


def _b_interest_group_opinion(p):
    return [
        f"set_temp_variable = {{ temp_opinion = {_number_value(p, 'amount')} }}",
        f"{_value(p, 'effect')} = yes",
    ]


def _b_add_manpower(p): return [f"add_manpower = {_number_value(p, 'amount')}"]


def _b_add_resource(p):
    return [
        f"add_resource = {{ type = {_value(p, 'type')} amount = {_number_value(p, 'amount')} state = {_number_value(p, 'state')} }}"
    ]


def _b_timed_resource(p):
    return [
        f"add_resource = {{ type = {_value(p, 'type')} amount = {_number_value(p, 'amount')} state = {_number_value(p, 'state')} days = {_number_value(p, 'days')} }}"
    ]


# Buildings with shares_slots = yes in MD's common/buildings/00_buildings.txt —
# only these get a free slot alongside the construction so the reward never
# overfills a full state. Everything else (infrastructure, air bases, radar,
# MD's renewable-energy "synthetic_refinery", …) has its own row and must NOT
# grant a shared slot as a side effect.
_SHARED_SLOT_BUILDINGS = {
    "industrial_complex", "arms_factory", "dockyard", "offices",
    "agriculture_district", "stronghold_network", "naval_headquarters",
    "energy_infrastructure", "industrial_infrastructure",
}


def _b_state_building(p):
    building = _value(p, "building")
    lines = []
    if building in _SHARED_SLOT_BUILDINGS:
        lines.append("add_extra_state_shared_building_slots = 1")
    # Province-level buildings (naval_base, bunker, coastal_bunker, …) need an
    # explicit province inside the construction block or HOI4 ignores them.
    province = _value(p, "province")
    prov = f" province = {province}" if province not in ("", "0") else ""
    lines.append(
        f"add_building_construction = {{ type = {building}{prov} level = {_number_value(p, 'level')} instant_build = yes }}")
    return _block(f"{_number_value(p, 'state')}", lines)


def _b_equipment_stockpile(p):
    return _block(
        "add_equipment_to_stockpile",
        [
            f"type = {_value(p, 'type')}",
            f"amount = {_number_value(p, 'amount')}",
            *_maybe_line(f"producer = {_value(p, 'producer')}", bool(_value(p, "producer"))),
        ],
    )


def _b_opinion_modifier(p):
    return [
        f"add_opinion_modifier = {{ target = {_value(p, 'target')} modifier = {_value(p, 'modifier')} }}"
    ]


def _b_reverse_opinion_modifier(p):
    return [
        f"reverse_add_opinion_modifier = {{ target = {_value(p, 'target')} modifier = {_value(p, 'modifier')} }}"
    ]


def _b_create_wargoal(p):
    return _block(
        "create_wargoal",
        [f"type = {_value(p, 'type')}", f"target = {_value(p, 'target')}"],
    )


def _b_puppet(p):
    return [f"puppet = {_value(p, 'target')}"]


def _b_annex(p):
    return [f"annex_country = {{ target = {_value(p, 'target')} transfer_troops = yes }}"]


def _b_add_variable(p):
    return [f"add_to_variable = {{ {_value(p, 'variable')} = {_number_value(p, 'amount')} }}"]


def _b_set_variable(p):
    return [f"set_variable = {{ {_value(p, 'variable')} = {_number_value(p, 'amount')} }}"]


def _b_set_temp_variable(p):
    return [f"set_temp_variable = {{ {_value(p, 'variable')} = {_number_value(p, 'amount')} }}"]


# ----- preset definitions ------------------------------------------------------

_RAW_PRESETS = [
    RewardPreset("political_power", "Political", "Political Power", "Adds vanilla political power.",
                 [RewardParamDef("amount", "Amount", "number", 50, required=True)], _b_political_power),
    RewardPreset("stability", "Political", "Stability", "Adds stability as a decimal, so 0.05 is 5%.",
                 [RewardParamDef("amount", "Amount", "number", 0.05, required=True, step=0.01)], _b_stability),
    RewardPreset("war_support", "Political", "War Support", "Adds war support as a decimal.",
                 [RewardParamDef("amount", "Amount", "number", 0.05, required=True, step=0.01)], _b_war_support),
    RewardPreset("command_power", "Political", "Command Power", "Adds command power.",
                 [RewardParamDef("amount", "Amount", "number", 10, required=True)], _b_command_power),
    RewardPreset("promote_leader", "Leaders", "Put Leader in Power",
                 "Installs a specific country leader (create_country_leader) and, by "
                 "default, makes their ideology the ruling party. Choose one of the "
                 "country's preset Millennium Dawn leaders or your own custom leaders.",
                 [RewardParamDef("leader", "Leader", "leader_ref", "", required=True),
                  RewardParamDef("setRuling", "Make ruling party", "select", "yes",
                                 options=["yes", "no"])], _b_promote_leader),
    RewardPreset("army_experience", "Experience", "Army XP", "Adds army experience.",
                 [RewardParamDef("amount", "Amount", "number", 10, required=True)], _b_army_xp),
    RewardPreset("air_experience", "Experience", "Air XP", "Adds air experience.",
                 [RewardParamDef("amount", "Amount", "number", 10, required=True)], _b_air_xp),
    RewardPreset("navy_experience", "Experience", "Navy XP", "Adds navy experience.",
                 [RewardParamDef("amount", "Amount", "number", 10, required=True)], _b_navy_xp),
    RewardPreset("add_idea", "Ideas", "Add Idea", "Adds an existing national spirit / idea (or use “New Idea” to author one).",
                 [RewardParamDef("idea", "Idea", "idea_ref", "", required=True, placeholder="MEX_new_idea")], _b_add_idea),
    RewardPreset("remove_idea", "Ideas", "Remove Idea", "Removes an idea.",
                 [RewardParamDef("idea", "Idea", "idea_ref", "", required=True)], _b_remove_idea),
    RewardPreset("timed_idea", "Ideas", "Timed Idea", "Adds an idea for a fixed number of days.",
                 [RewardParamDef("idea", "Idea", "idea_ref", "", required=True),
                  RewardParamDef("days", "Days", "number", 365, required=True)], _b_timed_idea),
    RewardPreset("swap_idea", "Ideas", "Swap Idea", "Replaces one idea with another.",
                 [RewardParamDef("removeIdea", "Remove Idea", "idea_ref", "", required=True),
                  RewardParamDef("addIdea", "Add Idea", "idea_ref", "", required=True)], _b_swap_idea),
    RewardPreset("country_event", "Events and Flags", "Country Event", "Fires a country event immediately or after a delay.",
                 [RewardParamDef("eventId", "Event ID", "event_ref", "", required=True, placeholder="MEX_forge.1"),
                  RewardParamDef("days", "Delay Days", "number", 0)], _b_country_event),
    RewardPreset("news_event", "Events and Flags", "News Event", "Fires a news event (shown to every country) immediately or after a delay.",
                 [RewardParamDef("eventId", "Event ID", "event_ref", "", required=True, placeholder="MEX_forge.2"),
                  RewardParamDef("days", "Delay Days", "number", 0)], _b_news_event),
    RewardPreset("custom_tooltip", "Events and Flags", "Custom Tooltip", "Shows a custom effect tooltip.",
                 [RewardParamDef("tooltipId", "Tooltip Loc Key", "string", "", required=True)], _b_custom_tooltip),
    RewardPreset("set_country_flag", "Events and Flags", "Set Country Flag", "Sets a country flag for later triggers or event logic.",
                 [RewardParamDef("flag", "Flag", "string", "", required=True)], _b_set_country_flag),
    RewardPreset("clear_country_flag", "Events and Flags", "Clear Country Flag", "Clears a country flag.",
                 [RewardParamDef("flag", "Flag", "string", "", required=True)], _b_clear_country_flag),
    RewardPreset("tech_bonus", "Research", "Tech Bonus", "Adds a research bonus for a MD tech category.",
                 [RewardParamDef("name", "Bonus Name", "string", "focus_research_bonus"),
                  RewardParamDef("bonus", "Bonus", "number", 0.5, required=True, step=0.05),
                  RewardParamDef("uses", "Uses", "number", 1, required=True),
                  RewardParamDef("category", "Category", "tech_category", "CAT_industry", required=True)], _b_tech_bonus),
    RewardPreset("treasury_change", "Millennium Dawn Economy", "Treasury Change", "Uses the common MD treasury helper pattern.",
                 [RewardParamDef("amount", "Treasury Change", "number", 1, required=True, step=0.1)], _b_treasury_change),
    RewardPreset("productivity_growth", "Millennium Dawn Economy", "Productivity Growth",
                 "Flat productivity change across all your states on MD's internal scale "
                 "(states start around 550-1000). 25-50 matches MD's own focuses; negative cuts it.",
                 [RewardParamDef("amount", "Productivity Change", "number", 25, required=True, step=5)], _b_productivity_growth),
    RewardPreset("state_productivity", "Millennium Dawn Economy", "State Productivity",
                 "Flat productivity change for ONE state on MD's internal scale (states "
                 "start around 550-1000). MD's own focuses typically grant 25-50.",
                 [RewardParamDef("state", "State", "state", "", required=True),
                  RewardParamDef("amount", "Productivity Change", "number", 25, required=True, step=5)], _b_state_productivity),
    RewardPreset("economic_growth", "Millennium Dawn Economy", "Economic Growth (GDP)",
                 "Triggers MD's one-shot GDP growth boost, once or several times. At the "
                 "maximum growth level each extra call grants 100 PP + 5% stability instead.",
                 [RewardParamDef("times", "Times", "number", 1, required=True)], _b_economic_growth),
    RewardPreset("agriculture_district", "Millennium Dawn Economy", "Agriculture District",
                 "Builds random agriculture districts, raising farming output (MD).",
                 [RewardParamDef("count", "Count", "number", 1, required=True)], _b_agriculture_district),
    RewardPreset("corporate_tax", "Millennium Dawn Economy", "Corporate Tax Change",
                 "Changes the corporate tax rate (MD). Positive raises taxes, negative cuts them.",
                 [RewardParamDef("amount", "Tax Change", "number", -5, required=True)], _b_corporate_tax),
    RewardPreset("radicalization", "Millennium Dawn Politics", "Radicalization Change",
                 "Changes national radicalization (MD counter-terror system). Negative reduces unrest.",
                 [RewardParamDef("amount", "Radicalization Change", "number", -5, required=True)], _b_radicalization),
    RewardPreset("income_tax", "Millennium Dawn Economy", "Personal Income Tax",
                 "Changes the personal/population income tax rate (MD). Positive raises taxes, negative cuts them.",
                 [RewardParamDef("amount", "Tax Change", "number", -4, required=True)], _b_income_tax),
    RewardPreset("national_debt", "Millennium Dawn Economy", "National Debt",
                 "Changes national debt (MD). Negative pays it down; positive takes on debt.",
                 [RewardParamDef("amount", "Debt Change", "number", -5, required=True)], _b_national_debt),
    RewardPreset("international_investment", "Millennium Dawn Economy", "International Investment",
                 "Changes international investment inflow (MD). Positive attracts foreign investment.",
                 [RewardParamDef("amount", "Investment Change", "number", 3.5, required=True, step=0.5)], _b_intl_investment),
    RewardPreset("government_expenses", "Millennium Dawn Economy", "Government Expenses (Italy only)",
                 "Changes recurring government expenses. The MD helper behind this writes an "
                 "Italy-specific budget variable — for any other country it does nothing.",
                 [RewardParamDef("amount", "Expense Change", "number", 0.2, required=True, step=0.1)], _b_govt_expenses),
    RewardPreset("urban_development_fund", "Millennium Dawn Economy", "Urban Development Fund (Denmark only)",
                 "Adds to the urban development fund. The MD helper behind this writes a "
                 "Denmark-specific variable — for any other country it does nothing.",
                 [RewardParamDef("amount", "Amount", "number", 10, required=True)], _b_urban_dev_fund),
    RewardPreset("hydroelectric_dam", "Millennium Dawn Economy", "Hydroelectric Dam",
                 "Adds MD hydroelectric power to a state via MD's additive helper (stacks "
                 "with existing dams). Production is in GW (0.8 is about 800 MW).",
                 [RewardParamDef("state", "State", "state", "", required=True),
                  RewardParamDef("production", "Production (GW)", "number", 0.8, required=True, step=0.1),
                  RewardParamDef("tooltip", "Tooltip Key", "string", "", placeholder="TT_SYR_TABQA_DAM_HYDRO")],
                 _b_hydroelectric_dam),
    RewardPreset("domestic_influence", "Millennium Dawn Politics", "Domestic Influence", "Changes domestic influence percentage through the MD helper.",
                 [RewardParamDef("percent", "Percent Change", "number", 5, required=True)], _b_domestic_influence),
    RewardPreset("foreign_influence", "Millennium Dawn Politics", "Foreign Influence", "Changes a tag influence percentage over a target country.",
                 [RewardParamDef("percent", "Percent Change", "number", 5, required=True),
                  RewardParamDef("influencerTag", "Influencer", "country_tag", "", required=True),
                  RewardParamDef("targetTag", "Target", "country_tag", "", required=True)], _b_foreign_influence),
    RewardPreset("relative_party_popularity", "Millennium Dawn Politics", "Relative Party Popularity", "Uses the MD party popularity helper. Pick the party whose popularity shifts.",
                 [RewardParamDef("partyIndex", "Party", "party_index", 14, required=True),
                  RewardParamDef("popularity", "Popularity Increase", "number", 0.05, required=True, step=0.01),
                  RewardParamDef("outlook", "Outlook Increase", "number", 0, step=0.01)], _b_relative_party_popularity),
    RewardPreset("interest_group_opinion", "Millennium Dawn Politics", "Interest Group Opinion",
                 "Shifts an MD internal faction's opinion. Only does something if the country "
                 "actually has that faction's idea; autocratic governments double positive shifts.",
                 [RewardParamDef("amount", "Opinion Change", "number", 5, required=True),
                  RewardParamDef("effect", "Interest Group", "select", "change_farmers_opinion",
                                 required=True, options=INTEREST_GROUP_EFFECTS)], _b_interest_group_opinion),
    RewardPreset("add_manpower", "State and Material", "Manpower", "Adds manpower.",
                 [RewardParamDef("amount", "Amount", "number", 10000, required=True)], _b_add_manpower),
    RewardPreset("add_resource", "State and Material", "State Resource", "Adds resources to a state.",
                 [RewardParamDef("state", "State", "state", "", required=True),
                  RewardParamDef("type", "Resource", "select", "steel", required=True, options=RESOURCE_TYPES),
                  RewardParamDef("amount", "Amount", "number", 4, required=True)], _b_add_resource),
    RewardPreset("timed_resource", "State and Material", "Timed Resource", "Adds a resource to one of your states for a limited time (e.g. a 730-day deal). Name the donor country in the focus text.",
                 [RewardParamDef("type", "Resource", "select", "oil", required=True, options=RESOURCE_TYPES),
                  RewardParamDef("amount", "Amount", "number", 8, required=True),
                  RewardParamDef("state", "State", "state", "", required=True),
                  RewardParamDef("days", "Days", "number", 730, required=True)], _b_timed_resource),
    RewardPreset("state_building", "State and Material", "State Building",
                 "Instantly builds levels of a building (infrastructure, factories, …) in a specific state.",
                 [RewardParamDef("state", "State", "state", "", required=True),
                  RewardParamDef("building", "Building", "building", "industrial_complex", required=True),
                  RewardParamDef("level", "Level", "number", 1, required=True),
                  RewardParamDef("province", "Province", "string", "",
                                 placeholder="needed for naval base / bunker")], _b_state_building),
    RewardPreset("equipment_stockpile", "State and Material", "Equipment Stockpile", "Adds equipment, optionally with a producer tag.",
                 [RewardParamDef("type", "Equipment Type", "equipment", "Inf_equipment", required=True, options=EQUIPMENT_TYPES),
                  RewardParamDef("amount", "Amount", "number", 1000, required=True),
                  RewardParamDef("producer", "Producer", "country_tag", "")], _b_equipment_stockpile),
    RewardPreset("opinion_modifier", "Diplomacy and War", "Opinion Modifier", "Adds an opinion modifier toward another country (e.g. USA gains +25).",
                 [RewardParamDef("target", "Target", "country_tag", "", required=True),
                  RewardParamDef("modifier", "Modifier", "opinion_modifier", "", required=True)], _b_opinion_modifier),
    RewardPreset("reverse_opinion_modifier", "Diplomacy and War", "Reverse Opinion Modifier", "Makes the target add an opinion modifier toward ROOT.",
                 [RewardParamDef("target", "Target", "country_tag", "", required=True),
                  RewardParamDef("modifier", "Modifier", "opinion_modifier", "", required=True)], _b_reverse_opinion_modifier),
    RewardPreset("create_wargoal", "Diplomacy and War", "Create Wargoal", "Creates a wargoal against a target.",
                 [RewardParamDef("target", "Target", "country_tag", "", required=True),
                  RewardParamDef("type", "Wargoal Type", "select", "puppet_wargoal_focus", required=True, options=WARGOAL_TYPES)], _b_create_wargoal),
    RewardPreset("puppet", "Diplomacy and War", "Puppet Country", "Makes the target country a puppet/subject of this country.",
                 [RewardParamDef("target", "Target", "country_tag", "", required=True)], _b_puppet),
    RewardPreset("annex", "Diplomacy and War", "Annex Country", "Annexes the target country (its troops transfer to you).",
                 [RewardParamDef("target", "Target", "country_tag", "", required=True)], _b_annex),
    RewardPreset("add_variable", "Variables", "Add To Variable", "Adds to a variable. Useful for MD arrays and country-specific mechanics.",
                 [RewardParamDef("variable", "Variable", "string", "", required=True, placeholder="party_pop_array^1"),
                  RewardParamDef("amount", "Amount", "number", 1, required=True, step=0.01)], _b_add_variable),
    RewardPreset("set_variable", "Variables", "Set Variable", "Sets a variable.",
                 [RewardParamDef("variable", "Variable", "string", "", required=True),
                  RewardParamDef("amount", "Value", "number", 1, required=True, step=0.01)], _b_set_variable),
    RewardPreset("set_temp_variable", "Variables", "Set Temp Variable", "Sets a temporary variable before a scripted helper effect.",
                 [RewardParamDef("variable", "Variable", "string", "", required=True),
                  RewardParamDef("amount", "Value", "number", 1, required=True, step=0.01)], _b_set_temp_variable),
]


def _attach_help(preset: RewardPreset) -> RewardPreset:
    for param in preset.params:
        if param.helpText:
            continue
        param.helpText = (
            CONTEXTUAL_PARAM_HELP.get(f"{preset.kind}.{param.key}")
            or SHARED_PARAM_HELP.get(param.key)
            or f"{param.label} value used by the generated HOI4 reward effect."
        )
    return preset


REWARD_PRESETS: list[RewardPreset] = [_attach_help(p) for p in _RAW_PRESETS]

REWARD_PRESET_GROUPS: list[tuple[str, list[RewardPreset]]] = []
_seen = set()
for _p in REWARD_PRESETS:
    if _p.group not in _seen:
        REWARD_PRESET_GROUPS.append((_p.group, [q for q in REWARD_PRESETS if q.group == _p.group]))
        _seen.add(_p.group)


def get_reward_preset(kind: str) -> Optional[RewardPreset]:
    for preset in REWARD_PRESETS:
        if preset.kind == kind:
            return preset
    return None


def create_reward_item(kind: str) -> dict:
    preset = get_reward_preset(kind)
    params = {param.key: param.defaultValue for param in (preset.params if preset else [])}
    return {"kind": kind, "enabled": True, "params": params}


def build_reward_item_lines(item) -> list:
    enabled = item.get("enabled") if isinstance(item, dict) else getattr(item, "enabled", True)
    if enabled is False:
        return []
    kind = item["kind"] if isinstance(item, dict) else getattr(item, "kind", "")
    params = item.get("params", {}) if isinstance(item, dict) else getattr(item, "params", {})
    preset = get_reward_preset(kind)
    return preset.build(params) if preset else []


def validate_reward_item(item) -> list:
    enabled = item.get("enabled") if isinstance(item, dict) else getattr(item, "enabled", True)
    if enabled is False:
        return []
    kind = item["kind"] if isinstance(item, dict) else getattr(item, "kind", "")
    params = item.get("params", {}) if isinstance(item, dict) else getattr(item, "params", {})
    preset = get_reward_preset(kind)
    if not preset:
        return [f"Unknown reward preset {kind}."]

    issues: list = []
    for param in preset.params:
        current = params.get(param.key)
        s = "" if current is None else str(current).strip()
        if param.required and s == "":
            issues.append(f"{preset.label} is missing {param.label}.")
        if param.type in ("number", "state", "party_index") and s != "":
            try:
                float(current)
            except (TypeError, ValueError):
                issues.append(f"{preset.label} has an invalid number for {param.label}.")
                continue
            # State ids start at 1 — a 0/negative value exports a broken block.
            if param.type == "state" and float(current) < 1:
                issues.append(f"{preset.label} needs a real state id (1 or higher) for {param.label}.")
    return issues
