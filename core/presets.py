"""Static Millennium Dawn reference lists shared by the UI pickers, the
validator and the AI bridge."""
from __future__ import annotations

import re

# Focus search filters localised in BOTH Millennium Dawn editions (verified
# 2026-09-05 against workshop items 2777392649 main and 3374271790 beta).
# Order matters: the inspector's chip selector shows them in this order, so
# the common ones come first. Country-specific FOCUS_FILTER_<TAG>_* filters
# are real too but must be defined by the mod itself — the validator flags
# anything outside this list as `focus.filter.nonstandard` (a warning).
MD_FOCUS_FILTERS = [
    "FOCUS_FILTER_POLITICAL",
    "FOCUS_FILTER_ECONOMY",
    "FOCUS_FILTER_INDUSTRY",
    "FOCUS_FILTER_RESEARCH",
    "FOCUS_FILTER_STABILITY",
    "FOCUS_FILTER_WAR_SUPPORT",
    "FOCUS_FILTER_FOREIGN_POLICY",
    "FOCUS_FILTER_DIPLOMACY",
    "FOCUS_FILTER_INFLUENCE",
    "FOCUS_FILTER_INTERNAL_AFFAIRS",
    "FOCUS_FILTER_INTERNAL_FACTION",
    "FOCUS_FILTER_INTERNAL_CONSOLIDATION",
    "FOCUS_FILTER_MILITARY_LAWS",
    "FOCUS_FILTER_ARMY",
    "FOCUS_FILTER_NAVY",
    "FOCUS_FILTER_AIRCRAFT",
    "FOCUS_FILTER_EQUIPMENT",
    "FOCUS_FILTER_MANPOWER",
    "FOCUS_FILTER_ANNEXATION",
    "FOCUS_FILTER_RESOURCE",
    "FOCUS_FILTER_TRADE",
    "FOCUS_FILTER_CORRUPTION",
    "FOCUS_FILTER_EXPENDITURE",
    "FOCUS_FILTER_FOREIGN_INVESTMENTS",
    "FOCUS_FILTER_INFRASTRUCTURE",
    "FOCUS_FILTER_INSURGENCY",
    "FOCUS_FILTER_PROPAGANDA",
    "FOCUS_FILTER_ENVIRONMENT",
    "FOCUS_FILTER_ADD_BUILDING",
    "FOCUS_FILTER_RADICALIZATION",
    "FOCUS_FILTER_SECTARIANISM",
    "FOCUS_FILTER_SOCIAL_CONSERVATISM",
    "FOCUS_FILTER_COUNTER_DEBUFF",
    "FOCUS_FILTER_POL_REFORM",
    "FOCUS_FILTER_ARMY_XP",
    "FOCUS_FILTER_NAVY_XP",
    "FOCUS_FILTER_AIR_XP",
    "FOCUS_FILTER_MIGRANT_CRISIS",
    "FOCUS_FILTER_NATO",
    "FOCUS_FILTER_EUROPEAN_UNION",
    "FOCUS_FILTER_MERCOSUR",
    "FOCUS_FILTER_UNASUL",
    "FOCUS_FILTER_ASEAN",
    "FOCUS_FILTER_SPACE",
]

# Filters only ONE edition localises; keyed by edition key. Kept out of the
# shared list so the chip selector never offers a filter the other edition
# lacks, but the validator stays quiet about them on the right edition.
EDITION_ONLY_FOCUS_FILTERS = {
    "main": ["FOCUS_FILTER_MILITARY"],
    "beta": [],
}

# Shape every focus filter must have to be a valid HOI4 search_filters token.
FOCUS_FILTER_PATTERN = re.compile(r"^FOCUS_FILTER_[A-Z0-9_]+$")


MD_ICON_PRESETS = [
    "MEX_Mexican_government",
    "MEX_Economic_reform",
    "army_reform",
    "military_planning",
    "research",
    "research3",
    "support_democracy",
    "communism",
    "nationalist_administration",
    "align_to_mexico",
    "align_to_venezuela",
    "focus_trade_republic",
    "industry",
    "construct_infrastructure",
    "modern_fighter",
    "MEX_The_Mexican_navy",
    "nuclear_energy",
]

# Most common country-modifier keys used by MD ideas/national spirits — seeds
# the idea editor's modifier dropdown (still free-typable for any other key).
COMMON_IDEA_MODIFIERS = [
    "stability_factor",
    "political_power_factor",
    "political_power_gain",
    "war_support_factor",
    "research_speed_factor",
    "production_speed_buildings_factor",
    "consumer_goods_factor",
    "industrial_capacity_factory",
    "industrial_capacity_dockyard",
    "monthly_population",
    "conscription_factor",
    "democratic_drift",
    "communism_drift",
    "fascism_drift",
    "neutrality_drift",
    "nationalist_drift",
    "drift_defence_factor",
    "army_org_factor",
    "army_attack_factor",
    "army_defence_factor",
    "army_morale_factor",
    "max_planning",
    "training_time_army_factor",
    "justify_war_goal_time",
    "surrender_limit",
    "corruption_cost_factor",
    "tax_gain_multiplier_modifier",
    "social_cost_multiplier_modifier",
    "foreign_influence_defense_modifier",
]

MD_TECH_CATEGORIES = [
    "CAT_industry",
    "CAT_computing_tech",
    "CAT_land_doctrine",
    "CAT_inf_wep",
    "CAT_artillery",
    "CAT_afv",
    "CAT_apc",
    "CAT_ifv",
    "CAT_air_eqp",
    "CAT_air_doctrine",
    "CAT_cas",
    "CAT_heli",
    "CAT_drones",
    "CAT_aa",
    "CAT_naval_all",
    "CAT_corvette",
    "CAT_frigate",
    "CAT_sub",
    "CAT_naval_modules",
]
