"""Tests for the idea-modifier index (base-doc parse + MD-idea harvest + grouping)."""
from __future__ import annotations

from core.modifier_index import (
    GROUP_ORDER,
    build_base_modifier_names,
    build_md_idea_modifier_keys,
    build_modifier_groups,
    build_modifier_names,
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
    # only non-empty groups, in GROUP_ORDER relative order
    assert labels == [g for g in GROUP_ORDER if g in labels]
    assert all(label in GROUP_ORDER for label in labels)
    for _label, names in groups:
        assert names == sorted(names, key=str.lower)
    # Trade and Diplomacy present (trade_opinion_factor, opinion_gain_monthly_factor)
    assert "Trade" in labels and "Diplomacy" in labels


def test_fallback_when_no_sources(tmp_path):
    groups = build_modifier_groups([str(tmp_path / "empty")])
    flat = {n for _l, names in groups for n in names}
    assert groups  # non-empty
    assert "stability_factor" in flat   # from COMMON_IDEA_MODIFIERS fallback
