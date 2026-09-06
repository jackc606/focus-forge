"""AI-bridge hardening for weaker models (v0.4.3): op specs + describe_op + tool
schemas, arg normalisation (aliases / unknown-key rejection / no exception class
names), fail-fast write checks, inline validation issues, deferred batch
reference checks, the bridge-served guide, the standard MD filter list and the
compact / filtered reads. Driven headlessly through ``dispatch`` like
tests/test_bridge_dispatch.py."""
from __future__ import annotations

import ast
import inspect
import json
import re
import time
from pathlib import Path

import pytest

from core import bridge_dispatch as bd
from core import md_focus_guide as guide
from core.bridge_dispatch import OP_SPECS, dispatch, normalize_args, tool_schemas
from core.bridge_specs import GUI_ONLY_OPS, JSON_TYPES
from core.md_edition import BETA, MAIN
from core.presets import EDITION_ONLY_FOCUS_FILTERS, MD_FOCUS_FILTERS
from core.reward_presets import REWARD_PRESETS
from core.sample_project import make_sample_project
from core.serialization import project_to_dict
from core.validation import validate_project
from ui.project_model import ProjectModel

NA = "MEX_forge_national_assessment"      # (0, 0)
IND = "MEX_forge_industrial_plan"         # (-4, 1)
SEC = "MEX_forge_security_review"         # (4, 1)

_CLASS_NAME = re.compile(r"\b[A-Z][A-Za-z]*(Error|Exception)\b")


def _model():
    return ProjectModel()


def _ok(model, op, **args):
    res = dispatch(model, op, args)
    assert res["ok"], res
    return res["result"]


def _err(model, op, **args) -> str:
    res = dispatch(model, op, args)
    assert res["ok"] is False, res
    assert not _CLASS_NAME.search(res["error"]), res["error"]
    return res["error"]


# ===================== 1. op specs / describe_op / tool schemas =====================

def test_every_op_has_a_spec_and_every_spec_has_a_handler():
    assert set(bd._OPS) | set(GUI_ONLY_OPS) == set(OP_SPECS)
    for name, spec in OP_SPECS.items():
        assert spec.description and spec.returns, name
        for arg, a in spec.args.items():
            assert set(a) == {"type", "required", "description", "aliases"}, (name, arg)
            assert a["type"] in JSON_TYPES, (name, arg, a["type"])


def test_every_spec_example_normalizes_and_names_required_args():
    for name, spec in OP_SPECS.items():
        out = normalize_args(name, dict(spec.example))
        for arg, a in spec.args.items():
            if a["required"]:
                assert arg in out, f"{name} example lacks required '{arg}'"


def test_tool_schemas_are_valid_json_schema_function_tools():
    tools = tool_schemas()
    assert {t["function"]["name"] for t in tools} == set(OP_SPECS)
    for t in tools:
        assert t["type"] == "function"
        params = t["function"]["parameters"]
        assert params["type"] == "object"
        spec = OP_SPECS[t["function"]["name"]]
        for arg, prop in params["properties"].items():
            assert prop["type"] in ("string", "number", "integer", "boolean", "array", "object")
            assert prop["type"] == spec.args[arg]["type"]
        required = [a for a, d in spec.args.items() if d["required"]]
        assert params.get("required", []) == required
    json.dumps(tools)  # serialisable


def test_describe_op_single_and_all_forms():
    m = _model()
    one = dispatch(m, "describe_op", {"op": "add_focus"})["result"]
    assert one["op"] == "add_focus" and one["example"]["id"] and "x" in one["args"]
    assert one["args"]["id"]["aliases"] == ["focus_id"]
    every = _ok(m, "describe_op")
    assert set(every["ops"]) == set(OP_SPECS)
    assert set(every["ops"]["add_focus"]) == {"description", "args"}   # no examples
    res = dispatch(m, "describe_op", {"op": "nope"})
    assert res["ok"] is False and "Unknown op 'nope'" in res["error"]


def test_hello_lists_ops_and_start_here():
    r = _ok(_model(), "hello")
    assert r["ops"] == sorted(OP_SPECS)
    assert "guide" in r["start_here"] and "describe_op" in r["start_here"]


def _mcp_calls(src: str):
    """(tool, op, arg keys) for every _call(...) inside an @mcp.tool function,
    resolving `args = _compact(...)` + `args["k"] = ...` indirections."""
    for node in ast.parse(src).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
                   for d in node.decorator_list):
            continue
        named: dict = {}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
                tgt, val = sub.targets[0], sub.value
                if isinstance(tgt, ast.Name) and isinstance(val, ast.Call) \
                        and getattr(val.func, "id", "") == "_compact":
                    named.setdefault(tgt.id, set()).update(kw.arg for kw in val.keywords)
                elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name) \
                        and isinstance(tgt.slice, ast.Constant):
                    named.setdefault(tgt.value.id, set()).add(tgt.slice.value)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "_call":
                op = sub.args[0].value
                keys: set = set()
                if len(sub.args) > 1:
                    a = sub.args[1]
                    if isinstance(a, ast.Dict):
                        keys |= {k.value for k in a.keys}
                    elif isinstance(a, ast.Call) and getattr(a.func, "id", "") == "_compact":
                        keys |= {kw.arg for kw in a.keywords}
                    elif isinstance(a, ast.Name):
                        keys |= named.get(a.id, set())
                yield node.name, op, keys


def test_mcp_server_tools_send_only_accepted_args():
    pytest.importorskip("mcp")
    from focusforge_mcp import server
    seen = 0
    for tool, op, keys in _mcp_calls(inspect.getsource(server)):
        seen += 1
        assert op in OP_SPECS, (tool, op)
        accepted = set(OP_SPECS[op].args) | set(bd.alias_map(op))
        assert keys <= accepted, (tool, op, keys - accepted)
    assert seen >= 30
    tools = {t for t, _op, _k in _mcp_calls(inspect.getsource(server))}
    assert {"describe_op", "guide", "list_focuses", "reference_data"} <= tools


# ===================== 2. arg normalisation =====================

def test_unknown_arg_rejected_with_accepted_list_and_hint():
    msg = _err(_model(), "add_focus", titel="x")
    assert msg.startswith("Unknown arg(s) for add_focus: 'titel'. Accepted: title, x, y, id, icon, "
                          "cost, description, prerequisites, place_below, completionReward, "
                          "available, aiWillDo, aiModifiers, filters, notes")
    assert msg.endswith("Did you mean 'title'?")
    msg = _err(_model(), "get_focus", zzzz=1)
    assert "Did you mean" not in msg and "Accepted: id." in msg


def test_aliases_map_to_canonical_names():
    m = _model()
    assert _ok(m, "get_focus", focus_id=NA)["id"] == NA
    r = _ok(m, "update_focus", focus_id=IND, completion_reward={
        "items": [{"kind": "political_power", "params": {"amount": 5}}]},
        mutually_exclusive=[SEC], ai_will_do=3, ai_modifiers=[{"factor": 0, "trigger": {
            "items": [{"kind": "at_war", "params": {}}]}}])
    assert r["mutuallyExclusive"] == [SEC] and r["aiWillDo"] == 3 and r["aiModifierCount"] == 1
    assert m.find_focus(IND).completionReward.items[0].params["amount"] == 5
    r = _ok(m, "link_prerequisite", focus=SEC, prerequisite=IND)
    assert r["message"].startswith("Linked")
    r = _ok(m, "set_mutually_exclusive", focus_a=IND, focus_b=SEC)
    assert SEC in m.find_focus(IND).mutuallyExclusive
    assert _ok(m, "delete_focuses", focus_ids=[SEC])["deleted"] == [SEC]


def test_update_focus_accepts_top_level_xy_and_requires_both():
    m = _model()
    r = _ok(m, "update_focus", id=IND, x=-6, y=2)
    assert (r["x"], r["y"]) == (-6, 2)
    assert "BOTH x and y" in _err(m, "update_focus", id=IND, x=3)
    assert "disagree" in _err(m, "update_focus", id=IND, x=1, y=1, position={"x": 2, "y": 2})


def test_alias_and_canonical_conflict_is_rejected():
    assert "either 'id' or its alias 'focus_id'" in _err(_model(), "get_focus", id=NA, focus_id=IND)


def test_filters_single_string_is_coerced_then_validated():
    m = _model()
    _ok(m, "update_focus", id=IND, filters="FOCUS_FILTER_ARMY")
    assert m.find_focus(IND).filters == ["FOCUS_FILTER_ARMY"]
    msg = _err(m, "update_focus", id=IND, filters="political")
    assert "not a FOCUS_FILTER_* token" in msg and "FOCUS_FILTER_POLITICAL" in msg


def test_error_text_never_names_a_python_exception_class():
    class Boom:
        project = make_sample_project()

        def find_focus(self, fid):
            raise RuntimeError("index exploded")

    msg = _err(Boom(), "get_focus", id="x")
    assert msg == ("Internal error in get_focus: index exploded. Call describe_op('get_focus') "
                   "for the expected arg shapes.")
    for op, args in (("get_focus", {}), ("add_focus", {"x": "a", "y": 1}),
                     ("update_focus", {"id": IND, "cost": "lots"}),
                     ("batch", {"ops": [{"op": "get_focus", "args": {"idd": 1}}]})):
        _err(_model(), op, **args)


def test_batch_entry_with_unknown_arg_is_rejected_before_anything_applies():
    m = _model()
    before = project_to_dict(m.project)
    msg = _err(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_t", "x": 9, "y": 9}},
        {"op": "add_focus", "args": {"id": "MEX_u", "x": 9, "y": 10, "titel": "U"}}])
    assert msg.startswith("Batch rejected at op 1 (add_focus): Unknown arg(s)")
    assert "Nothing was applied" in msg and project_to_dict(m.project) == before


# ===================== 3. fail-fast write checks =====================

def test_bad_ids_rejected_with_slug_suggestion():
    m = _model()
    msg = _err(m, "add_focus", id="x y", x=10, y=10)
    assert "'x y' is not a valid focus id" in msg and "Suggested: 'x_y'" in msg
    msg = _err(m, "rename_focus", id=IND, new_id="9 Lives!")
    assert "Suggested: 'f_9_lives'" in msg
    assert m.find_focus(IND) is not None and len(m.project.focuses) == 3


def test_occupied_cell_rejected_with_nearest_free_cells():
    m = _model()
    msg = _err(m, "add_focus", id="MEX_dup", x=0, y=0)
    assert msg == ("Cell (0, 0) is occupied by 'MEX_forge_national_assessment'. Nearest free "
                   "cells: (2, 0), (-2, 0), (0, 1). Pass allow_overlap=true to place anyway.")
    assert m.find_focus("MEX_dup") is None
    _ok(m, "add_focus", id="MEX_dup", x=0, y=0, allow_overlap=True)
    assert m.find_focus("MEX_dup").position.x == 0


def test_same_row_suggestions_respect_min_dx():
    occupied = {(0, 0): "a", (3, 0): "b"}     # (1,0) and (2,0) are free but too close
    cells = bd._nearest_free_cells(occupied, 0, 0)
    assert (1, 0) not in cells and (2, 0) not in cells
    assert cells[0] in ((-2, 0), (5, 0), (0, 1))


def test_update_focus_move_onto_occupied_cell_rejected_but_own_cell_ok():
    m = _model()
    msg = _err(m, "update_focus", id=IND, position={"x": 4, "y": 1})
    assert "occupied by 'MEX_forge_security_review'" in msg
    assert m.find_focus(IND).position.x == -4
    _ok(m, "update_focus", id=IND, position={"x": -4, "y": 1})          # no-op move
    _ok(m, "update_focus", id=IND, x=4, y=1, allow_overlap=True)


def test_unknown_reward_kind_rejected_with_closest():
    msg = _err(_model(), "add_focus", x=10, y=10, completionReward={
        "items": [{"kind": "add_political_power", "params": {"amount": 50}}]})
    assert msg.startswith("Unknown reward preset 'add_political_power'. Closest: political_power")
    assert "list_reward_presets(compact=true)" in msg


def test_reward_param_checks():
    m = _model()
    base = dict(x=10, y=10)
    msg = _err(m, "add_focus", completionReward={"items": [
        {"kind": "political_power", "params": {"amt": 50}}]}, **base)
    assert "unknown param(s) 'amt'" in msg and "amount:number*" in msg
    msg = _err(m, "add_focus", completionReward={"items": [
        {"kind": "political_power", "params": {}}]}, **base)
    assert "missing required param 'amount'" in msg
    msg = _err(m, "add_focus", completionReward={"items": [
        {"kind": "political_power", "params": {"amount": "fifty"}}]}, **base)
    assert "'amount' must be a number" in msg
    msg = _err(m, "add_focus", completionReward={"items": [
        {"kind": "political_power", "amount": 50}]}, **base)
    assert "unknown key(s) 'amount'" in msg and 'under "params"' in msg
    # optional params may still be omitted
    _ok(m, "add_focus", completionReward={"items": [
        {"kind": "country_event", "params": {"eventId": "MEX_forge.1"}}]}, **base)
    assert len(m.project.focuses) == 4


def test_reward_block_as_string_or_list_is_rejected_without_traceback_leak():
    m = _model()
    msg = _err(m, "add_focus", x=10, y=10, completionReward="add_political_power = 50")
    assert msg == ('completionReward must be an object: {"items": [{"kind": "political_power", '
                   '"params": {"amount": 50}}], "rawLines": ["..."]}. You passed a string — put '
                   "raw script lines in rawLines.")
    assert "You passed a list" in _err(m, "add_focus", x=10, y=10, completionReward=["x"])
    assert "available must be an object" in _err(m, "update_focus", id=IND, available="has_war = yes")


def test_condition_items_checked_in_available_ai_triggers_and_events():
    m = _model()
    msg = _err(m, "update_focus", id=IND, available={"items": [{"kind": "has_flag", "params": {}}]})
    assert "Unknown condition preset 'has_flag'" in msg and "has_country_flag" in msg
    msg = _err(m, "update_focus", id=IND, aiModifiers=[{"factor": 0, "trigger": {
        "items": [{"kind": "has_country_flag", "params": {}}]}}])
    assert "aiModifiers[0].trigger.items[1] (has_country_flag): missing required param 'flag'" in msg
    msg = _err(m, "add_event", event={"id": "MEX_forge.9", "title": "E", "options": [
        {"key": "a", "text": "A", "items": [{"kind": "stabilty", "params": {"amount": 0.1}}]}]})
    assert "Unknown reward preset 'stabilty'" in msg and "stability" in msg
    assert len(m.project.events) == 1
    _ok(m, "add_event", event={"id": "MEX_forge.9", "title": "E", "options": [
        {"key": "a", "text": "A", "items": [{"kind": "stability", "params": {"amount": 0.1}}],
         "trigger": {"items": [{"kind": "at_war", "params": {}}]}}]})


def test_dangling_references_rejected_outside_a_batch():
    m = _model()
    msg = _err(m, "add_focus", id="MEX_x", x=10, y=10, prerequisites=["MEX_y"])
    assert "references missing focus 'MEX_y'" in msg and m.find_focus("MEX_x") is None
    msg = _err(m, "update_focus", id=IND, mutuallyExclusive=["MEX_ghost"])
    assert "mutuallyExclusive references missing focus 'MEX_ghost'" in msg
    assert m.find_focus(IND).mutuallyExclusive == []
    assert "No focus 'MEX_ghost'" in _err(m, "link_prerequisite", target=IND, prereq="MEX_ghost")
    assert "No focus 'MEX_ghost'" in _err(m, "set_mutually_exclusive", a="MEX_ghost", b=IND)
    assert "No focus 'MEX_ghost'" in _err(m, "unlink_prerequisite", target="MEX_ghost", prereq=IND)


def test_batch_forward_references_work_and_dangling_ones_roll_back():
    m = _model()
    r = _ok(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_b1", "x": 20, "y": 0, "title": "B1",
                                     "prerequisites": ["MEX_b2"], "mutuallyExclusive": ["MEX_b3"]}},
        {"op": "add_focus", "args": {"id": "MEX_b2", "x": 20, "y": 1, "title": "B2"}},
        {"op": "add_focus", "args": {"id": "MEX_b3", "x": 22, "y": 0, "title": "B3"}},
    ])
    assert r["count"] == 3 and m.find_focus("MEX_b1").prerequisites == ["MEX_b2"]
    before = project_to_dict(m.project)
    msg = _err(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_c0", "x": 30, "y": 0}},
        {"op": "add_focus", "args": {"id": "MEX_c1", "x": 30, "y": 1}},
        {"op": "add_focus", "args": {"id": "MEX_c2", "x": 30, "y": 2},},
        {"op": "update_focus", "args": {"id": "MEX_c2", "prerequisites": ["MEX_c1", "MEX_nope"]}},
    ])
    assert msg == ("Batch failed: op 3 (update_focus 'MEX_c2') references missing focus "
                   "'MEX_nope'. Nothing was applied.")
    assert project_to_dict(m.project) == before
    assert bd._batch_ctx is None


def test_batch_link_op_needs_both_focuses_to_exist_already():
    m = _model()
    msg = _err(m, "batch", ops=[
        {"op": "link_prerequisite", "args": {"target": "MEX_later", "prereq": NA}},
        {"op": "add_focus", "args": {"id": "MEX_later", "x": 20, "y": 1}},
    ])
    assert "No focus 'MEX_later'" in msg and "add focuses before linking" in msg
    assert m.find_focus("MEX_later") is None


def test_nonstandard_filter_allowed_but_warns_inline():
    m = _model()
    r = _ok(m, "update_focus", id=IND, filters=["FOCUS_FILTER_MEX_CHURCH_AUTHORITY"])
    codes = [i["code"] for i in r["issues"]]
    assert "focus.filter.nonstandard" in codes
    assert all("focusId" not in i for i in r["issues"])
    r = _ok(m, "update_focus", id=IND, filters=["FOCUS_FILTER_POLITICAL"])
    assert "focus.filter.nonstandard" not in [i["code"] for i in r["issues"]]
    assert "not a FOCUS_FILTER_* token" in _err(m, "update_focus", id=IND, filters=["focus_filter_x"])


def test_icon_not_verified_note_when_no_roots():
    m = _model()
    r = _ok(m, "add_focus", id="MEX_i", x=10, y=10, icon="GFX_whatever")
    assert r["note"] == "icon not verified (no icon roots configured)"
    assert "note" not in _ok(m, "update_focus", id="MEX_i", cost=3)


def test_icon_rejected_when_resolver_says_no(monkeypatch):
    m = _model()
    m._icon_exists = lambda: (lambda name: name == "GFX_focus_real")
    monkeypatch.setattr(bd, "_icon_search_provider",
                        lambda: ["GFX_focus_real", "GFX_focus_realpolitik", "GFX_other"])
    msg = _err(m, "add_focus", id="MEX_i", x=10, y=10, icon="GFX_focus_reel")
    assert msg.startswith("Icon 'GFX_focus_reel' does not resolve in your icon sources. "
                          "Verify with search_icons before assigning.")
    assert m.find_focus("MEX_i") is None
    msg = _err(m, "update_focus", id=IND, icon="GFX_focus_rea")
    assert "Closest: GFX_focus_real, GFX_focus_realpolitik" in msg
    r = _ok(m, "update_focus", id=IND, icon="GFX_focus_real")
    assert "note" not in r and m.find_focus(IND).icon == "GFX_focus_real"
    m._icon_exists = lambda: (lambda name: None)      # index not built yet
    assert "not built yet" in _ok(m, "update_focus", id=IND, icon="GFX_x")["note"]


def test_rejected_add_focus_leaves_no_placeholder_behind():
    m = _model()
    for args in ({"x": 10, "y": 10, "completionReward": "raw"},
                 {"x": 10, "y": 10, "prerequisites": ["MEX_nope"]},
                 {"id": "bad id", "x": 10, "y": 10}):
        _err(m, "add_focus", **args)
    assert len(m.project.focuses) == 3 and not m.can_undo()


# ===================== 4. inline issues =====================

def test_write_ops_return_issues_for_touched_focuses_only():
    m = _model()
    m.update_focus(SEC, title="")                    # an unrelated warning elsewhere
    r = _ok(m, "add_focus", id="MEX_new", x=10, y=10)
    assert {"severity", "code", "message"} == set(r["issues"][0])
    codes = {i["code"] for i in r["issues"]}
    assert {"focus.description.empty", "focus.icon.empty"} <= codes
    assert all("MEX_new" in i["message"] for i in r["issues"])
    r = _ok(m, "rename_focus", id="MEX_new", new_id="MEX_renamed")
    assert all("MEX_renamed" in i["message"] for i in r["issues"]) and r["issues"]
    r = _ok(m, "remove_mutex", a=IND, b=SEC)
    assert "focus.title.empty" in {i["code"] for i in r["issues"]}   # SEC was touched


def test_graph_issues_mentioning_touched_focus_are_included():
    m = _model()
    # IND already requires NA; a direct field write makes NA require IND -> cycle.
    r = _ok(m, "update_focus", id=NA, prerequisites=[IND])
    cyc = [i for i in r["issues"] if i["code"] == "focus.graph.cycle"]
    assert cyc and NA in cyc[0]["message"]


def test_batch_returns_deduped_issues_and_summary():
    m = _model()
    r = _ok(m, "batch", ops=[
        {"op": "add_focus", "args": {"id": "MEX_p", "x": 20, "y": 0, "title": "P"}},
        {"op": "add_focus", "args": {"id": "MEX_q", "x": 20, "y": 1, "title": "Q"}},
        {"op": "link_prerequisite", "args": {"target": "MEX_q", "prereq": "MEX_p"}},
        {"op": "update_focus", "args": {"id": "MEX_q", "cost": 5}},
    ])
    assert set(r) == {"results", "count", "issues", "summary"}
    keys = [(i["code"], i["message"]) for i in r["issues"]]
    assert len(keys) == len(set(keys))
    assert r["summary"] == {"errors": 0, "warnings": len(r["issues"])}
    assert any("MEX_p" in i["message"] for i in r["issues"])
    assert any("MEX_q" in i["message"] for i in r["issues"])


_BIG = Path(__file__).resolve().parents[1] / "projects" / "md_beta_mexico_expanded" / \
    "md_beta_mexico_expanded.focusforge.json"


@pytest.mark.skipif(not _BIG.is_file(), reason="139-focus fixture project not present")
def test_inline_issues_stay_cheap_on_a_140_focus_tree():
    """Reads the fixture only. The budget is generous (the spec's 150 ms is a
    reporting threshold, measured separately) so the test isn't flaky."""
    from core.serialization import project_from_dict
    m = _model()
    m.replace_project(project_from_dict(json.loads(_BIG.read_text(encoding="utf-8"))))
    assert len(m.project.focuses) >= 130
    t = time.perf_counter()
    r = _ok(m, "update_focus", id=m.project.focuses[0].id, cost=m.project.focuses[0].cost)
    elapsed_ms = (time.perf_counter() - t) * 1000
    assert isinstance(r["issues"], list)
    assert elapsed_ms < 1000, elapsed_ms


# ===================== 5. bridge-served guide =====================

def test_guide_op_serves_the_guide_with_the_procedure_first():
    text = _ok(_model(), "guide")["text"]
    assert text is guide.MD_FOCUS_GUIDE
    proc = text.index("## Procedure (follow in order)")
    assert proc < text.index("## Cost")
    for must in ("`hello` -> `guide` -> `describe_op`", "`list_focuses` with `prefix`",
                 "dx >= 2", "ONE `batch`", "returns `issues`", "`validate`, then `screenshot`",
                 "NEVER call `save`, `export`, `load_project`", "compact=true"):
        assert must in text, must


def test_guide_filter_paragraph_matches_the_real_md_list():
    text = guide.MD_FOCUS_GUIDE
    assert "FOCUS_FILTER_AIR," not in text and "FOCUS_FILTER_AIR " not in text
    for f in MD_FOCUS_FILTERS:
        assert f[len("FOCUS_FILTER_"):] in text
    assert "FOCUS_FILTER_<TAG>_*" in text and "already defines them" in text


def test_guide_md_preset_kinds_exist_and_are_derived_from_registry():
    kinds = guide.md_specific_reward_kinds()
    known = {p.kind for p in REWARD_PRESETS}
    assert kinds and set(kinds) <= known
    assert {"treasury_change", "relative_party_popularity", "foreign_influence"} <= set(kinds)
    for k in kinds:
        assert k in guide.MD_FOCUS_GUIDE
    assert "rawLines only for shapes no preset expresses" in guide.MD_FOCUS_GUIDE


def test_reference_data_notes_are_the_guide_constants():
    ref = _ok(_model(), "reference_data")
    assert ref["rewardAuthoring"]["note"] == guide.REWARD_AUTHORING_NOTE
    assert ref["aiWeightAuthoring"]["note"] == guide.AI_WEIGHT_AUTHORING_NOTE
    assert ref["costConvention"] == guide.COST_CONVENTION
    assert ref["layoutConvention"] == guide.LAYOUT_CONVENTION
    for s in (guide.REWARD_AUTHORING_NOTE, guide.AI_WEIGHT_AUTHORING_NOTE,
              guide.COST_CONVENTION["note"], guide.LAYOUT_CONVENTION["note"]):
        assert s in guide.MD_FOCUS_GUIDE


def test_mcp_server_serves_the_same_guide():
    pytest.importorskip("mcp")
    from focusforge_mcp import server
    assert server.MD_FOCUS_GUIDE is guide.MD_FOCUS_GUIDE
    assert server.md_focus_guide() is guide.MD_FOCUS_GUIDE
    assert server.author_md_focuses() is guide.MD_FOCUS_GUIDE


# ===================== 6. standard MD filters =====================

_SPEC_FILTERS = """
FOCUS_FILTER_POLITICAL FOCUS_FILTER_ECONOMY FOCUS_FILTER_INDUSTRY FOCUS_FILTER_RESEARCH
FOCUS_FILTER_STABILITY FOCUS_FILTER_WAR_SUPPORT FOCUS_FILTER_FOREIGN_POLICY FOCUS_FILTER_DIPLOMACY
FOCUS_FILTER_INFLUENCE FOCUS_FILTER_INTERNAL_AFFAIRS FOCUS_FILTER_INTERNAL_FACTION
FOCUS_FILTER_INTERNAL_CONSOLIDATION FOCUS_FILTER_MILITARY_LAWS FOCUS_FILTER_ARMY FOCUS_FILTER_NAVY
FOCUS_FILTER_AIRCRAFT FOCUS_FILTER_EQUIPMENT FOCUS_FILTER_MANPOWER FOCUS_FILTER_ANNEXATION
FOCUS_FILTER_RESOURCE FOCUS_FILTER_TRADE FOCUS_FILTER_CORRUPTION FOCUS_FILTER_EXPENDITURE
FOCUS_FILTER_FOREIGN_INVESTMENTS FOCUS_FILTER_INFRASTRUCTURE FOCUS_FILTER_INSURGENCY
FOCUS_FILTER_PROPAGANDA FOCUS_FILTER_ENVIRONMENT FOCUS_FILTER_ADD_BUILDING FOCUS_FILTER_RADICALIZATION
FOCUS_FILTER_SECTARIANISM FOCUS_FILTER_SOCIAL_CONSERVATISM FOCUS_FILTER_COUNTER_DEBUFF
FOCUS_FILTER_POL_REFORM FOCUS_FILTER_ARMY_XP FOCUS_FILTER_NAVY_XP FOCUS_FILTER_AIR_XP
FOCUS_FILTER_MIGRANT_CRISIS FOCUS_FILTER_NATO FOCUS_FILTER_EUROPEAN_UNION FOCUS_FILTER_MERCOSUR
FOCUS_FILTER_UNASUL FOCUS_FILTER_ASEAN FOCUS_FILTER_SPACE
""".split()


def test_standard_filter_list_matches_both_editions_in_order():
    assert MD_FOCUS_FILTERS == _SPEC_FILTERS
    assert "FOCUS_FILTER_AIR" not in MD_FOCUS_FILTERS
    assert "FOCUS_FILTER_MILITARY" not in MD_FOCUS_FILTERS
    assert EDITION_ONLY_FOCUS_FILTERS["main"] == ["FOCUS_FILTER_MILITARY"]


def test_validation_warns_on_nonstandard_filter_with_edition_awareness():
    p = make_sample_project()
    p.focuses[0].filters = ["FOCUS_FILTER_AIR", "FOCUS_FILTER_ARMY"]
    issues = [i for i in validate_project(p) if i.code == "focus.filter.nonstandard"]
    assert len(issues) == 1 and issues[0].severity == "warning"
    assert "FOCUS_FILTER_AIR is not a standard Millennium Dawn filter" in issues[0].message
    assert "filter button will not appear" in issues[0].message
    p.focuses[0].filters = ["FOCUS_FILTER_MILITARY"]
    assert not [i for i in validate_project(p, edition=MAIN) if i.code == "focus.filter.nonstandard"]
    assert [i for i in validate_project(p, edition=BETA) if i.code == "focus.filter.nonstandard"]
    p.focuses[0].filters = ["political"]
    assert "focus.filter.invalid" in {i.code for i in validate_project(p)}


def test_chip_selector_still_accepts_custom_filter_values():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    from ui.chip_selector import ChipSelector
    QApplication.instance() or QApplication([])
    cs = ChipSelector(MD_FOCUS_FILTERS, "add filter…")
    cs._combo.setCurrentText("FOCUS_FILTER_MEX_CHURCH_AUTHORITY")
    cs._on_return()
    assert cs.tokens() == ["FOCUS_FILTER_MEX_CHURCH_AUTHORITY"]


# ===================== 7. compact / filtered reads =====================

def test_reference_data_accepts_loose_section_names():
    from core.bridge_dispatch import resolve_reference_sections
    avail = ["countryTags", "parties", "focusFilters", "iconPresets", "layoutConvention",
             "rewardAuthoring", "aiWeightAuthoring", "costConvention"]
    assert resolve_reference_sections(["filters", "conventions"], avail) == [
        "focusFilters", "layoutConvention", "rewardAuthoring", "aiWeightAuthoring",
        "costConvention"]
    assert resolve_reference_sections(["FocusFilters", "Tags", "icon presets"], avail) == [
        "countryTags", "focusFilters", "iconPresets"] or resolve_reference_sections(
        ["FocusFilters", "Tags", "icon presets"], avail) == ["focusFilters", "countryTags", "iconPresets"]
    assert resolve_reference_sections(["focusfilter"], avail) == ["focusFilters"]
    with pytest.raises(ValueError) as info:
        resolve_reference_sections(["banana"], avail)
    assert "Unknown section(s) 'banana'" in str(info.value) and "Available:" in str(info.value)


def test_reference_data_sections_and_dynamic_tags():
    m = _model()
    full = _ok(m, "reference_data")
    assert set(full["sections_available"]) <= set(full)
    assert not any(re.match(r"^D\d\d$", t["tag"]) for t in full["countryTags"])
    part = _ok(m, "reference_data", sections=["focusFilters", "costConvention"])
    assert set(part) == {"focusFilters", "costConvention", "sections_available"}
    assert part["focusFilters"] == MD_FOCUS_FILTERS
    withd = _ok(m, "reference_data", sections=["countryTags"], include_dynamic_tags=True)
    assert any(t["tag"] == "D01" for t in withd["countryTags"])
    assert len(withd["countryTags"]) - len(full["countryTags"]) == 75
    assert "Unknown section(s) 'nope'" in _err(m, "reference_data", sections=["nope"])


# Reward presets carry long help text, so compact is ~20% of full (the 33 KB the
# spec targets). Condition presets' help text is short, so their ratio is ~28%.
@pytest.mark.parametrize("op,kind,ratio", [
    ("list_reward_presets", "political_power", 0.25),
    ("list_condition_presets", "has_country_flag", 0.30)])
def test_preset_lists_compact_and_single_kind(op, kind, ratio):
    m = _model()
    full = _ok(m, op)
    compact = _ok(m, op, compact=True)
    assert len(json.dumps(compact)) < ratio * len(json.dumps(full))
    assert [c["kind"] for c in compact] == [p["kind"] for p in full]
    row = next(c for c in compact if c["kind"] == kind)
    assert set(row) == {"kind", "group", "label", "params"} and "*" in row["params"]
    one = _ok(m, op, kind=kind)
    assert one["kind"] == kind and one["params"][0]["helpText"]
    assert f"Unknown {'reward' if 'reward' in op else 'condition'} preset 'zzz'" in _err(m, op, kind="zzz")


def test_list_focuses_filters_fields_and_limit():
    m = _model()
    bare = _ok(m, "list_focuses")
    assert isinstance(bare, list) and len(bare) == 3
    r = _ok(m, "list_focuses", prefix="MEX_forge_i")
    assert r == {"focuses": [bare[1]], "total": 1, "returned": 1} or r["focuses"][0]["id"] == IND
    r = _ok(m, "list_focuses", ids=[NA, "nope"], fields=["x", "y"])
    assert r["focuses"] == [{"id": NA, "x": 0, "y": 0}]
    r = _ok(m, "list_focuses", y_min=1, y_max=1, x_min=0)
    assert [f["id"] for f in r["focuses"]] == [SEC]
    r = _ok(m, "list_focuses", limit=2)
    assert (r["total"], r["returned"]) == (3, 2)
    assert "Unknown field(s) 'title2'" in _err(m, "list_focuses", fields=["title2"])
    r = _ok(m, "list_focuses", fields=["title"])
    assert set(r["focuses"][0]) == {"id", "title"}


# ===================== GUI-only ops go through the same normalisation =====================

def test_gui_only_ops_get_alias_and_unknown_arg_treatment():
    pytest.importorskip("PySide6.QtNetwork")
    from ui.agent_bridge import AgentBridge
    b = AgentBridge.__new__(AgentBridge)
    b._model, b._scene, b._token = None, None, "tok"

    def line(op, args):
        return b._handle_line(json.dumps({"op": op, "args": args, "token": "tok"}).encode())

    r = line("search_icons", {"querry": "nuc"})
    assert r["ok"] is False and "Did you mean 'query'?" in r["error"]
    r = line("screenshot", {"whole_tree": True})
    assert r["ok"] is False and r["error"] == "No canvas available (headless)."


# ===================== 8. docs / changelog =====================

def test_docs_and_changelog_mention_the_new_surface():
    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "MCP.md").read_text(encoding="utf-8")
    for must in ("describe_op", "guide", "issues", "compact", "focus_id"):
        assert must in docs, must
    from core.changelog import CHANGELOG
    from core.version import __version__
    import re
    # The newest changelog entry is the running version, dated either
    # "unreleased" (in development) or YYYY-MM-DD (release.py copies it to the site).
    assert CHANGELOG[0]["version"] == __version__
    date = (CHANGELOG[0].get("date") or "").lower()
    assert date == "unreleased" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date), date
