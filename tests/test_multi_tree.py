"""Multi-tree national_focus files: several ``focus_tree`` blocks plus top-level
``shared_focus`` blocks in one file, imported / edited / exported as a whole
(core.multi_tree and friends)."""
from __future__ import annotations

import json
import os
import re

import pytest

from core import multi_tree as mt
from core.bridge_dispatch import dispatch
from core.export_check import smoke_check
from core.exporters import (
    export_focus_localisation,
    export_focus_tree,
    export_project_files,
    shortcut_loc_keys,
    shortcut_loc_keys_by_tree,
)
from core.focus_import import (
    FocusTreeRef,
    find_focus_trees,
    import_focus_tree,
)
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.types import FocusNodeData, FocusPosition, FocusShortcut, iter_prereq_ids
from core.validation import validate_project
from ui.project_model import ProjectModel

NEW_FOCUS_KEYS = {"shared", "relativePositionId", "offsets", "appliedOffset", "extraRawLines"}
NEW_PROJECT_KEYS = {"otherTrees", "activeTreeIndex", "sharedPool", "countryRawLines",
                    "sharedFocusRefs", "treeRawLines"}

# Three trees, five shared focuses in two branches:
#   branch A: SH_a_root -> SH_a_child -> SH_a_leaf   (offset +5 x in tree_b)
#   branch B: SH_b_root -> SH_b_child
# tree_a references both branches (+ one defined in another file), tree_b only
# branch A, tree_c only branch B and has no focuses of its own.
FILE = """
shared_focus = {
\tid = SH_a_root
\ticon = GFX_shared_a
\tx = 20
\ty = 0
\toffset = {
\t\tx = 5
\t\ty = 0
\t\ttrigger = { has_focus_tree = tree_b }
\t}
\toffset = {
\t\tx = 100
\t\ty = 100
\t\ttrigger = { has_focus_tree = tree_b has_country_flag = odd }
\t}
\tcost = 5
\tcompletion_reward = { add_political_power = 10 }
}

shared_focus = {
\tid = SH_a_child
\ticon = GFX_shared_a
\tx = 1
\ty = 1
\trelative_position_id = SH_a_root
\tcost = 5
\tprerequisite = { focus = SH_a_root }
\tallow_branch = { has_country_flag = branch_a }
}

shared_focus = {
\tid = SH_a_leaf
\ticon = GFX_shared_a
\tx = -1
\ty = 1
\trelative_position_id = SH_a_child
\tcost = 5
\tprerequisite = { focus = SH_a_child focus = SH_a_root }
}

shared_focus = {
\tid = SH_b_root
\ticon = GFX_shared_b
\tx = 30
\ty = 0
\tcost = 5
}

shared_focus = {
\tid = SH_b_child
\ticon = GFX_shared_b
\tx = 0
\ty = 1
\trelative_position_id = SH_b_root
\tcost = 5
\tprerequisite = { focus = SH_b_root }
}

focus_tree = {
\tid = tree_a
\tcountry = {
\t\tbase = 0
\t\tmodifier = {
\t\t\tadd = 10
\t\t\ttag = TST
\t\t}
\t}
\tshared_focus = SH_a_root
\tshared_focus = SH_b_root
\tshared_focus = EXT_defined_elsewhere
\tdefault = no
\tshortcut = {
\t\tname = TST_politics_shortcut
\t\ttarget = TA_root
\t}

\tfocus = {
\t\tid = TA_root
\t\ticon = GFX_ta
\t\tx = 2
\t\ty = 0
\t\tcost = 10
\t\twill_lead_to_war_with = SOV
\t\tcancel_if_invalid = no
\t\ttext = "TA_custom_text"
\t\tallow_branch = { has_country_flag = branch_ta }
\t\tselect_effect = {
\t\t\tset_country_flag = picked
\t\t\tif = {
\t\t\t\tlimit = { tag = TST }
\t\t\t\tadd_stability = 0.01
\t\t\t}
\t\t}
\t\tbypass = {
\t\t\thas_country_flag = skip_it
\t\t}
\t\tcompletion_reward = { add_political_power = 50 }
\t}

\tfocus = {
\t\tid = TA_child
\t\ticon = GFX_ta
\t\tx = 1
\t\ty = 1
\t\trelative_position_id = TA_root
\t\tcost = 5
\t\tprerequisite = { focus = TA_root }
\t}
}

focus_tree = {
\tid = tree_b
\tcountry = { base = 0 }
\tshared_focus = SH_a_root
\tinitial_show_position = { x = 3 y = 1 }
\treset_on_civilwar = no
\tcontinuous_focus_position = { x = 40 y = 900 }
\tshortcut = {
\t\tname = TST_politics_b_shortcut
\t\ttarget = TB_root
\t}

\tfocus = {
\t\tid = TB_root
\t\ticon = GFX_tb
\t\tx = 4
\t\ty = 0
\t\tcost = 10
\t}

\tfocus = {
\t\tid = TB_child
\t\ticon = GFX_tb
\t\tx = 0
\t\ty = 1
\t\trelative_position_id = TB_root
\t\tcost = 5
\t\tprerequisite = { focus = TB_root }
\t}
}

focus_tree = {
\tid = tree_c
\tcountry = { base = 0 }
\tshared_focus = SH_b_root
}
"""

LOC = ('l_english:\n TA_root:0 "A Root"\n TA_root_desc:0 "A root desc"\n'
       ' TB_root:0 "B Root"\n SH_a_root:0 "Shared A"\n SH_b_child:0 "Shared B Child"\n'
       ' TST_politics_shortcut:0 "Politics"\n TST_politics_b_shortcut:0 "Politics"\n')


def _setup(tmp_path, text=FILE, name="multi.txt"):
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True, exist_ok=True)
    (nf / name).write_text(text, encoding="utf-8")
    loc = tmp_path / "localisation" / "english"
    loc.mkdir(parents=True, exist_ok=True)
    (loc / "multi_l_english.yml").write_text(LOC, encoding="utf-8")
    return [str(tmp_path)]


def _ref(roots, tree_id):
    return next(r for r in find_focus_trees(roots, use_cache=False) if r.tree_id == tree_id)


def _import(tmp_path, tree_id="tree_a"):
    roots = _setup(tmp_path)
    return import_focus_tree(_ref(roots, tree_id), roots)


def _dump(project) -> str:
    return json.dumps(project_to_dict(project), sort_keys=True)


def _pos(project) -> dict:
    return {f.id: (f.position.x, f.position.y) for f in project.focuses}


def _graph(project) -> dict:
    """Per tree (through its view): ids, shared flags, prereqs and positions."""
    out = {}
    for view in mt.tree_views(project):
        out[view.treeId] = sorted(
            (f.id, bool(f.shared), json.dumps(f.prerequisites), f.position.x, f.position.y)
            for f in view.focuses)
    return out


# ----- discovery ---------------------------------------------------------------

def test_discovery_counts_visible_shared_and_inherits_the_tag(tmp_path):
    roots = _setup(tmp_path)
    refs = {r.tree_id: r for r in find_focus_trees(roots, use_cache=False)}
    # tree_c has NO focuses of its own — it is listed because it shows branch B.
    assert set(refs) == {"tree_a", "tree_b", "tree_c"}
    assert refs["tree_a"].focus_count == 2 + 5
    assert refs["tree_b"].focus_count == 2 + 3
    assert refs["tree_c"].focus_count == 0 + 2
    # Only tree_a names a tag; the load_focus_tree-style trees inherit it.
    assert {r.tag for r in refs.values()} == {"TST"}


def test_discovery_does_not_inherit_when_tagged_trees_disagree(tmp_path):
    text = FILE.replace("\tid = tree_b\n\tcountry = { base = 0 }",
                        "\tid = tree_b\n\tcountry = { base = 0 modifier = { add = 10 tag = OTH } }")
    roots = _setup(tmp_path, text)
    tags = {r.tree_id: r.tag for r in find_focus_trees(roots, use_cache=False)}
    assert tags == {"tree_a": "TST", "tree_b": "OTH", "tree_c": "?"}


def test_tagless_file_still_lists_under_question_mark(tmp_path):
    text = "focus_tree = {\n\tid = generic_focus\n\tcountry = { factor = 1 }\n" \
           "\tfocus = { id = g_one x = 0 y = 0 }\n}\n"
    roots = _setup(tmp_path, text, "generic.txt")
    assert [(r.tag, r.tree_id, r.focus_count)
            for r in find_focus_trees(roots, use_cache=False)] == [("?", "generic_focus", 1)]


# ----- whole-file import -------------------------------------------------------

def test_import_holds_the_whole_file(tmp_path):
    p = _import(tmp_path, "tree_b")
    assert mt.tree_count(p) == 3
    assert mt.tree_ids(p) == ["tree_a", "tree_b", "tree_c"]
    assert p.activeTreeIndex == 1 and p.treeId == "tree_b"
    assert [t.treeId for t in p.otherTrees] == ["tree_a", "tree_c"]
    own = [f.id for f in p.focuses if not f.shared]
    shared = [f.id for f in p.focuses if f.shared]
    assert own == ["TB_root", "TB_child"]
    # tree_b references only branch A — branch B waits in the pool.
    assert sorted(shared) == ["SH_a_child", "SH_a_leaf", "SH_a_root"]
    assert sorted(f.id for f in p.sharedPool) == ["SH_b_child", "SH_b_root"]
    assert all(f.shared for f in p.sharedPool)
    assert len(mt.all_focuses(p)) == 4 + 5
    assert len({id(f) for f in mt.all_focuses(p)}) == 9          # each exactly once
    assert p.source == {"file": "multi.txt", "treeId": "tree_b", "tag": "TST",
                        "mode": "replace", "trees": 3}
    assert p.exportSettings.focusFileName == "multi"
    assert mt.tree_summaries(p) == [
        {"index": 0, "treeId": "tree_a", "active": False, "ownFocuses": 2, "sharedFocuses": 5},
        {"index": 1, "treeId": "tree_b", "active": True, "ownFocuses": 2, "sharedFocuses": 3},
        {"index": 2, "treeId": "tree_c", "active": False, "ownFocuses": 0, "sharedFocuses": 2},
    ]


def test_import_keeps_tree_level_statements(tmp_path):
    p = _import(tmp_path, "tree_a")
    assert p.countryRawLines == ["base = 0", "modifier = {", "add = 10", "tag = TST", "}"]
    assert p.sharedFocusRefs == ["SH_a_root", "SH_b_root", "EXT_defined_elsewhere"]
    assert p.treeRawLines == ["default = no"]
    b = p.otherTrees[0]
    assert b.treeId == "tree_b" and b.countryRawLines == ["base = 0"]
    assert b.extraRawLines == ["initial_show_position = { x = 3 y = 1 }", "reset_on_civilwar = no"]
    assert (b.continuousFocusPosition.x, b.continuousFocusPosition.y) == (40, 900)
    # Localisation is loaded for every tree and for the shared focuses.
    assert b.focuses[0].title == "B Root"
    by = {f.id: f for f in mt.all_focuses(p)}
    assert by["SH_a_root"].title == "Shared A" and by["SH_b_child"].title == "Shared B Child"
    assert p.shortcuts[0].label == "Politics" and b.shortcuts[0].label == "Politics"


def test_shared_positions_resolve_through_relative_ids(tmp_path):
    p = _import(tmp_path, "tree_a")
    by = {f.id: f for f in p.focuses}
    assert _pos(p)["SH_a_root"] == (20, 0)
    assert _pos(p)["SH_a_child"] == (21, 1)
    assert _pos(p)["SH_a_leaf"] == (20, 2)
    assert _pos(p)["SH_b_child"] == (30, 1)
    assert _pos(p)["TA_child"] == (3, 1)
    # The anchor is remembered for shared focuses only.
    assert by["SH_a_child"].relativePositionId == "SH_a_root"
    assert by["SH_a_root"].relativePositionId is None
    assert by["TA_child"].relativePositionId is None
    assert all(f.appliedOffset is None for f in p.focuses)       # no offset targets tree_a


def test_extra_statements_and_bypass_are_imported(tmp_path):
    p = _import(tmp_path, "tree_a")
    root = next(f for f in p.focuses if f.id == "TA_root")
    assert root.bypass.rawLines == ["has_country_flag = skip_it"]
    assert root.extraRawLines == [
        "will_lead_to_war_with = SOV",
        "cancel_if_invalid = no",
        'text = "TA_custom_text"',                      # quoting survives
        "allow_branch = { has_country_flag = branch_ta }",
        "select_effect = {", "set_country_flag = picked", "if = {", "limit = { tag = TST }",
        "add_stability = 0.01", "}", "}",
    ]
    assert next(f for f in p.focuses if f.id == "TA_child").extraRawLines is None
    assert next(f for f in p.focuses if f.id == "SH_a_root").offsets == [
        ["x = 5", "y = 0", "trigger = { has_focus_tree = tree_b }"],
        ["x = 100", "y = 100", "trigger = { has_focus_tree = tree_b has_country_flag = odd }"],
    ]


# ----- offsets and switching ---------------------------------------------------

def test_offsets_apply_only_in_the_matching_tree(tmp_path):
    a = _import(tmp_path / "a", "tree_a")
    b = _import(tmp_path / "b", "tree_b")
    # Whole relative chain moves with its offset anchor; the compound-trigger
    # offset (+100) is not evaluated by the editor.
    for fid in ("SH_a_root", "SH_a_child", "SH_a_leaf"):
        ax, ay = _pos(a)[fid]
        assert _pos(b)[fid] == (ax + 5, ay)
        f = next(x for x in b.focuses if x.id == fid)
        assert (f.appliedOffset.x, f.appliedOffset.y) == (5, 0)
        assert mt.base_position(f) == (ax, ay)


def test_switch_there_and_back_is_identical(tmp_path):
    p = _import(tmp_path, "tree_a")
    before = _dump(p)
    base = _pos(p)
    assert mt.switch_tree(p, 1) is True
    assert p.treeId == "tree_b" and p.activeTreeIndex == 1
    assert [t.treeId for t in p.otherTrees] == ["tree_a", "tree_c"]
    assert [f.id for f in p.focuses if not f.shared] == ["TB_root", "TB_child"]
    assert _pos(p)["SH_a_root"] == (base["SH_a_root"][0] + 5, 0)
    assert sorted(f.id for f in p.sharedPool) == ["SH_b_child", "SH_b_root"]
    assert p.countryRawLines == ["base = 0"]
    assert p.treeRawLines == ["initial_show_position = { x = 3 y = 1 }", "reset_on_civilwar = no"]
    assert mt.switch_tree(p, 2) is True                      # a tree with no own focuses
    assert [f.id for f in p.focuses] == ["SH_b_root", "SH_b_child"]
    assert all(f.appliedOffset is None for f in mt.all_focuses(p))
    assert mt.switch_tree(p, 0) is True
    assert _dump(p) == before


def test_switch_rejects_bad_indexes(tmp_path):
    p = _import(tmp_path, "tree_a")
    before = _dump(p)
    assert mt.switch_tree(p, 0) is False        # already active
    assert mt.switch_tree(p, 3) is False
    assert mt.switch_tree(p, -1) is False
    assert mt.switch_tree(p, "x") is False
    assert _dump(p) == before
    sample = make_sample_project()
    assert mt.switch_tree(sample, 0) is False and mt.switch_tree(sample, 1) is False


def test_tree_views(tmp_path):
    p = _import(tmp_path, "tree_a")
    views = mt.tree_views(p)
    assert [v.treeId for v in views] == ["tree_a", "tree_b", "tree_c"]
    assert views[0].focuses is p.focuses and views[0].shortcuts is p.shortcuts
    assert all(v.otherTrees == [] and v.sharedPool == [] for v in views)
    b = views[1]
    assert [f.id for f in b.focuses] == ["TB_root", "TB_child", "SH_a_root", "SH_a_child", "SH_a_leaf"]
    live = {f.id: f for f in mt.all_shared(p)}
    moved = next(f for f in b.focuses if f.id == "SH_a_root")
    assert moved is not live["SH_a_root"]                      # a copy: its position differs
    assert (moved.position.x, live["SH_a_root"].position.x) == (25, 20)
    c = views[2]
    assert all(f is live[f.id] for f in c.focuses)              # unmoved: the live objects
    # A view describes exactly what switching to that tree would show.
    q = project_from_dict(project_to_dict(p))
    mt.switch_tree(q, 1)
    assert _pos(b) == _pos(q)
    # An ordinary project is its own single view.
    sample = make_sample_project()
    assert mt.tree_views(sample) == [sample] and mt.tree_views(sample)[0] is sample
    assert mt.all_focuses(sample) is sample.focuses
    assert mt.tree_summaries(sample) == [{"index": 0, "treeId": sample.treeId, "active": True,
                                          "ownFocuses": 3, "sharedFocuses": 0}]


# ----- serialization -----------------------------------------------------------

def test_serialization_round_trip(tmp_path):
    p = _import(tmp_path, "tree_b")
    d = project_to_dict(p)
    assert d["activeTreeIndex"] == 1 and len(d["otherTrees"]) == 2 and len(d["sharedPool"]) == 2
    q = project_from_dict(json.loads(json.dumps(d)))
    assert _dump(q) == _dump(p)
    assert export_focus_tree(q) == export_focus_tree(p)
    moved = next(f for f in q.focuses if f.id == "SH_a_root")
    assert (moved.appliedOffset.x, moved.appliedOffset.y) == (5, 0)
    assert moved.shared is True and moved.offsets[0][2] == "trigger = { has_focus_tree = tree_b }"
    # Only what is set is written.
    own = next(f for f in d["focuses"] if f["id"] == "TB_root")
    assert not (NEW_FOCUS_KEYS & set(own))


def test_old_single_tree_project_is_untouched():
    p = make_sample_project()
    p.shortcuts = [FocusShortcut(label="Economy", target=p.focuses[0].id)]
    d = project_to_dict(p)
    assert not (NEW_PROJECT_KEYS & set(d))
    for f in d["focuses"]:
        assert not (NEW_FOCUS_KEYS & set(f))
    q = project_from_dict(d)
    assert q.otherTrees == [] and q.sharedPool == [] and q.activeTreeIndex == 0
    assert project_to_dict(q) == d
    # Byte-identical to the single-tree layout the exporter has always written.
    tree = export_focus_tree(p)
    assert tree == export_focus_tree(q)
    assert tree.startswith(
        "focus_tree = {\n\tid = mexico_focus\n\n\tcountry = {\n\t\tfactor = 0\n"
        "\t\tmodifier = {\n\t\t\tadd = 100\n\t\t\ttag = MEX\n\t\t}\n\t}\n\n"
        "\tcontinuous_focus_position = { x = ")
    assert "\tinitial_show_position = { x = 0 y = 0 }\n\n\tshortcut = {\n" in tree
    assert tree.count("focus_tree = {") == 1 and "shared_focus" not in tree
    assert tree.endswith("\t}\n\n}\n")
    assert shortcut_loc_keys(p) == shortcut_loc_keys_by_tree(p)[0] == ["MEX_forge_economy_shortcut"]


# ----- export ------------------------------------------------------------------

def test_export_writes_every_tree_and_shared_focus(tmp_path):
    p = _import(tmp_path, "tree_a")
    out = export_focus_tree(p)
    assert len(re.findall(r"^focus_tree = \{", out, re.M)) == 3
    assert len(re.findall(r"^shared_focus = \{", out, re.M)) == 5
    assert [m for m in re.findall(r"^\tid = (\S+)", out, re.M) if m.startswith("tree_")] == \
        ["tree_a", "tree_b", "tree_c"]
    # Each tree block holds ONLY its own focuses.
    a_block = out[:out.index("focus_tree = {", 5)]
    assert "id = TA_root" in a_block and "id = TB_root" not in a_block and "SH_a_child" not in a_block
    # country blocks verbatim, references in order (the external one included).
    assert ("\tcountry = {\n\t\tbase = 0\n\t\tmodifier = {\n\t\t\tadd = 10\n\t\t\ttag = TST\n"
            "\t\t}\n\t}\n\tshared_focus = SH_a_root\n\tshared_focus = SH_b_root\n"
            "\tshared_focus = EXT_defined_elsewhere\n") in a_block
    assert "\tdefault = no\n" in a_block
    b_block = out[out.index("\tid = tree_b"):out.index("\tid = tree_c")]
    assert "\tcountry = {\n\t\tbase = 0\n\t}\n\tshared_focus = SH_a_root\n" in b_block
    assert "continuous_focus_position = { x = 40 y = 900 }" in b_block
    # The imported initial_show_position replaces the generated one.
    assert b_block.count("initial_show_position") == 1
    assert "\tinitial_show_position = { x = 3 y = 1 }\n\treset_on_civilwar = no\n" in b_block
    assert a_block.count("initial_show_position = { x = 0 y = 0 }") == 1
    assert not [i for i in smoke_check(export_project_files(p)) if i.severity == "error"]


def test_export_shared_focus_is_relative_with_offsets(tmp_path):
    for active in ("tree_a", "tree_b"):          # the active tree must not change the file
        p = _import(tmp_path / active, active)
        out = export_focus_tree(p)
        root = out[out.index("shared_focus = {\n\tid = SH_a_root"):]
        root = root[:root.index("\n}\n") + 3]
        assert root.startswith(
            "shared_focus = {\n\tid = SH_a_root\n\ticon = GFX_shared_a\n\tx = 20\n\ty = 0\n"
            "\toffset = {\n\t\tx = 5\n\t\ty = 0\n\t\ttrigger = { has_focus_tree = tree_b }\n\t}\n"
            "\toffset = {\n\t\tx = 100\n\t\ty = 100\n"
            "\t\ttrigger = { has_focus_tree = tree_b has_country_flag = odd }\n\t}\n\tcost = ")
        assert "relative_position_id" not in root
        leaf = out[out.index("shared_focus = {\n\tid = SH_a_leaf"):]
        assert leaf.startswith("shared_focus = {\n\tid = SH_a_leaf\n\ticon = GFX_shared_a\n"
                               "\tx = -1\n\ty = 1\n\trelative_position_id = SH_a_child\n\tcost = ")
        child = out[out.index("shared_focus = {\n\tid = SH_a_child"):]
        assert child.startswith("shared_focus = {\n\tid = SH_a_child\n\ticon = GFX_shared_a\n"
                                "\tx = 1\n\ty = 1\n\trelative_position_id = SH_a_root\n")
    a = export_focus_tree(_import(tmp_path / "x", "tree_a"))
    b = export_focus_tree(_import(tmp_path / "y", "tree_b"))
    assert a == b


def test_export_moved_shared_focus_stays_relative(tmp_path):
    p = _import(tmp_path, "tree_b")              # offsets are baked in (+5 x)
    child = next(f for f in p.focuses if f.id == "SH_a_child")
    child.position = FocusPosition(x=child.position.x + 2, y=child.position.y + 1)
    out = export_focus_tree(p)
    block = out[out.index("shared_focus = {\n\tid = SH_a_child"):]
    assert "\tx = 3\n\ty = 2\n\trelative_position_id = SH_a_root\n" in block[:200]
    # An anchor that no longer exists falls back to absolute base coordinates.
    child.relativePositionId = "gone"
    out = export_focus_tree(p)
    block = out[out.index("shared_focus = {\n\tid = SH_a_child"):][:200]
    assert "\tx = 23\n\ty = 2\n\tcost" in block and "relative_position_id" not in block


def test_export_extra_statements_and_bypass(tmp_path):
    out = export_focus_tree(_import(tmp_path, "tree_a"))
    block = out[out.index("\tfocus = {\n\t\tid = TA_root"):]
    block = block[:block.index("\t\tai_will_do")]
    assert ("\t\tbypass = {\n\t\t\thas_country_flag = skip_it\n\t\t}\n"
            "\t\twill_lead_to_war_with = SOV\n"
            "\t\tcancel_if_invalid = no\n"
            '\t\ttext = "TA_custom_text"\n'
            "\t\tallow_branch = { has_country_flag = branch_ta }\n"
            "\t\tselect_effect = {\n"
            "\t\t\tset_country_flag = picked\n"
            "\t\t\tif = {\n"
            "\t\t\t\tlimit = { tag = TST }\n"
            "\t\t\t\tadd_stability = 0.01\n"
            "\t\t\t}\n"
            "\t\t}\n"
            "\n\t\tcompletion_reward = {\n") in block
    shared = out[out.index("shared_focus = {\n\tid = SH_a_child"):]
    assert "\tallow_branch = { has_country_flag = branch_a }\n\n\tcompletion_reward = {\n" in shared[:400]


def test_export_localisation_covers_all_trees(tmp_path):
    p = _import(tmp_path, "tree_b")
    loc = export_focus_localisation(p)
    for fid in ("TA_root", "TA_child", "TB_root", "TB_child", "SH_a_root", "SH_a_leaf",
                "SH_b_root", "SH_b_child"):
        assert loc.count(f"\n {fid}:0 ") == 1 and loc.count(f"\n {fid}_desc:0 ") == 1
    # Both trees have a "Politics" shortcut — the keys must not collide.
    keys = shortcut_loc_keys_by_tree(p)
    assert keys == [["TST_politics_shortcut"], ["TST_politics_shortcut_2"], []]
    assert shortcut_loc_keys(p) == ["TST_politics_shortcut_2"]        # active = tree_b
    assert loc.count(' TST_politics_shortcut:0 "Politics"') == 1
    assert loc.count(' TST_politics_shortcut_2:0 "Politics"') == 1
    out = export_focus_tree(p)
    assert "\t\tname = TST_politics_shortcut\n\t\ttarget = TA_root" in out
    assert "\t\tname = TST_politics_shortcut_2\n\t\ttarget = TB_root" in out


def test_export_reimport_round_trip(tmp_path):
    p = _import(tmp_path / "src", "tree_a")
    out = export_focus_tree(p)
    roots = _setup(tmp_path / "again", out)
    # The exported localisation travels with the tree (shortcut labels live there).
    (tmp_path / "again" / "localisation" / "english" / "multi_l_english.yml").write_text(
        export_focus_localisation(p), encoding="utf-8")
    q = import_focus_tree(_ref(roots, "tree_a"), roots)
    assert mt.tree_ids(q) == mt.tree_ids(p)
    assert mt.tree_summaries(q) == mt.tree_summaries(p)
    assert _graph(q) == _graph(p)                          # ids, prereqs, absolute positions
    assert q.sharedFocusRefs == p.sharedFocusRefs
    assert [t.countryRawLines for t in q.otherTrees] == [t.countryRawLines for t in p.otherTrees]
    by_p = {f.id: f for f in mt.all_focuses(p)}
    for f in mt.all_focuses(q):
        assert f.extraRawLines == by_p[f.id].extraRawLines
        assert f.offsets == by_p[f.id].offsets
        assert f.relativePositionId == by_p[f.id].relativePositionId
        assert (f.bypass.rawLines if f.bypass else None) == \
            (by_p[f.id].bypass.rawLines if by_p[f.id].bypass else None)
    assert export_focus_tree(q) == out                     # and the export is a fixed point


# ----- copy mode ---------------------------------------------------------------

def test_copy_mode_imports_one_tree_with_prefixed_shared(tmp_path):
    roots = _setup(tmp_path)
    ref = _ref(roots, "tree_b")
    ref = FocusTreeRef(tag=ref.tag, tree_id=ref.tree_id, focus_count=ref.focus_count,
                       file=ref.file, id_prefix="NEW")
    p = import_focus_tree(ref, roots)
    assert p.otherTrees == [] and p.sharedPool == [] and p.activeTreeIndex == 0
    assert mt.tree_count(p) == 1 and p.treeId == "new_focus"
    assert p.source["mode"] == "copy" and "trees" not in p.source
    assert [(f.id, f.shared) for f in p.focuses] == [
        ("NEW_TB_root", False), ("NEW_TB_child", False),
        ("NEW_SH_a_root", True), ("NEW_SH_a_child", True), ("NEW_SH_a_leaf", True)]
    by = {f.id: f for f in p.focuses}
    assert by["NEW_SH_a_child"].prerequisites == ["NEW_SH_a_root"]
    assert by["NEW_SH_a_leaf"].prerequisites == [["NEW_SH_a_child", "NEW_SH_a_root"]]
    assert by["NEW_SH_a_child"].relativePositionId == "NEW_SH_a_root"
    assert p.sharedFocusRefs == ["NEW_SH_a_root"]
    assert p.countryRawLines == []                               # generated, tag-based
    assert p.shortcuts[0].target == "NEW_TB_root"
    # The per-tree offset follows the tree to its new id and stays applied.
    assert by["NEW_SH_a_root"].offsets[0][2] == "trigger = { has_focus_tree = new_focus }"
    assert (by["NEW_SH_a_root"].position.x, by["NEW_SH_a_root"].appliedOffset.x) == (25, 5)
    out = export_focus_tree(p)
    assert out.count("focus_tree = {") == 1
    assert len(re.findall(r"^shared_focus = \{", out, re.M)) == 3
    assert "\t\t\ttag = TST\n" in out and "\tshared_focus = NEW_SH_a_root\n" in out
    assert not [i for i in validate_project(p) if i.severity == "error"]


def test_copy_mode_keeps_external_refs_and_drops_default(tmp_path):
    roots = _setup(tmp_path, FILE.replace("\tdefault = no\n", "\tdefault = yes\n\treset_on_civilwar = no\n"))
    ref = _ref(roots, "tree_a")
    ref = FocusTreeRef(tag=ref.tag, tree_id=ref.tree_id, focus_count=ref.focus_count,
                       file=ref.file, id_prefix="NEW")
    p = import_focus_tree(ref, roots)
    assert p.sharedFocusRefs == ["NEW_SH_a_root", "NEW_SH_b_root", "EXT_defined_elsewhere"]
    assert p.treeRawLines == ["reset_on_civilwar = no"]
    assert len([f for f in p.focuses if f.shared]) == 5


# ----- validation --------------------------------------------------------------

def _codes(issues, severity=None):
    return sorted(i.code for i in issues if severity is None or i.severity == severity)


def test_validation_external_ref_and_no_errors(tmp_path):
    p = _import(tmp_path, "tree_a")
    issues = validate_project(p)
    assert _codes(issues, "error") == []
    ext = [i for i in issues if i.code == "tree.sharedRef.external"]
    assert len(ext) == 1 and "EXT_defined_elsewhere" in ext[0].message and "tree_a" in ext[0].message
    assert ext[0].severity == "warning"
    assert "focus.shared.unreferenced" not in _codes(issues)
    # The external reference is still written out verbatim.
    assert "\tshared_focus = EXT_defined_elsewhere\n" in export_focus_tree(p)


def test_validation_prefixes_other_trees_and_reports_shared_once(tmp_path):
    p = _import(tmp_path, "tree_a")
    issues = validate_project(p)
    # TB_child has no description → flagged in its own (non-active) tree.
    hit = [i for i in issues if i.focusId == "TB_child" and i.code == "focus.description.empty"]
    assert len(hit) == 1 and hit[0].message.startswith("[tree_b] TB_child ")
    own = [i for i in issues if i.focusId == "TA_child" and i.code == "focus.description.empty"]
    assert len(own) == 1 and own[0].message.startswith("TA_child ")
    # A shared focus shown by several trees is reported once, by the active tree.
    shared = [i for i in issues if i.focusId == "SH_a_leaf" and i.code == "focus.description.empty"]
    assert len(shared) == 1 and not shared[0].message.startswith("[")
    # Project-level checks run once.
    assert _codes(issues).count("project.tag.empty") == 0
    p.countryTag = ""
    assert _codes(validate_project(p)).count("project.tag.empty") == 1
    # A broken parked tree is caught without switching to it.
    p.otherTrees[0].focuses[1].prerequisites = ["nope"]
    p.otherTrees[0].shortcuts[0].target = "nope"
    p.otherTrees[1].treeId = ""
    issues = validate_project(p)
    miss = [i for i in issues if i.code == "focus.prerequisite.missing"]
    assert len(miss) == 1 and miss[0].focusId == "TB_child" and miss[0].message.startswith("[tree_b] ")
    sc = [i for i in issues if i.code == "shortcut.target.missing"]
    assert len(sc) == 1 and sc[0].message.startswith("[tree_b] ")
    assert [i.message for i in issues if i.code == "project.treeId.empty"] == \
        ["[] Focus tree has no id (treeId)."]


def test_validation_duplicate_id_across_trees(tmp_path):
    p = _import(tmp_path, "tree_a")
    p.otherTrees[0].focuses[0].id = "TA_root"            # tree_b now redefines tree_a's root
    dups = [i for i in validate_project(p) if i.code == "focus.id.duplicateAcrossTrees"]
    assert len(dups) == 1 and dups[0].severity == "error" and dups[0].focusId == "TA_root"
    assert "tree tree_a" in dups[0].message and "tree tree_b" in dups[0].message
    # ...and a tree focus colliding with a shared focus.
    q = _import(tmp_path / "q", "tree_a")
    q.focuses[0].id = "SH_b_root"
    dups = [i for i in validate_project(q) if i.code == "focus.id.duplicateAcrossTrees"]
    assert [d.focusId for d in dups] == ["SH_b_root"] and "the shared focuses" in dups[0].message


def test_validation_unreferenced_shared(tmp_path):
    p = _import(tmp_path, "tree_a")
    p.sharedFocusRefs = ["SH_a_root"]
    p.otherTrees[1].sharedFocusRefs = []                 # nobody references branch B now
    hits = sorted(i.focusId for i in validate_project(p) if i.code == "focus.shared.unreferenced")
    assert hits == ["SH_b_child", "SH_b_root"]


def test_validation_of_ordinary_project_has_no_tree_issues():
    issues = validate_project(make_sample_project())
    assert not [i for i in issues if i.code.startswith(("tree.", "focus.shared.", "focus.id.duplicateAcross"))]
    assert not [i for i in issues if i.message.startswith("[")]


# ----- model -------------------------------------------------------------------

def _model(tmp_path, tree_id="tree_a"):
    m = ProjectModel()                    # headless: no QApplication needed
    m.replace_project(_import(tmp_path, tree_id))
    return m


def test_model_switch_tree_undo_redo(tmp_path):
    m = _model(tmp_path)
    before = _dump(m.project)
    m.set_selection("TA_root")
    assert m.is_dirty() is False and m.can_undo() is False
    changes = []
    m.project_changed.connect(lambda: changes.append(1))
    assert m.switch_tree(1) is True
    assert m.project.treeId == "tree_b" and m.selected_id == "" and m.is_dirty() is True
    assert changes == [1]
    assert m.find_focus("TB_root") is not None and m.find_focus("TA_root") is None
    after = _dump(m.project)
    assert m.undo() is True
    assert m.project.treeId == "tree_a" and _dump(m.project) == before
    assert m.can_undo() is False                          # exactly one step
    assert m.redo() is True
    assert m.project.treeId == "tree_b" and _dump(m.project) == after
    assert m.switch_tree(1) is False and m.switch_tree(9) is False


def test_model_ids_are_unique_across_trees(tmp_path):
    m = _model(tmp_path)
    assert m.rename_focus("TA_child", "TB_root") == "TB_root_2"     # tree_b owns TB_root
    assert m.rename_focus("TB_root_2", "SH_b_root") == "SH_b_root_2"
    new_id = m.add_focus_at(40, 40)
    assert new_id not in {"TB_root", "TB_child"}
    assert len({f.id for f in mt.all_focuses(m.project)}) == len(mt.all_focuses(m.project))


def test_model_rename_and_delete_shared_root_updates_every_tree(tmp_path):
    m = _model(tmp_path)
    assert m.rename_focus("SH_a_root", "SH_alpha") == "SH_alpha"
    p = m.project
    assert p.sharedFocusRefs == ["SH_alpha", "SH_b_root", "EXT_defined_elsewhere"]
    assert p.otherTrees[0].sharedFocusRefs == ["SH_alpha"]
    by = {f.id: f for f in p.focuses}
    assert by["SH_a_child"].prerequisites == ["SH_alpha"]
    assert by["SH_a_child"].relativePositionId == "SH_alpha"
    assert mt.tree_summaries(p)[1]["sharedFocuses"] == 3            # tree_b still sees the branch
    m.delete_focuses(["SH_b_root"])
    p = m.project
    assert p.sharedFocusRefs == ["SH_alpha", "EXT_defined_elsewhere"]
    assert p.otherTrees[1].sharedFocusRefs == []
    by = {f.id: f for f in p.focuses}
    assert by["SH_b_child"].prerequisites == [] and by["SH_b_child"].relativePositionId is None


# ----- bridge ------------------------------------------------------------------

def _ok(model, op, **args):
    res = dispatch(model, op, args)
    assert res["ok"], res
    return res["result"]


def test_bridge_list_and_switch_trees(tmp_path):
    m = _model(tmp_path)
    trees = _ok(m, "list_trees")
    assert [(t["index"], t["treeId"], t["active"]) for t in trees] == [
        (0, "tree_a", True), (1, "tree_b", False), (2, "tree_c", False)]
    assert _ok(m, "hello")["project"]["trees"] == trees
    assert _ok(m, "get_project")["trees"] == trees
    rows = {f["id"]: f for f in _ok(m, "list_focuses")}
    assert rows["SH_a_root"]["shared"] is True and "shared" not in rows["TA_root"]
    r = _ok(m, "switch_tree", treeId="tree_b")
    assert r["switched"] is True and r["index"] == 1 and r["treeId"] == "tree_b" and r["focuses"] == 5
    assert m.project.treeId == "tree_b"
    assert {f["id"] for f in _ok(m, "list_focuses")} == {
        "TB_root", "TB_child", "SH_a_root", "SH_a_child", "SH_a_leaf"}
    r = _ok(m, "switch_tree", tree_id="tree_b")                  # alias; already active
    assert r["switched"] is False
    assert _ok(m, "switch_tree", index=2)["treeId"] == "tree_c"
    assert m.undo() and m.project.treeId == "tree_b"
    bad = dispatch(m, "switch_tree", {"treeId": "nope"})
    assert not bad["ok"] and "tree_a" in bad["error"]
    assert not dispatch(m, "switch_tree", {"index": 7})["ok"]
    assert not dispatch(m, "switch_tree", {})["ok"]


def test_bridge_single_tree_project_reports_no_trees():
    m = ProjectModel()
    assert "trees" not in _ok(m, "hello")["project"]
    assert "trees" not in _ok(m, "get_project")
    assert all("shared" not in f for f in _ok(m, "list_focuses"))
    assert len(_ok(m, "list_trees")) == 1
    assert "switch_tree" in _ok(m, "hello")["ops"] and "list_trees" in _ok(m, "hello")["ops"]
    assert "shared" in _ok(m, "guide")["text"].lower()


# ----- the real thing ----------------------------------------------------------

MD_ROOT = r"C:\Program Files (x86)\Steam\steamapps\workshop\content\394360\2777392649"
MD_AUSTRALIA = os.path.join(MD_ROOT, "common", "national_focus", "05_Australia.txt")


@pytest.mark.skipif(not os.path.isfile(MD_AUSTRALIA), reason="Millennium Dawn is not installed")
def test_real_md_australia_file(tmp_path):
    from core.focus_import import _trees_in_file
    refs = _trees_in_file(MD_AUSTRALIA)
    assert len(refs) == 8 and {r.tag for r in refs} == {"AST"}
    expected_own = {"howardgov_focus": 88, "australia_abbottgov_focus": 88,
                    "costellogov_focus": 60, "ruddgov_focus": 64, "gillardgov_focus": 53,
                    "ruddgov_return_focus": 7, "turnbullgov_focus": 1, "miscle_tree_focus": 0}
    assert {r.tree_id: r.focus_count for r in refs} == {k: v + 89 for k, v in expected_own.items()}

    p = import_focus_tree(next(r for r in refs if r.tree_id == "howardgov_focus"), [MD_ROOT])
    assert mt.tree_count(p) == 8 and p.activeTreeIndex == 0
    assert len([f for f in p.focuses if not f.shared]) == 88
    assert len([f for f in p.focuses if f.shared]) == 89
    assert len(p.focuses) == 177 and p.sharedPool == []
    assert len(mt.all_focuses(p)) == 450
    assert {t["treeId"]: t["ownFocuses"] for t in mt.tree_summaries(p)} == expected_own
    assert all(t["sharedFocuses"] == 89 for t in mt.tree_summaries(p))

    # Switching to the Abbott tree shifts the five shared branches by +9 x.
    before = _dump(p)
    base = {f.id: (f.position.x, f.position.y) for f in p.focuses if f.shared}
    assert mt.switch_tree(p, mt.index_of_tree(p, "australia_abbottgov_focus"))
    shifts = {(f.position.x - base[f.id][0], f.position.y - base[f.id][1])
              for f in p.focuses if f.shared}
    assert shifts == {(9, 0)} and len([f for f in p.focuses if f.shared]) == 89
    assert mt.switch_tree(p, 0) and _dump(p) == before

    # Validation: no errors except Millennium Dawn's own same-cell pairs in the
    # Gillard tree (two focuses written at the same relative position).
    errors = [i for i in validate_project(p) if i.severity == "error"]
    assert {i.code for i in errors} <= {"focus.position.overlap"}
    assert all(i.message.startswith("[gillardgov_focus] ") for i in errors)

    # Export → re-import keeps every tree.
    out = export_focus_tree(p)
    assert len(re.findall(r"^focus_tree = \{", out, re.M)) == 8
    assert len(re.findall(r"^shared_focus = \{", out, re.M)) == 89
    assert not [i for i in smoke_check(export_project_files(p)) if i.severity == "error"]
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True)
    (nf / "05_Australia.txt").write_text(out, encoding="utf-8")
    refs2 = _trees_in_file(str(nf / "05_Australia.txt"))
    assert [(r.tag, r.tree_id, r.focus_count) for r in refs2] == \
        [(r.tag, r.tree_id, r.focus_count) for r in refs]
    q = import_focus_tree(refs2[0], [str(tmp_path)])
    assert mt.tree_summaries(q) == mt.tree_summaries(p)
    assert _graph(q) == _graph(p)
    assert export_focus_tree(q) == out
