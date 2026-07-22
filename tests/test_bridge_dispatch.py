"""AI-bridge command dispatch — driven against a headless ProjectModel (no Qt app),
the same way tests/test_events.py exercises the model."""
from __future__ import annotations

import pytest

from core.bridge_dispatch import OP_NAMES, dispatch
from core.serialization import project_to_dict
from ui.project_model import ProjectModel

NA = "MEX_forge_national_assessment"
IND = "MEX_forge_industrial_plan"


def _model():
    return ProjectModel()  # sample MEX project: 3 focuses, 1 event


def _ok(model, op, **args):
    res = dispatch(model, op, args)
    assert res["ok"], res
    return res["result"]


# ----- read -----
def test_hello_reports_version_and_project():
    r = _ok(_model(), "hello")
    assert r["protocol"] >= 1
    assert r["project"]["tag"] == "MEX"
    assert r["project"]["focuses"] == 3


def test_get_project_and_list_focuses():
    m = _model()
    proj = _ok(m, "get_project")
    assert proj["countryTag"] == "MEX"
    focuses = _ok(m, "list_focuses")
    assert {f["id"] for f in focuses} >= {NA, IND}


def test_validate_shape():
    r = _ok(_model(), "validate")
    assert set(r) == {"errors", "warnings", "summary"}
    assert r["summary"]["errors"] == 0  # sample is clean


def test_reference_and_presets():
    m = _model()
    ref = _ok(m, "reference_data")
    assert any(t["tag"] == "USA" for t in ref["countryTags"])
    assert ref["resourceTypes"]
    rp = _ok(m, "list_reward_presets")
    assert any(p["kind"] == "political_power" for p in rp)
    cp = _ok(m, "list_condition_presets")
    assert any(p["kind"] == "has_country_flag" for p in cp)


# ----- focus writes -----
def test_add_focus_with_position_and_fields():
    m = _model()
    r = _ok(m, "add_focus", x=2, y=6, title="New Plan", icon="GFX_x")
    fid = r["id"]
    f = m.find_focus(fid)
    assert f and f.title == "New Plan" and f.position.x == 2 and f.icon == "GFX_x"


def test_add_focus_with_structured_reward_items():
    """The preferred agent authoring path (reference_data.rewardAuthoring):
    structured items in, preset-built script out — no rawLines involved."""
    from core.exporters import export_completion_reward_lines
    m = _model()
    r = _ok(m, "add_focus", x=4, y=6, title="Structured", completionReward={
        "items": [
            {"kind": "political_power", "enabled": True,
             "params": {"amount": 75}},
            {"kind": "treasury_change", "enabled": True,
             "params": {"amount": -6.5}},
        ]})
    f = m.find_focus(r["id"])
    assert [i.kind for i in f.completionReward.items] == [
        "political_power", "treasury_change"]
    assert not f.completionReward.rawLines
    exported = "\n".join(export_completion_reward_lines(f.completionReward))
    assert "add_political_power = 75" in exported
    assert "treasury_change = -6.5" in exported
    assert "modify_treasury_effect = yes" in exported
    # An unknown kind must be caught by validation, not silently export nothing.
    _ok(m, "update_focus", id=r["id"], completionReward={
        "items": [{"kind": "not_a_real_kind", "enabled": True, "params": {}}]})
    issues = _ok(m, "validate")
    assert any("not_a_real_kind" in i["message"] or "Unknown" in i["message"]
               for i in issues["errors"]), issues


def test_reference_data_teaches_structured_authoring():
    ref = _ok(_model(), "reference_data")
    note = ref["rewardAuthoring"]["note"]
    assert "items" in note and "rawLines" in note


def test_add_focus_with_explicit_id_and_reward():
    m = _model()
    r = _ok(m, "add_focus", id="MEX_custom", title="Custom",
            completionReward={"politicalPower": 25})
    assert r["id"] == "MEX_custom"
    assert m.find_focus("MEX_custom").completionReward.politicalPower == 25


def test_update_focus_changes_fields():
    m = _model()
    _ok(m, "update_focus", id=IND, cost=8, description="Updated.")
    f = m.find_focus(IND)
    assert f.cost == 8 and f.description == "Updated."


def test_rename_focus_rewrites_prereq():
    m = _model()
    r = _ok(m, "rename_focus", id=NA, new_id="MEX_assess")
    assert r["id"] == "MEX_assess"
    assert m.find_focus(IND).prerequisites == ["MEX_assess"]


def test_link_prerequisite_refuses_cycle():
    m = _model()
    # IND already requires NA; linking NA→requires IND would cycle.
    r = _ok(m, "link_prerequisite", target=NA, prereq=IND)
    assert "Skipped" in r["message"]
    assert IND not in m.find_focus(NA).prerequisites


def test_set_and_remove_mutex_symmetric():
    m = _model()
    _ok(m, "set_mutually_exclusive", a=IND, b="MEX_forge_security_review")
    assert "MEX_forge_security_review" in m.find_focus(IND).mutuallyExclusive
    assert IND in m.find_focus("MEX_forge_security_review").mutuallyExclusive
    _ok(m, "remove_mutex", a=IND, b="MEX_forge_security_review")
    assert "MEX_forge_security_review" not in m.find_focus(IND).mutuallyExclusive


def test_delete_focus_strips_references():
    m = _model()
    _ok(m, "delete_focus", id=NA)
    assert m.find_focus(NA) is None
    assert m.find_focus(IND).prerequisites == []


# ----- ideas / events -----
def test_add_event_dedupes_and_flips_include():
    m = _model()
    r = _ok(m, "add_event", event={"id": "MEX_forge.1", "title": "Dup"})
    assert r["id"] == "MEX_forge.2"
    assert m.project.exportSettings.includeEvents is True


def test_add_and_update_idea():
    m = _model()
    r = _ok(m, "add_idea", idea={"id": "MEX_spirit", "title": "Spirit"})
    assert r["id"] == "MEX_spirit"
    r2 = _ok(m, "update_idea", id="MEX_spirit", idea={"id": "MEX_spirit2", "title": "S2"})
    assert r2["id"] == "MEX_spirit2"


# ----- settings / export -----
def test_set_export_settings():
    m = _model()
    _ok(m, "set_export_settings", includeCountry=True, focusFileName="mex_tree")
    assert m.project.exportSettings.includeCountry is True
    assert m.project.exportSettings.focusFileName == "mex_tree"


def test_set_metadata():
    m = _model()
    _ok(m, "set_metadata", projectName="Renamed", treeId="mex_tree")
    assert m.project.projectName == "Renamed" and m.project.treeId == "mex_tree"


def test_export_lists_files():
    m = _model()
    r = _ok(m, "export")
    assert any(p.endswith("_focus_l_english.yml") for p in r["files"])


# ----- errors -----
def test_unknown_op():
    res = dispatch(_model(), "frobnicate", {})
    assert res["ok"] is False and "Unknown op" in res["error"]


def test_missing_required_arg():
    res = dispatch(_model(), "get_focus", {})
    assert res["ok"] is False and "Missing required" in res["error"]


def test_all_ops_registered():
    assert "add_focus" in OP_NAMES and "validate" in OP_NAMES
    assert "batch" in OP_NAMES


# ----- batch -----
def test_batch_applies_all_and_is_one_undo_step():
    m = _model()
    before = project_to_dict(m.project)
    r = _ok(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_b1", "x": 10, "y": 0, "title": "B1"}},
        {"op": "add_focus", "args": {"id": "MEX_b2", "x": 10, "y": 1, "title": "B2",
                                     "prerequisites": ["MEX_b1"]}},
        {"op": "update_focus", "args": {"id": "MEX_b2", "cost": 3}},
    ])
    assert r["count"] == 3
    assert r["results"][0]["id"] == "MEX_b1" and r["results"][1]["id"] == "MEX_b2"
    assert m.find_focus("MEX_b2").cost == 3
    assert m.undo()                        # ONE undo wipes the whole batch
    assert m.find_focus("MEX_b1") is None and m.find_focus("MEX_b2") is None
    assert project_to_dict(m.project) == before


def test_batch_mid_failure_rolls_back_everything():
    m = _model()
    before = project_to_dict(m.project)
    res = dispatch(m, "batch", {"ops": [
        {"op": "add_focus", "args": {"id": "MEX_tmp", "x": 9, "y": 9}},
        {"op": "get_focus", "args": {}},   # missing id -> fails mid-batch
    ]})
    assert res["ok"] is False
    assert "Batch failed at op 1 (get_focus)" in res["error"]
    assert "Nothing was applied" in res["error"]
    assert m.find_focus("MEX_tmp") is None
    assert project_to_dict(m.project) == before   # byte-identical rollback
    assert not m.can_undo() and not m.can_redo()  # stacks untouched


def test_batch_prevalidates_unknown_op_without_applying_anything():
    m = _model()
    res = dispatch(m, "batch", {"ops": [
        {"op": "add_focus", "args": {"id": "MEX_tmp", "x": 9, "y": 9}},
        {"op": "frobnicate", "args": {}},
    ]})
    assert res["ok"] is False and "Unknown op 'frobnicate'" in res["error"]
    assert m.find_focus("MEX_tmp") is None


def test_batch_refuses_io_and_nested_batch_ops():
    m = _model()
    for bad in ("batch", "load_project", "save", "export"):
        res = dispatch(m, "batch", {"ops": [{"op": bad, "args": {}}]})
        assert res["ok"] is False and "allowed inside a batch" in res["error"], res


def test_batch_caps_at_200_ops():
    res = dispatch(_model(), "batch",
                   {"ops": [{"op": "get_selection", "args": {}}] * 201})
    assert res["ok"] is False and "200" in res["error"]


def test_batch_allows_read_ops_and_returns_their_results():
    m = _model()
    r = _ok(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_r1", "x": 12, "y": 0}},
        {"op": "get_focus", "args": {"id": "MEX_r1"}},
    ])
    assert r["results"][1]["id"] == "MEX_r1"


def test_nested_model_batch_raises_runtime_error():
    m = _model()
    with pytest.raises(RuntimeError):
        with m.batch():
            with m.batch():
                pass  # pragma: no cover


# ----- place_below -----
def test_add_focus_place_below_places_without_linking():
    m = _model()
    ex, ey = m.free_cell_below(NA)
    r = _ok(m, "add_focus", place_below=NA, id="MEX_child")
    f = m.find_focus("MEX_child")
    assert (f.position.x, f.position.y) == (ex, ey)
    assert f.prerequisites == []           # placement only — prereqs stay explicit
    assert r["id"] == "MEX_child"


def test_add_focus_place_below_with_explicit_prereq():
    m = _model()
    _ok(m, "add_focus", place_below=NA, id="MEX_child2", prerequisites=[NA])
    assert m.find_focus("MEX_child2").prerequisites == [NA]


def test_place_below_unknown_parent_errors():
    res = dispatch(_model(), "add_focus", {"place_below": "MEX_nope"})
    assert res["ok"] is False and "MEX_nope" in res["error"]


def test_place_below_conflicts_with_explicit_xy():
    res = dispatch(_model(), "add_focus", {"place_below": NA, "x": 1, "y": 2})
    assert res["ok"] is False and "mutually exclusive" in res["error"]


def test_place_below_skips_occupied_cells():
    m = _model()
    px, py = m.free_cell_below(NA)
    _ok(m, "add_focus", x=px, y=py, id="MEX_blocker")
    nx, ny = m.free_cell_below(NA)
    assert (nx, ny) != (px, py) and ny == py   # same row, shifted column


def test_place_below_chains_inside_a_batch():
    m = _model()
    _ok(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_c1", "place_below": NA}},
        {"op": "add_focus", "args": {"id": "MEX_c2", "place_below": "MEX_c1",
                                     "prerequisites": ["MEX_c1"]}},
    ])
    c1, c2 = m.find_focus("MEX_c1"), m.find_focus("MEX_c2")
    assert c2.position.y == c1.position.y + 1  # saw the focus created earlier in the batch
    assert c2.prerequisites == ["MEX_c1"]
