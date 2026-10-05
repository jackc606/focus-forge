"""Static Millennium Dawn reference lists shared by the UI pickers, the
validator and the AI bridge."""
from __future__ import annotations

import re

# Focus search filters Millennium Dawn localises (verified 2026-09-24 against
# MD 2.0 — workshop items 2777392649 main and 3374271790 beta, identical content).
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
    "FOCUS_FILTER_POWER_INFRASTRUCTURE",
    "FOCUS_FILTER_RENEWABLE_ENERGY_INFRASTRUCTURE",
]

# Filters only ONE edition localises; keyed by edition key. Kept out of the
# shared list so the chip selector never offers a filter the other edition
# lacks, but the validator stays quiet about them on the right edition. Empty
# since MD 2.0 (1.x main's FOCUS_FILTER_MILITARY is no longer localised).
EDITION_ONLY_FOCUS_FILTERS = {
    "main": [],
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

# Common research-bonus categories for the add_tech_bonus picker when no game
# data is configured (with data, the picker lists every live category).
# MD 2.0 rebuilt the tech tree and its categories — verified against MD 2.0.2.
MD_TECH_CATEGORIES = [
    "CAT_industry",
    "CAT_construction",
    "CAT_energy",
    "CAT_agriculture",
    "CAT_electronics",
    "CAT_computing",
    "CAT_internet",
    "CAT_infantry_weapons",
    "CAT_artillery",
    "CAT_anti_air",
    "CAT_anti_tank",
    "CAT_armor",
    "CAT_main_battle_tanks",
    "CAT_armored_fighting_vehicles",
    "CAT_infantry_fighting_vehicles",
    "CAT_armored_personnel_carriers",
    "CAT_aircraft",
    "CAT_helicopters",
    "CAT_drones",
    "CAT_missiles",
    "CAT_naval",
    "CAT_naval_modules",
    "CAT_corvettes",
    "CAT_frigates",
    "CAT_submarines",
]

# MD 1.x tech categories that MD 2.0 dropped → the current category that holds
# (most of) the same technologies. Derived, not guessed: for each 1.x category
# (MD v1.12.3b technology_tags), the smallest 2.0.2 category containing >=90%
# of its techs that still exist; kept only where >=75% of those techs survived
# and the match is specific (>=30% of the new category). The other dropped
# categories (CAT_inf_wep, CAT_computing_tech, …) were rebuilt beyond a clean
# match — validation just asks for a current category. Used for hints only.
LEGACY_TECH_CATEGORY_HINTS = {
    "CAT_a_uav": "CAT_air_drones",
    "CAT_aa": "CAT_anti_air",
    "CAT_aa_missiles": "CAT_naval_anti_air_missiles",
    "CAT_afv": "CAT_armored_fighting_vehicles",
    "CAT_afv_weapons": "CAT_infantry_fighting_vehicles",
    "CAT_air_camera": "CAT_targeting_pods",
    "CAT_air_engine": "CAT_air_engines",
    "CAT_air_eqp": "CAT_aircraft",
    "CAT_air_ground_weapons": "CAT_air_to_ground_weapons",
    "CAT_air_naval_weapons": "CAT_air_to_naval_weapons",
    "CAT_air_wpn": "CAT_air_weapons",
    "CAT_apc": "CAT_armored_personnel_carriers",
    "CAT_armor_engines": "CAT_tank_engines",
    "CAT_armor_weapons": "CAT_tank_guns",
    "CAT_as_fighter": "CAT_medium_aircraft",
    "CAT_as_missiles": "CAT_naval_anti_ship_missiles",
    "CAT_at": "CAT_anti_tank",
    "CAT_atk_heli": "CAT_helicopters",
    "CAT_atk_sub": "CAT_attack_submarines",
    "CAT_awacs": "CAT_airborne_early_warning",
    "CAT_carrier": "CAT_aircraft_carriers",
    "CAT_cm": "CAT_cruise_missiles",
    "CAT_computer_systems": "CAT_tank_computer_systems",
    "CAT_cv": "CAT_aircraft_carriers",
    "CAT_cv_l_s_fighter": "CAT_light_aircraft",
    "CAT_cv_mr_fighter": "CAT_medium_aircraft",
    "CAT_cze": "CAT_czech_engines",
    "CAT_d_sub": "CAT_missile_submarines",
    "CAT_excavation_tech": "CAT_excavation",
    "CAT_fixed_wing": "CAT_aircraft",
    "CAT_fuel_oil": "CAT_energy",
    "CAT_glcm": "CAT_cruise_missiles",
    "CAT_gnss": "CAT_navigation_satellites",
    "CAT_h_at": "CAT_heavy_anti_tank",
    "CAT_heli": "CAT_helicopters",
    "CAT_ifv": "CAT_infantry_fighting_vehicles",
    "CAT_l_at": "CAT_light_anti_tank",
    "CAT_l_fighter": "CAT_light_aircraft",
    "CAT_l_s_fighter": "CAT_light_aircraft",
    "CAT_m_sub": "CAT_attack_submarines",
    "CAT_mbt": "CAT_tanks",
    "CAT_mr_fighter": "CAT_medium_aircraft",
    "CAT_n_cv": "CAT_aircraft_carriers",
    "CAT_naval_all": "CAT_naval",
    "CAT_naval_plane": "CAT_heavy_aircraft",
    "CAT_nuke_sub": "CAT_submarines",
    "CAT_pds": "CAT_naval_close_in_weapon_systems",
    "CAT_rec_tank": "CAT_light_tanks",
    "CAT_renewable": "CAT_renewable_energy",
    "CAT_s_fighter": "CAT_light_aircraft",
    "CAT_sam": "CAT_surface_to_air_missiles",
    "CAT_satellite": "CAT_satellites",
    "CAT_str_bomber": "CAT_heavy_aircraft",
    "CAT_sub": "CAT_submarines",
    "CAT_trans_plane": "CAT_heavy_aircraft",
    "CAT_util": "CAT_utility_vehicles",
    "CAT_vls_air_systems": "CAT_vertical_launch_anti_air_missiles",
    "CAT_vls_land_systems": "CAT_vertical_launch_surface_missiles",
    "CAT_vls_systems": "CAT_naval_vertical_launch_systems",
    "CAT_wings": "CAT_wing_designs",
}

# add_doctrine_cost_reduction categories: MD 1.x's CAT_*_doctrine tech tags →
# the doctrine-folder categories vanilla 1.19 and MD 2.0 use. One-to-one.
LEGACY_DOCTRINE_CATEGORIES = {
    "CAT_land_doctrine": "land_doctrine",
    "CAT_naval_doctrine": "naval_doctrine",
    "CAT_air_doctrine": "air_doctrine",
}
DOCTRINE_CATEGORIES = ["land_doctrine", "naval_doctrine", "air_doctrine",
                       "special_forces_doctrine", "equipment_doctrine"]
