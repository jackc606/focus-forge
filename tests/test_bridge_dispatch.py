"""AI-bridge command dispatch — driven against a headless ProjectModel (no Qt app),
the same way tests/test_events.py exercises the model."""
from __future__ import annotations

from core.bridge_dispatch import OP_NAMES, dispatch
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
