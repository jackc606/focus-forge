"""OR-group prerequisites: helpers, serialization, export, import round-trip,
validation (unreachable rule), model rewrites, and the AI bridge."""
from __future__ import annotations

from core.bridge_dispatch import dispatch
from core.exporters import export_focus_tree
from core.focus_import import find_focus_trees, import_focus_tree
from core.serialization import _focus_from_dict, focus_to_dict
from core.types import (
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    iter_prereq_ids,
    map_prereq_groups,
    normalize_prereq_groups,
)
from core.validation import validate_project
from ui.project_model import ProjectModel


# ----- helpers -----------------------------------------------------------------

def test_normalize_preserves_or_group():
    assert normalize_prereq_groups([["a", "b"]]) == [["a", "b"]]


def test_normalize_keeps_plain_and_terms():
    assert normalize_prereq_groups(["a", "b"]) == ["a", "b"]


def test_normalize_mixed_and_or():
    assert normalize_prereq_groups([["a", "b"], "c"]) == [["a", "b"], "c"]


def test_normalize_collapses_singleton_group():
    assert normalize_prereq_groups([["a"]]) == ["a"]


def test_normalize_dedups_within_group_only():
    # In-group dup collapses, but "b" as its OWN prerequisite block is a hard
    # AND requirement and must survive even though "b" also appears in the group.
    assert normalize_prereq_groups([["a", "b", "a"], "b"]) == [["a", "b"], "b"]


def test_normalize_never_dedups_across_groups():
    # (a OR b) AND (a OR c): the shared "a" must stay in BOTH groups.
    assert normalize_prereq_groups([["a", "b"], ["a", "c"]]) == [["a", "b"], ["a", "c"]]
    # (a OR b) AND a: the flat hard requirement must not be deleted.
    assert normalize_prereq_groups([["a", "b"], "a"]) == [["a", "b"], "a"]


def test_normalize_drops_exact_duplicate_groups_and_empties():
    assert normalize_prereq_groups([["a", "b"], ["b", "a"]]) == [["a", "b"]]
    assert normalize_prereq_groups(["a", "a"]) == ["a"]
    assert normalize_prereq_groups([[], ["", None], "a"]) == ["a"]
    # a singleton group is the same block as the flat id — second one drops
    assert normalize_prereq_groups(["a", ["a"]]) == ["a"]


def test_normalize_flattens_overnesting():
    assert normalize_prereq_groups([[["a", "b"]]]) == [["a", "b"]]


def test_normalize_str_and_none():
    assert normalize_prereq_groups("a") == ["a"]
    assert normalize_prereq_groups(None) == []


def test_iter_prereq_ids_flattens():
    assert list(iter_prereq_ids([["a", "b"], "c"])) == ["a", "b", "c"]


def test_map_prereq_groups_rename_preserves_structure():
    out = map_prereq_groups([["a", "b"], "c"], lambda p: {"a": "x"}.get(p, p))
    assert out == [["x", "b"], "c"]


def test_map_prereq_groups_drop_collapses_group():
    out = map_prereq_groups([["a", "b"], "c"], lambda p: None if p == "a" else p)
    assert out == ["b", "c"]  # group of one collapses to a plain term


# ----- serialization round-trip ------------------------------------------------

def test_focus_dict_round_trip_keeps_or_group():
    f = FocusNodeData(id="f", prerequisites=[["a", "b"], "c"])
    again = _focus_from_dict(focus_to_dict(f))
    assert again.prerequisites == [["a", "b"], "c"]


# ----- exporter ----------------------------------------------------------------

def _tree_with(prereqs):
    return FocusForgeProject(
        projectName="T", countryTag="TST", treeId="tst_focus",
        focuses=[
            FocusNodeData(id="a", title="A", position=FocusPosition(0, 0)),
            FocusNodeData(id="b", title="B", position=FocusPosition(1, 0)),
            FocusNodeData(id="c", title="C", position=FocusPosition(2, 0)),
            FocusNodeData(id="t", title="T", position=FocusPosition(1, 1),
                          prerequisites=prereqs),
        ],
    )


def test_export_or_group_is_one_block():
    out = export_focus_tree(_tree_with([["a", "b"]]))
    assert "prerequisite = { focus = a focus = b }" in out


def test_export_and_terms_are_separate_blocks():
    out = export_focus_tree(_tree_with(["a", "b"]))
    assert "prerequisite = { focus = a }" in out
    assert "prerequisite = { focus = b }" in out


def test_export_mixed():
    out = export_focus_tree(_tree_with([["a", "b"], "c"]))
    assert "prerequisite = { focus = a focus = b }" in out
    assert "prerequisite = { focus = c }" in out


# ----- importer round-trip -----------------------------------------------------

_OR_TREE = """
focus_tree = {
\tid = test_focus
\tfocus = {
\t\tid = TST_a
\t\tx = 0
\t\ty = 0
\t}
\tfocus = {
\t\tid = TST_b
\t\tx = 1
\t\ty = 0
\t}
\tfocus = {
\t\tid = TST_t
\t\tx = 0
\t\ty = 1
\t\tprerequisite = { focus = TST_a focus = TST_b }
\t}
\tfocus = {
\t\tid = TST_u
\t\tx = 1
\t\ty = 1
\t\tprerequisite = { focus = TST_a }
\t\tprerequisite = { focus = TST_b }
\t}
}
"""


def _setup_or(tmp_path):
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True)
    (nf / "test.txt").write_text(_OR_TREE, encoding="utf-8")
    loc = tmp_path / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "test_l_english.yml").write_text("l_english:\n", encoding="utf-8")
    return [str(tmp_path)]


def test_import_or_block_becomes_group(tmp_path):
    roots = _setup_or(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    by = {f.id: f for f in proj.focuses}
    # one block with two focus= -> OR group
    assert by["TST_t"].prerequisites == [["TST_a", "TST_b"]]
    # two separate blocks -> two AND terms
    assert by["TST_u"].prerequisites == ["TST_a", "TST_b"]


def test_import_export_or_round_trips(tmp_path):
    roots = _setup_or(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    out = export_focus_tree(proj)
    assert "prerequisite = { focus = TST_a focus = TST_b }" in out


# ----- validation --------------------------------------------------------------

def _and_of_mutex_project():
    # peace XOR war; t requires BOTH (separate AND blocks) -> unreachable
    return FocusForgeProject(
        projectName="T", countryTag="TST", treeId="tst_focus",
        exportSettings=ExportSettings(focusFileName="tst", localisationPrefix="tst"),
        focuses=[
            FocusNodeData(id="peace", title="P", position=FocusPosition(0, 0),
                          mutuallyExclusive=["war"], icon="x", description="d"),
            FocusNodeData(id="war", title="W", position=FocusPosition(1, 0),
                          mutuallyExclusive=["peace"], icon="x", description="d"),
            FocusNodeData(id="t", title="T", position=FocusPosition(0, 1),
                          prerequisites=["peace", "war"], icon="x", description="d"),
        ],
    )


def test_and_of_mutex_is_unreachable():
    codes = {i.code for i in validate_project(_and_of_mutex_project())}
    assert "focus.prerequisite.unreachable" in codes


def test_or_group_of_mutex_is_reachable():
    proj = _and_of_mutex_project()
    proj.focuses[2].prerequisites = [["peace", "war"]]  # OR instead of AND
    codes = {i.code for i in validate_project(proj)}
    assert "focus.prerequisite.unreachable" not in codes


def test_or_group_missing_ref_still_flagged():
    proj = _and_of_mutex_project()
    proj.focuses[2].prerequisites = [["peace", "ghost"]]
    codes = {i.code for i in validate_project(proj)}
    assert "focus.prerequisite.missing" in codes


# ----- model rewrites ----------------------------------------------------------

def _model_with_or():
    m = ProjectModel()
    m.project.focuses = [
        FocusNodeData(id="a", position=FocusPosition(0, 0)),
        FocusNodeData(id="b", position=FocusPosition(1, 0)),
        FocusNodeData(id="t", position=FocusPosition(0, 1), prerequisites=[["a", "b"]]),
    ]
    return m


def test_rename_rewrites_inside_or_group():
    m = _model_with_or()
    m.rename_focus("a", "aa")
    assert m.find_focus("t").prerequisites == [["aa", "b"]]


def test_delete_strips_from_or_group_and_collapses():
    m = _model_with_or()
    m.delete_focus("a")
    assert m.find_focus("t").prerequisites == ["b"]


def test_remove_prerequisite_drops_from_group():
    m = _model_with_or()
    m.remove_prerequisite("t", "a")
    assert m.find_focus("t").prerequisites == ["b"]


# ----- AI bridge ---------------------------------------------------------------

def test_bridge_update_focus_accepts_or_group():
    m = ProjectModel()
    m.project.focuses = [
        FocusNodeData(id="a", position=FocusPosition(0, 0)),
        FocusNodeData(id="b", position=FocusPosition(1, 0)),
        FocusNodeData(id="t", position=FocusPosition(0, 1)),
    ]
    res = dispatch(m, "update_focus", {"id": "t", "prerequisites": [["a", "b"]]})
    assert res["ok"], res
    assert m.find_focus("t").prerequisites == [["a", "b"]]
