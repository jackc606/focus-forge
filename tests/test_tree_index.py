"""The "replace, don't duplicate" guard: base-tree index, collision report,
import defaults/provenance, validation + bridge wiring.

Background (real user report): an edited copy of MD's Nigeria tree exported
as nga_focus.txt loaded NEXT TO MD's nigeria file, defined every focus twice
and broke the tree in-game. Nothing here may let that happen silently again.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from core import bridge_dispatch
from core import tree_index as TI
from core.bridge_dispatch import dispatch
from core.export_check import collision_issues_for
from core.exporters import export_project_files
from core.focus_import import FocusTreeRef, find_focus_trees, import_focus_tree
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.tree_index import (
    BaseTreeIndex,
    collision_issues,
    current_index,
    find_collisions,
    scan_base_trees,
)
from core.types import ExportSettings, FocusForgeProject, FocusNodeData, FocusPosition, FocusShortcut
from core.validation import validate_project
from ui.project_model import ProjectModel

NIGERIA = """
focus_tree = {
\tid = nigeria_focus
\tcountry = {
\t\tfactor = 0
\t\tmodifier = { add = 10 tag = NIG }
\t}
\tfocus = {
\t\tid = NGA_a
\t\ticon = GFX_goal_generic_construct_civilian
\t\tx = 0
\t\ty = 0
\t\tcost = 10
\t\tcompletion_reward = { add_political_power = 50 }
\t}
\tfocus = {
\t\tid = NGA_b
\t\ticon = GFX_goal_generic_construct_civilian
\t\tx = 0
\t\ty = 1
\t\tprerequisite = { focus = NGA_a }
\t\tmutually_exclusive = { focus = NGA_a }
\t\tavailable = { has_completed_focus = NGA_a }
\t\tcost = 10
\t}
\tshortcut = {
\t\tname = NGA_shortcut
\t\ttarget = NGA_b
\t}
}
"""


@pytest.fixture(autouse=True)
def _fresh_index_cache():
    TI.invalidate()
    yield
    TI.invalidate()


def _root(tmp_path, basename: str = "05_nigeria.txt", text: str = NIGERIA):
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True, exist_ok=True)
    (nf / basename).write_text(text, encoding="utf-8")
    return [str(tmp_path)]


def _project(file_name="nga_focus", tree_id="nga_focus", ids=("NGA_a", "NGA_b")):
    return FocusForgeProject(
        projectName="p", countryTag="NGA", treeId=tree_id,
        focuses=[FocusNodeData(id=i, title=i, position=FocusPosition(n, 0))
                 for n, i in enumerate(ids)],
        exportSettings=ExportSettings(modPrefix="NGA", focusFileName=file_name,
                                      localisationPrefix="NGA"))


# ----- scan -------------------------------------------------------------------------
def test_scan_finds_basename_tree_and_focus_ids(tmp_path):
    idx = scan_base_trees(_root(tmp_path))
    assert idx.basenames() == {"05_nigeria.txt"}
    assert idx.file_for_tree("nigeria_focus") == "05_nigeria.txt"
    assert idx.file_for_focus("NGA_a") == "05_nigeria.txt"
    assert idx.file_for_focus("NGA_b") == "05_nigeria.txt"
    assert idx.file_for_focus("NGA_zzz") is None
    assert idx.file_for_tree("other") is None


def test_scan_cache_invalidates_on_mtime_change(tmp_path):
    roots = _root(tmp_path)
    path = tmp_path / "common" / "national_focus" / "05_nigeria.txt"
    first = scan_base_trees(roots)
    assert first.file_for_focus("NGA_c") is None
    again = scan_base_trees(roots)
    assert again.files[0] is first.files[0]          # per-file cache hit
    path.write_text(NIGERIA.replace("id = NGA_b", "id = NGA_c"), encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))  # guarantee a new mtime
    third = scan_base_trees(roots)
    assert third.file_for_focus("NGA_c") == "05_nigeria.txt"
    assert third.file_for_focus("NGA_b") is None


def test_scan_honours_replace_path(tmp_path):
    vanilla = tmp_path / "vanilla"
    _root(vanilla, "germany.txt", NIGERIA.replace("nigeria_focus", "german_focus")
          .replace("NGA_", "GER_"))
    mod = tmp_path / "mod"
    _root(mod)
    (mod / "descriptor.mod").write_text(
        'name="MD"\nreplace_path="common/national_focus"\n', encoding="utf-8")
    idx = scan_base_trees([str(vanilla), str(mod)])
    assert idx.basenames() == {"05_nigeria.txt"}   # vanilla dropped, like the importer


def test_current_index_is_cached_until_the_folder_changes(tmp_path):
    roots = _root(tmp_path)
    a = current_index(lambda: roots)
    b = current_index(lambda: roots)
    assert a is b
    # A new file changes the national_focus dir's mtime → new key → rebuilt.
    nf = tmp_path / "common" / "national_focus"
    (nf / "06_ghana.txt").write_text(NIGERIA.replace("nigeria_focus", "ghana_focus")
                                     .replace("NGA_", "GHA_"), encoding="utf-8")
    os.utime(nf, (time.time() + 5, time.time() + 5))
    c = current_index(lambda: roots)
    assert c is not a
    assert c.basenames() == {"05_nigeria.txt", "06_ghana.txt"}
    assert current_index(lambda: []) is None


def test_current_index_non_blocking_builds_in_background(tmp_path):
    roots = _root(tmp_path)
    landed = []
    assert current_index(lambda: roots, block=False, on_ready=lambda: landed.append(1)) is None
    deadline = time.time() + 10
    while not landed and time.time() < deadline:
        time.sleep(0.02)
    assert landed == [1]
    assert current_index(lambda: roots, block=False).file_for_focus("NGA_a") == "05_nigeria.txt"


# ----- collisions -------------------------------------------------------------------
def test_same_basename_replaces_no_issue(tmp_path):
    idx = scan_base_trees(_root(tmp_path))
    rep = find_collisions(_project(file_name="05_nigeria", tree_id="nigeria_focus"), idx)
    assert rep.replaces == "05_nigeria.txt"
    assert not rep.is_problem
    assert rep.duplicate_ids == {} and rep.tree_id_clash is None
    assert collision_issues(rep) == []


def test_different_basename_shared_ids_is_a_problem(tmp_path):
    idx = scan_base_trees(_root(tmp_path))
    rep = find_collisions(_project(), idx)
    assert rep.is_problem
    assert rep.replaces is None
    assert rep.duplicate_ids == {"05_nigeria.txt": ["NGA_a", "NGA_b"]}
    assert rep.suggested_basename == "05_nigeria.txt"
    assert rep.suggested_stem == "05_nigeria"
    issues = collision_issues(rep)
    assert [i.code for i in issues] == ["project.tree.duplicate"]
    assert issues[0].severity == "error"
    msg = issues[0].message
    assert "nga_focus.txt" in msg and "05_nigeria.txt" in msg
    assert "2 of your focus ids" in msg
    assert "'05_nigeria'" in msg           # the one-click fix target, as a stem
    assert "Fix:" in msg


def test_suggested_basename_is_the_file_holding_most_ids(tmp_path):
    roots = _root(tmp_path)
    _root(tmp_path, "06_ghana.txt", NIGERIA.replace("nigeria_focus", "ghana_focus")
          .replace("NGA_b", "GHA_x").replace("NGA_a", "GHA_a"))
    idx = scan_base_trees(roots)
    rep = find_collisions(_project(ids=("NGA_a", "NGA_b", "GHA_a")), idx)
    assert set(rep.duplicate_ids) == {"05_nigeria.txt", "06_ghana.txt"}
    assert rep.suggested_basename == "05_nigeria.txt"
    assert len(collision_issues(rep)) == 2       # one issue per colliding base file


def test_tree_id_only_clash(tmp_path):
    idx = scan_base_trees(_root(tmp_path))
    rep = find_collisions(_project(tree_id="nigeria_focus", ids=("NGA_new_1",)), idx)
    assert rep.is_problem
    assert rep.duplicate_ids == {}
    assert rep.tree_id_clash == "05_nigeria.txt"
    assert rep.suggested_basename == "05_nigeria.txt"
    issues = collision_issues(rep)
    assert [i.code for i in issues] == ["project.tree.idClash"]
    assert "nigeria_focus" in issues[0].message and "05_nigeria" in issues[0].message


def test_empty_index_nothing():
    rep = find_collisions(_project(), BaseTreeIndex())
    assert not rep.is_problem and rep.replaces is None and rep.suggested_basename is None
    assert find_collisions(_project(), None).is_problem is False


def test_basename_match_is_case_insensitive(tmp_path):
    idx = scan_base_trees(_root(tmp_path, "Nigeria.TXT"))
    rep = find_collisions(_project(file_name="nigeria"), idx)
    assert rep.replaces == "Nigeria.TXT"
    assert not rep.is_problem


# ----- import defaults + provenance ---------------------------------------------------
def test_import_tag_owned_ref_replaces_its_file(tmp_path):
    roots = _root(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    assert ref.tag == "NIG"
    proj = import_focus_tree(ref, roots)
    assert proj.exportSettings.focusFileName == "05_nigeria"
    assert proj.treeId == "nigeria_focus"
    assert proj.source == {"file": "05_nigeria.txt", "treeId": "nigeria_focus",
                           "tag": "NIG", "mode": "replace"}
    # And the round trip proves it: the export replaces, nothing duplicates.
    rep = find_collisions(proj, scan_base_trees(roots))
    assert rep.replaces == "05_nigeria.txt" and not rep.is_problem


def test_import_generic_path_keeps_tag_focus_and_records_copy(tmp_path):
    roots = _root(tmp_path)
    base = find_focus_trees(roots, use_cache=False)[0]
    ref = FocusTreeRef(tag="MEX", tree_id=base.tree_id, focus_count=base.focus_count,
                       file=base.file, prefix_ids=True)
    proj = import_focus_tree(ref, roots)
    assert proj.exportSettings.focusFileName == "mex_focus"
    assert proj.treeId == "mex_focus"
    assert proj.source["mode"] == "copy"
    assert proj.projectName == "MEX focus tree (from generic)"


def test_import_id_prefix_makes_a_separate_copy(tmp_path):
    roots = _root(tmp_path)
    base = find_focus_trees(roots, use_cache=False)[0]
    ref = FocusTreeRef(tag="NGA", tree_id=base.tree_id, focus_count=base.focus_count,
                       file=base.file, id_prefix="NGA_NEW")
    proj = import_focus_tree(ref, roots)
    assert {f.id for f in proj.focuses} == {"NGA_NEW_NGA_a", "NGA_NEW_NGA_b"}
    b = next(f for f in proj.focuses if f.id == "NGA_NEW_NGA_b")
    assert b.prerequisites == ["NGA_NEW_NGA_a"]
    assert b.mutuallyExclusive == ["NGA_NEW_NGA_a"]
    assert proj.shortcuts[0].target == "NGA_NEW_NGA_b"
    assert proj.treeId == "nga_new_focus"
    assert proj.exportSettings.focusFileName == "nga_new_focus"
    assert proj.projectName == "NGA focus tree (copy)"
    assert proj.source["mode"] == "copy"
    assert not find_collisions(proj, scan_base_trees(roots)).is_problem


def test_import_rejects_illegal_prefix(tmp_path):
    roots = _root(tmp_path)
    base = find_focus_trees(roots, use_cache=False)[0]
    for bad in ("1NGA", "NGA NEW", "NGA-NEW", "_x"):
        ref = FocusTreeRef(tag="NGA", tree_id=base.tree_id, focus_count=1,
                           file=base.file, id_prefix=bad)
        with pytest.raises(ValueError):
            import_focus_tree(ref, roots)


# ----- serialization ------------------------------------------------------------------
def test_source_round_trips_and_old_files_load_without_it():
    proj = make_sample_project()
    proj.source = {"file": "05_nigeria.txt", "treeId": "nigeria_focus", "tag": "NGA",
                   "mode": "replace"}
    d = project_to_dict(proj)
    assert d["source"]["mode"] == "replace"
    back = project_from_dict(json.loads(json.dumps(d)))
    assert back.source == proj.source
    d.pop("source")
    assert project_from_dict(d).source == {}


def test_source_never_changes_the_exported_files():
    plain = make_sample_project()
    tagged = make_sample_project()
    tagged.source = {"file": "x.txt", "treeId": "t", "tag": "MEX", "mode": "copy"}
    a = [(f.relativePath, f.content, f.bom) for f in export_project_files(plain)]
    b = [(f.relativePath, f.content, f.bom) for f in export_project_files(tagged)]
    assert a == b
    # And through a save/load round trip (what an existing project file does).
    reloaded = project_from_dict(project_to_dict(tagged))
    c = [(f.relativePath, f.content, f.bom) for f in export_project_files(reloaded)]
    assert a == c


# ----- validation ---------------------------------------------------------------------
def test_validate_project_with_and_without_index(tmp_path):
    idx = scan_base_trees(_root(tmp_path))
    proj = _project()
    assert "project.tree.duplicate" not in {i.code for i in validate_project(proj)}
    with_idx = validate_project(proj, tree_index=idx)
    hits = [i for i in with_idx if i.code == "project.tree.duplicate"]
    assert len(hits) == 1 and hits[0].severity == "error"
    fixed = _project(file_name="05_nigeria")
    assert not [i for i in validate_project(fixed, tree_index=idx) if i.code.startswith("project.tree.")]


def test_collision_issues_for_convenience(tmp_path):
    roots = _root(tmp_path)
    assert [i.code for i in collision_issues_for(_project(), roots)] == ["project.tree.duplicate"]
    assert collision_issues_for(_project(), []) == []
    assert collision_issues_for(_project(file_name="05_nigeria"), roots) == []


# ----- bridge -------------------------------------------------------------------------
@pytest.fixture()
def roots_provider(tmp_path):
    roots = _root(tmp_path)
    # The UI's country-tag hook installs ITS roots provider (Settings roots)
    # the first time a model validates; trigger that once so the test's
    # provider is the one left standing.
    ProjectModel().issues()
    bridge_dispatch.set_roots_provider(lambda: roots)
    try:
        yield roots
    finally:
        bridge_dispatch.set_roots_provider(None)


def _model_for(project):
    m = ProjectModel()
    m.replace_project(project, path=None)
    return m


def test_dispatch_validate_and_smoke_check_include_collisions(roots_provider):
    m = _model_for(_project())
    res = dispatch(m, "validate", {})
    assert res["ok"], res
    codes = [e["code"] for e in res["result"]["errors"]]
    assert codes.count("project.tree.duplicate") == 1
    smoke = dispatch(m, "smoke_check", {})
    assert smoke["ok"], smoke
    assert "project.tree.duplicate" in [e["code"] for e in smoke["result"]["errors"]]
    # Fix through the bridge → clean.
    assert dispatch(m, "set_export_settings", {"focusFileName": "05_nigeria"})["ok"]
    res = dispatch(m, "validate", {})
    assert "project.tree.duplicate" not in [e["code"] for e in res["result"]["errors"]]
    smoke = dispatch(m, "smoke_check", {})
    assert not [e for e in smoke["result"]["errors"] if e["code"].startswith("project.tree.")]


def test_dispatch_silent_without_roots_provider():
    bridge_dispatch.set_roots_provider(None)
    m = _model_for(_project())
    res = dispatch(m, "validate", {})
    assert "project.tree.duplicate" not in [e["code"] for e in res["result"]["errors"]]
