"""Tests for the idea-modifier index (base-doc parse + MD-idea harvest + grouping)."""
from __future__ import annotations

from core.modifier_index import (
    GROUP_ORDER,
    build_base_modifier_names,
    build_common_modifiers,
    build_md_idea_modifier_keys,
    build_modifier_groups,
    build_modifier_names,
    build_modifier_tooltips,
    classify_modifier,
)

_DOC = """# Modifiers

## Table of Content

* [country](#modifiers-for-scope-country)
* [politics](#modifiers-for-scope-politics)

## Modifiers for scope country

* [stability_factor](#stability_factor)
* [war_support_factor](#war_support_factor)
* [trade_opinion_factor](#trade_opinion_factor)

## stability_factor

Number with 2 decimal places.
"""

_IDEA = """ideas = {
\tcountry = {
\t\tLBA_spirit = {
\t\t\tpicture = GFX_idea_LBA
\t\t\tallowed = { always = yes }
\t\t\tmodifier = {
\t\t\t\tstability_factor = 0.1
\t\t\t\tcorruption_cost_factor = -0.05
\t\t\t}
\t\t\ttargeted_modifier = {
\t\t\t\ttag = USA
\t\t\t\topinion_gain_monthly_factor = 0.5
\t\t\t}
\t\t}
\t}
}
"""


def _game_root(tmp_path):
    d = tmp_path / "game"
    doc = d / "documentation"
    doc.mkdir(parents=True)
    (doc / "modifiers_documentation.md").write_text(_DOC, encoding="utf-8")
    return d


def _md_root(tmp_path):
    d = tmp_path / "md"
    ideas = d / "common" / "ideas"
    ideas.mkdir(parents=True)
    (ideas / "lba.txt").write_text(_IDEA, encoding="utf-8")
    return d


def test_base_doc_names_parsed(tmp_path):
    names = build_base_modifier_names([str(_game_root(tmp_path))])
    assert names == {"stability_factor", "war_support_factor", "trade_opinion_factor"}
    assert "country" not in names and "politics" not in names  # scope links excluded


def test_md_idea_keys_harvested_and_filtered(tmp_path):
    keys = build_md_idea_modifier_keys([str(_md_root(tmp_path))])
    assert keys == {"stability_factor", "corruption_cost_factor", "opinion_gain_monthly_factor"}
    # everything outside modifier blocks (and the targeted tag) is excluded
    for junk in ("picture", "allowed", "always", "tag"):
        assert junk not in keys


def test_union_and_dedup(tmp_path):
    roots = [str(_game_root(tmp_path)), str(_md_root(tmp_path))]
    names = build_modifier_names(roots)
    # union of both sources; stability_factor is in BOTH -> appears once
    assert "war_support_factor" in names          # doc-only
    assert "corruption_cost_factor" in names       # MD-only
    assert "stability_factor" in names
    assert len([n for n in names if n == "stability_factor"]) == 1


def test_classification_rules():
    cases = {
        "oil_export_multiplier_modifier": "Trade",
        "foreign_influence_modifier": "Diplomacy",
        "political_power_factor": "Politics & Power",
        "corruption_cost_factor": "Economy & Industry",
        "surrender_limit": "Stability & Unrest",
        "production_speed_buildings_factor": "Construction",
        "conscription_factor": "Manpower",
        "army_org_factor": "Army",
        "air_superiority": "Air",
        "convoy_raiding_efficiency_factor": "Naval",
        "decryption_factor": "Intelligence",
        "research_speed_factor": "Research",
        "some_unknown_xyz": "Other",
    }
    for name, group in cases.items():
        assert classify_modifier(name) == group, name


def test_group_order_and_sorting(tmp_path):
    roots = [str(_game_root(tmp_path)), str(_md_root(tmp_path))]
    groups = build_modifier_groups(roots)
    labels = [g[0] for g in groups]
    # "Common" (most-used quick-pick) leads; theme groups follow in GROUP_ORDER.
    assert labels[0] == "Common"
    theme_labels = labels[1:]
    assert theme_labels == [g for g in GROUP_ORDER if g in theme_labels]
    assert all(label in GROUP_ORDER for label in theme_labels)
    # Theme groups are alpha-sorted (the Common group is usage-ordered, not).
    for _label, names in groups[1:]:
        assert names == sorted(names, key=str.lower)
    assert "Trade" in theme_labels and "Diplomacy" in theme_labels


def test_common_group_is_most_used_in_order(tmp_path):
    # stability_factor appears twice across two ideas, corruption_cost_factor once.
    md = _md_root(tmp_path)
    (md / "common" / "ideas" / "more.txt").write_text(
        "ideas = {\n country = {\n  X = {\n   modifier = { stability_factor = 0.2 }\n"
        "  }\n }\n}\n", encoding="utf-8")
    common = build_common_modifiers([str(md)], limit=5)
    assert common[0] == "stability_factor"          # used twice -> first
    assert "corruption_cost_factor" in common
    assert "opinion_gain_monthly_factor" in common


def test_common_fallback_without_game_files(tmp_path):
    common = build_common_modifiers([str(tmp_path / "empty")], limit=20)
    assert len(common) == 20
    assert common[0] == "stability_factor"          # from the curated fallback


def test_modifier_tooltips_prefer_desc(tmp_path):
    loc = tmp_path / "g" / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "modifiers_l_english.yml").write_text(
        'l_english:\n'
        ' MODIFIER_STABILITY_FACTOR:0 "Stability"\n'
        ' MODIFIER_RESEARCH_SPEED_FACTOR:0 "Research Speed"\n'
        ' MODIFIER_RESEARCH_SPEED_FACTOR_DESC:1 "Decreases research time."\n'
        ' MODIFIER_TECH_PREFIX:0 "£tech_mod "\n'
        ' MODIFIER_FANCY:0 "§YColoured$VAR$ Name§!"\n',
        encoding="utf-8")
    tips = build_modifier_tooltips([str(tmp_path / "g")])
    assert tips["stability_factor"] == "Stability"
    assert tips["research_speed_factor"] == "Research Speed — Decreases research time."
    assert "tech_prefix" not in tips                # £icon prefix dropped
    assert tips["fancy"] == "Coloured Name"         # loc markup stripped


def test_fallback_when_no_sources(tmp_path):
    groups = build_modifier_groups([str(tmp_path / "empty")])
    flat = {n for _l, names in groups for n in names}
    assert groups  # non-empty
    assert groups[0][0] == "Common"     # Common group present even on fallback
    assert "stability_factor" in flat   # from COMMON_IDEA_MODIFIERS fallback
