"""Tests for the country-leader trait index + grouping."""
from __future__ import annotations

from core.leader_traits import (build_trait_groups, build_trait_index,
                                build_trait_sources, build_trait_tooltips,
                                classify_trait, format_trait_tooltip)

_GENERIC = """leader_traits = {
\tdictator = {
\t\trandom = no
\t\tpolitical_power_factor = 0.25
\t\tweekly_casualties_war_support = 0.001
\t\tai_desired_divisions_factor = 0.20
\t\tai_will_do = { factor = 1 }
\t}
\twar_hero = { random = no army_morale_factor = 0.05 }
\tcaptain_of_industry = { production_speed_buildings_factor = 0.1 }
\tsome_obscure_trait = { random = no }
}
"""

_COUNTRY = """leader_traits = {
\tLBA_great_leader = { random = no }
\tLBA_reformer = { random = no }
}
"""


def _root(tmp_path, files):
    d = tmp_path / "common" / "country_leader"
    d.mkdir(parents=True)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return str(tmp_path)


def test_build_trait_sources(tmp_path):
    root = _root(tmp_path, {"00_traits.txt": _GENERIC, "LBA_traits.txt": _COUNTRY})
    src = build_trait_sources([root])
    assert set(src) == {"dictator", "war_hero", "captain_of_industry",
                        "some_obscure_trait", "LBA_great_leader", "LBA_reformer"}
    assert src["LBA_great_leader"] == {"LBA_traits.txt"}


def test_classification():
    assert classify_trait("dictator") == "Personality"
    assert classify_trait("war_hero") == "Military"
    assert classify_trait("captain_of_industry") == "Economy"
    assert classify_trait("western_conservatism") == "Ideology & Party"
    assert classify_trait("spymaster") == "Intelligence"
    assert classify_trait("xyz_unknown") == "Other"


def test_country_traits_pinned_first(tmp_path):
    root = _root(tmp_path, {"00_traits.txt": _GENERIC, "LBA_traits.txt": _COUNTRY})
    groups = build_trait_groups([root], "LBA")
    assert groups[0][0] == "LBA — this country"
    assert set(groups[0][1]) == {"LBA_great_leader", "LBA_reformer"}
    # LBA traits are NOT duplicated into the theme buckets
    themed = {t for label, ids in groups[1:] for t in ids}
    assert "LBA_great_leader" not in themed
    # generic traits land in their themes
    by_group = dict(groups)
    assert "dictator" in by_group["Personality"]
    assert "war_hero" in by_group["Military"]
    assert "some_obscure_trait" in by_group["Other"]


def test_trait_effects_and_tooltip(tmp_path):
    root = _root(tmp_path, {"00_traits.txt": _GENERIC})
    idx = build_trait_index([root])
    eff = dict(idx["dictator"]["effects"])
    # real bonuses kept; random / ai_* / nested ai_will_do skipped
    assert eff == {"political_power_factor": "0.25",
                   "weekly_casualties_war_support": "0.001"}
    tip = format_trait_tooltip("dictator", idx["dictator"]["effects"])
    assert tip.startswith("dictator")
    assert "political_power_factor = +0.25" in tip
    assert "ai_will_do" not in tip and "random" not in tip
    # a trait with no modifiers shows the placeholder
    assert "no direct modifiers" in format_trait_tooltip("x", [])
    # tooltips map covers every trait
    tips = build_trait_tooltips([root])
    assert set(tips) == set(idx)


def test_no_tag_has_no_country_group(tmp_path):
    root = _root(tmp_path, {"00_traits.txt": _GENERIC, "LBA_traits.txt": _COUNTRY})
    groups = build_trait_groups([root], "")
    assert not any(g[0].endswith("this country") for g in groups)
    # LBA_* still appear, just classified by theme
    allids = {t for _l, ids in groups for t in ids}
    assert "LBA_great_leader" in allids
