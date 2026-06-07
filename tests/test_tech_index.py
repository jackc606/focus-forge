"""Tests for the technology index (folder grouping + replace_path)."""
from __future__ import annotations

from core.mod_paths import effective_roots_for_path, read_replace_paths
from core.tech_index import (
    build_building_types,
    build_tech_categories,
    build_tech_groups,
    build_tech_index,
)

TECHS = """
technologies = {
\tinfantry_weapons = {
\t\tfolder = { name = infantry_folder position = { x = 0 y = 0 } }
\t\tcategories = { CAT_inf }
\t}
\t# commented_tech = { folder = { name = ghost_folder } }
\tmodern_tank = {
\t\tfolder = { name = armour_folder position = { x = 1 y = 0 } }
\t\tpath = { leads_to_tech = infantry_weapons }
\t}
}
"""


def _setup(tmp_path):
    base = tmp_path / "base"
    md = tmp_path / "md"
    (base / "common" / "technologies").mkdir(parents=True)
    (md / "common" / "technologies").mkdir(parents=True)
    # base has a vanilla tech that MD should hide via replace_path
    (base / "common" / "technologies" / "v.txt").write_text(
        "technologies = { vanilla_ww2_tech = { folder = { name = infantry_folder } } }",
        encoding="utf-8")
    (md / "common" / "technologies" / "t.txt").write_text(TECHS, encoding="utf-8")
    (md / "descriptor.mod").write_text(
        'name="MD"\nreplace_path="common/technologies"\n', encoding="utf-8")
    loc = md / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "t_l_english.yml").write_text(
        'l_english:\n infantry_weapons:0 "Small Arms"\n modern_tank:0 "Modern Tank"\n',
        encoding="utf-8")
    return [str(base), str(md)]


def test_replace_path_excludes_vanilla(tmp_path):
    roots = _setup(tmp_path)
    assert "common/technologies" in read_replace_paths(roots[1])
    eff = effective_roots_for_path(roots, "common/technologies")
    assert eff == [roots[1]]                      # base dropped
    idx = build_tech_index(roots)
    assert "vanilla_ww2_tech" not in idx          # vanilla hidden
    assert set(idx) == {"infantry_weapons", "modern_tank"}


def test_comment_skipped_and_folder_parsed(tmp_path):
    roots = _setup(tmp_path)
    idx = build_tech_index(roots)
    assert "commented_tech" not in idx
    assert idx["infantry_weapons"] == "infantry_folder"
    assert idx["modern_tank"] == "armour_folder"


def test_groups_labelled_and_named(tmp_path):
    roots = _setup(tmp_path)
    groups = dict(build_tech_groups(roots))
    assert "Infantry" in groups and "Armour" in groups
    assert ("infantry_weapons", "Small Arms") in groups["Infantry"]
    assert ("modern_tank", "Modern Tank") in groups["Armour"]


def test_tech_categories_includes_nuclear(tmp_path):
    root = tmp_path / "md"
    tt = root / "common" / "technology_tags"
    tt.mkdir(parents=True)
    (tt / "00_technology.txt").write_text(
        "technology_Categories = {\n"
        "\tCAT_industry\n\tCAT_armor  # comment\n"
        "\tCAT_nuclear\n\tCAT_nuclear_reactors\n\tCAT_nuclear_weapons\n}\n"
        "technology_folders = { infantry_folder = {} }\n",
        encoding="utf-8")
    cats = build_tech_categories([str(root)])
    assert "CAT_nuclear" in cats
    assert "CAT_nuclear_reactors" in cats and "CAT_nuclear_weapons" in cats
    assert cats == sorted(cats)  # sorted, deduped


def test_building_types_parsed(tmp_path):
    root = tmp_path / "md"
    bd = root / "common" / "buildings"
    bd.mkdir(parents=True)
    (bd / "00_buildings.txt").write_text(
        "buildings = {\n"
        "\tindustrial_complex = { base_cost = 100 }\n"
        "\t# commented_building = { }\n"
        "\tnuclear_facility = { max_level = 10 }\n"
        "\tair_facility = { max_level = 10 }\n"
        "}\n", encoding="utf-8")
    blds = build_building_types([str(root)])
    assert "industrial_complex" in blds
    assert "nuclear_facility" in blds and "air_facility" in blds  # experimental facilities
    assert "commented_building" not in blds
    assert blds == sorted(blds)


def test_building_list_uses_english_names(tmp_path):
    # The dropdown pairs each id with its in-game name so facilities are findable
    # by name (air_facility -> "Aerodynamics & Avionics Facility").
    from core.tech_index import build_building_list
    root = tmp_path / "md"
    bd = root / "common" / "buildings"
    bd.mkdir(parents=True)
    (bd / "00_buildings.txt").write_text(
        "buildings = {\n\tair_facility = { max_level = 10 }\n"
        "\tunnamed_building = { base_cost = 1 }\n}\n", encoding="utf-8")
    loc = root / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "b_l_english.yml").write_text(
        'l_english:\n air_facility:0 "Aerodynamics & Avionics Facility"\n',
        encoding="utf-8")
    blds = dict(build_building_list([str(root)]))
    assert blds["air_facility"] == "Aerodynamics & Avionics Facility"
    assert blds["unnamed_building"] == "Unnamed Building"   # prettified fallback
