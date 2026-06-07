"""Tests for the focus-tree importer."""
from __future__ import annotations

from core.focus_import import FocusTreeRef, find_focus_trees, import_focus_tree

TREE = """
# comment line
focus_tree = {
\tid = test_focus
\tcountry = {
\t\tmodifier = { add = 100 original_tag = TST }
\t}
\tcontinuous_focus_position = { x = 50 y = 900 }

\tfocus = {
\t\tid = TST_root
\t\ticon = GFX_focus_TST_root
\t\tx = 10
\t\ty = 2
\t\tcost = 7
\t\tsearch_filters = { FOCUS_FILTER_POLITICAL FOCUS_FILTER_ARMY }
\t\tcompletion_reward = {
\t\t\tlog = "[GetDateText]: [Root.GetName]: Focus TST_root"
\t\t\tadd_political_power = 120
\t\t}
\t}

\tfocus = {
\t\tid = TST_child
\t\ticon = GFX_focus_TST_child
\t\tx = 0
\t\ty = 1
\t\trelative_position_id = TST_root
\t\tcost = 5
\t\tprerequisite = { focus = TST_root }
\t\tmutually_exclusive = { focus = TST_other }
\t\tavailable = { has_country_flag = some_flag }
\t}
}
"""


def _setup(tmp_path):
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True)
    (nf / "test.txt").write_text(TREE, encoding="utf-8")
    loc = tmp_path / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "test_l_english.yml").write_text(
        'l_english:\n TST_root:0 "The Root"\n TST_root_desc:0 "Root desc"\n'
        ' TST_child:0 "The Child"\n', encoding="utf-8")
    # A Spanish file with the SAME keys — must be ignored (alphabetically before
    # 'english', so it would win under a naive scan).
    es = tmp_path / "localisation" / "spanish"
    es.mkdir(parents=True)
    (es / "test_l_spanish.yml").write_text(
        'l_spanish:\n TST_root:0 "La Raíz"\n TST_root_desc:0 "Descripción"\n'
        ' TST_child:0 "El Hijo"\n', encoding="utf-8")
    return [str(tmp_path)]


def test_localisation_is_english_only(tmp_path):
    roots = _setup(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    by = {f.id: f for f in proj.focuses}
    assert by["TST_root"].title == "The Root"          # not "La Raíz"
    assert by["TST_root"].description == "Root desc"    # not "Descripción"
    assert by["TST_child"].title == "The Child"         # not "El Hijo"


def test_find_focus_trees(tmp_path):
    roots = _setup(tmp_path)
    trees = find_focus_trees(roots, use_cache=False)
    assert len(trees) == 1
    assert trees[0].tag == "TST"
    assert trees[0].tree_id == "test_focus"
    assert trees[0].focus_count == 2


def test_import_structural_fields(tmp_path):
    roots = _setup(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    assert proj.countryTag == "TST"
    assert proj.treeId == "test_focus"
    assert (proj.continuousFocusPosition.x, proj.continuousFocusPosition.y) == (50, 900)
    by = {f.id: f for f in proj.focuses}
    root, child = by["TST_root"], by["TST_child"]
    assert root.title == "The Root" and root.description == "Root desc"
    assert root.cost == 7
    assert root.filters == ["FOCUS_FILTER_POLITICAL", "FOCUS_FILTER_ARMY"]
    assert root.icon == "GFX_focus_TST_root"


def test_relative_position_resolved(tmp_path):
    roots = _setup(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    child = next(f for f in proj.focuses if f.id == "TST_child")
    # root at (10,2); child relative (0,1) -> absolute (10,3)
    assert (child.position.x, child.position.y) == (10, 3)
    assert child.prerequisites == ["TST_root"]
    assert child.mutuallyExclusive == ["TST_other"]
    assert child.available is not None
    assert "has_country_flag = some_flag" in child.available.rawLines


def test_replace_path_excludes_vanilla(tmp_path):
    # A vanilla root with its own tree, and a mod root that declares
    # replace_path="common/national_focus". The importer must see ONLY the mod's
    # tree (vanilla is ignored in-game), not both.
    vanilla = tmp_path / "vanilla"
    vnf = vanilla / "common" / "national_focus"
    vnf.mkdir(parents=True)
    (vnf / "ger.txt").write_text(
        "focus_tree = {\n\tid = vanilla_ger\n\tcountry = { modifier = "
        "{ original_tag = GER } }\n\tfocus = { id = GER_x x = 0 y = 0 }\n}\n",
        encoding="utf-8")

    mod = tmp_path / "mod"
    mnf = mod / "common" / "national_focus"
    mnf.mkdir(parents=True)
    (mnf / "ger.txt").write_text(
        "focus_tree = {\n\tid = md_ger\n\tcountry = { modifier = "
        "{ original_tag = GER } }\n\tfocus = { id = GER_modern x = 0 y = 0 }\n}\n",
        encoding="utf-8")
    (mod / "descriptor.mod").write_text(
        'name="Test Mod"\nreplace_path="common/national_focus"\n', encoding="utf-8")

    roots = [str(vanilla), str(mod)]
    trees = find_focus_trees(roots, use_cache=False)
    tree_ids = {t.tree_id for t in trees}
    assert tree_ids == {"md_ger"}          # vanilla_ger excluded
    assert all(t.tag == "GER" for t in trees)


def test_multi_tag_tree_surfaces_under_every_tag(tmp_path):
    # A shared tree applied to several countries via an OR list must be findable
    # (and importable) under each tag, not just the first.
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True)
    (nf / "gcc.txt").write_text(
        "focus_tree = {\n\tid = gcc_focus\n\tcountry = {\n\t\tfactor = 0\n"
        "\t\tmodifier = { add = 10 OR = { original_tag = SAU original_tag = QAT "
        "original_tag = UAE } }\n\t}\n\tfocus = { id = GCC_root x = 0 y = 0 }\n}\n",
        encoding="utf-8")
    roots = [str(tmp_path)]
    trees = find_focus_trees(roots, use_cache=False)
    assert {t.tag for t in trees} == {"SAU", "QAT", "UAE"}
    assert all(t.tree_id == "gcc_focus" for t in trees)
    # importing the UAE row sets countryTag = UAE
    uae = next(t for t in trees if t.tag == "UAE")
    proj = import_focus_tree(uae, roots)
    assert proj.countryTag == "UAE"
    assert proj.treeId == "gcc_focus"


def test_prefix_ids_namespaces_generic_tree(tmp_path):
    # "Start from generic": importing with prefix_ids renames every focus id to
    # <TAG>_<id>, remaps the prerequisite graph, and uses a tag-based tree id.
    roots = _setup(tmp_path)
    base = find_focus_trees(roots, use_cache=False)[0]
    ref = FocusTreeRef(tag="MEX", tree_id=base.tree_id,
                       focus_count=base.focus_count, file=base.file, prefix_ids=True)
    proj = import_focus_tree(ref, roots)
    assert proj.countryTag == "MEX"
    assert proj.treeId == "mex_focus"            # tag-based, not "test_focus"
    ids = {f.id for f in proj.focuses}
    assert ids == {"MEX_TST_root", "MEX_TST_child"}
    child = next(f for f in proj.focuses if f.id == "MEX_TST_child")
    assert child.prerequisites == ["MEX_TST_root"]   # remapped to the new id


def test_completion_reward_drops_autolog(tmp_path):
    roots = _setup(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    root = next(f for f in proj.focuses if f.id == "TST_root")
    raw = root.completionReward.rawLines
    assert "add_political_power = 120" in raw
    assert not any("GetDateText" in line for line in raw)  # auto-log stripped
