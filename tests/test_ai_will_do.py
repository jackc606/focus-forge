"""ai_will_do authoring: base + conditional modifiers, export, import round-trip,
serialization, bridge and validation."""
from __future__ import annotations

from core.bridge_dispatch import dispatch
from core.exporters import ai_will_do_lines, export_focus_tree
from core.focus_import import _parse_ai_will_do, _parse_focus
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.types import AiModifier, AvailabilityRule, FocusNodeData, RewardItem
from core.validation import validate_project
from ui.project_model import ProjectModel


def _mods():
    return [
        AiModifier(factor=0, trigger=AvailabilityRule(
            items=[RewardItem(kind="has_country_flag", params={"flag": "MEX_gov_pri"})])),
        AiModifier(factor=5, trigger=AvailabilityRule(rawLines=["date < 2003.1.1"])),
        AiModifier(add=2, trigger=AvailabilityRule(items=[RewardItem(kind="at_war", params={})])),
    ]


# ----- export -----------------------------------------------------------------

def test_default_block_is_unchanged_without_modifiers():
    f = FocusNodeData(id="X")
    assert ai_will_do_lines(f) == ["ai_will_do = {", "\tbase = 10", "}"]
    assert ai_will_do_lines(FocusNodeData(id="X", aiWillDo=3)) == ["ai_will_do = {", "\tbase = 3", "}"]


def test_modifiers_export_factor_add_and_triggers():
    f = FocusNodeData(id="X", aiWillDo=1, aiModifiers=_mods())
    text = "\n".join(ai_will_do_lines(f))
    assert text == (
        "ai_will_do = {\n"
        "\tbase = 1\n"
        "\tmodifier = {\n\t\tfactor = 0\n\t\thas_country_flag = MEX_gov_pri\n\t}\n"
        "\tmodifier = {\n\t\tfactor = 5\n\t\tdate < 2003.1.1\n\t}\n"
        "\tmodifier = {\n\t\tadd = 2\n\t\thas_war = yes\n\t}\n"
        "}")


def test_empty_modifier_is_skipped():
    f = FocusNodeData(id="X", aiModifiers=[AiModifier()])
    assert "modifier" not in "\n".join(ai_will_do_lines(f))


def test_focus_tree_export_embeds_block():
    project = make_sample_project()
    project.focuses[0].aiModifiers = [AiModifier(factor=0, trigger=AvailabilityRule(rawLines=["has_war = yes"]))]
    tree = export_focus_tree(project)
    assert "\t\tai_will_do = {\n\t\t\tbase = 10\n\t\t\tmodifier = {\n\t\t\t\tfactor = 0\n\t\t\t\thas_war = yes\n\t\t\t}\n\t\t}" in tree


# ----- serialization ------------------------------------------------------------

def test_round_trip_and_omitted_when_absent():
    project = make_sample_project()
    plain = project_to_dict(project)
    assert "aiModifiers" not in plain["focuses"][0]          # untouched projects unchanged
    project.focuses[0].aiModifiers = _mods()
    plain = project_to_dict(project)
    mods = plain["focuses"][0]["aiModifiers"]
    assert len(mods) == 3 and "add" not in mods[0] and mods[2] == {
        "add": 2, "trigger": {"items": [{"kind": "at_war", "params": {}}]}}
    back = project_from_dict(plain)
    assert [m.factor for m in back.focuses[0].aiModifiers] == [0, 5, None]
    assert back.focuses[0].aiModifiers[1].trigger.rawLines == ["date < 2003.1.1"]
    # corrupt numbers heal to None instead of crashing the load
    plain["focuses"][0]["aiModifiers"][0]["factor"] = "bogus"
    assert project_from_dict(plain).focuses[0].aiModifiers[0].factor is None


# ----- import round trip --------------------------------------------------------

_MD_BLOCK = """
\t\tid = USA_focus_limited_indust_expansion
\t\ticon = factory_planning
\t\tx = 2
\t\ty = 1
\t\tcost = 3.6
\t\tai_will_do = {
\t\t\tbase = 100
\t\t\tmodifier = {
\t\t\t\tfactor = 5
\t\t\t\tdate < 2000.6.1
\t\t\t}
\t\t\tmodifier = {
\t\t\t\tfactor = 0
\t\t\t\thas_active_mission = bankruptcy_incoming_collapse
\t\t\t}
\t\t\tmodifier = {
\t\t\t\tadd = 10
\t\t\t\tOR = {
\t\t\t\t\thas_country_flag = a
\t\t\t\t\thas_country_flag = b
\t\t\t\t}
\t\t\t}
\t\t}
"""


def test_import_parses_base_and_modifiers_keeping_comparison_lines():
    pf = _parse_focus(_MD_BLOCK)
    assert pf.ai_base == 100
    assert pf.ai_mods[0] == (5, None, ["date < 2000.6.1"])
    assert pf.ai_mods[1] == (0, None, ["has_active_mission = bankruptcy_incoming_collapse"])
    factor, add, trig = pf.ai_mods[2]
    assert (factor, add) == (None, 10)
    assert trig == ["OR = {", "has_country_flag = a", "has_country_flag = b", "}"]


def test_import_bare_factor_is_base_and_default_10_is_none():
    assert _parse_ai_will_do("factor = 1") == (1, [])
    assert _parse_ai_will_do("base = 10") == (10, [])
    pf = _parse_focus("\t\tid = A\n\t\tai_will_do = { base = 10 }\n")
    assert pf.ai_base == 10


def test_import_export_round_trip_is_stable():
    """Re-exporting an imported block reproduces its script (modulo indentation)."""
    from core.focus_import import _raw_lines
    pf = _parse_focus(_MD_BLOCK)
    focus = FocusNodeData(
        id=pf.id, aiWillDo=pf.ai_base,
        aiModifiers=[AiModifier(factor=f, add=a, trigger=AvailabilityRule(rawLines=t) if t else None)
                     for f, a, t in pf.ai_mods])
    out = [ln.strip() for ln in ai_will_do_lines(focus)]
    src = _raw_lines(_MD_BLOCK.split("ai_will_do = {", 1)[1].rsplit("}", 1)[0])
    assert out == ["ai_will_do = {"] + src + ["}"]


# ----- bridge -------------------------------------------------------------------

def test_bridge_sets_and_clears_ai_fields():
    model = ProjectModel()
    model.replace_project(make_sample_project())
    fid = model.project.focuses[0].id
    r = dispatch(model, "update_focus", {
        "id": fid, "aiWillDo": 2,
        "aiModifiers": [{"factor": 0, "trigger": {"items": [{"kind": "at_war", "params": {}}]}},
                        {"add": "3", "trigger": {"rawLines": ["date > 2010.1.1"]}}]})
    assert r["ok"], r
    assert r["result"]["aiWillDo"] == 2 and r["result"]["aiModifierCount"] == 2
    f = model.find_focus(fid)
    assert f.aiModifiers[1].add == 3.0 and f.aiModifiers[1].trigger.rawLines == ["date > 2010.1.1"]
    full = dispatch(model, "get_focus", {"id": fid})["result"]
    assert full["aiModifiers"][0]["factor"] == 0
    bad = dispatch(model, "update_focus", {"id": fid, "aiModifiers": [{"factor": "x"}]})
    assert not bad["ok"] and "factor" in bad["error"]
    bad2 = dispatch(model, "update_focus", {"id": fid, "aiWillDo": "many"})
    assert not bad2["ok"]
    r = dispatch(model, "update_focus", {"id": fid, "aiWillDo": None, "aiModifiers": []})
    assert r["ok"] and model.find_focus(fid).aiModifiers is None and model.find_focus(fid).aiWillDo is None


def test_reference_data_documents_ai_weights():
    model = ProjectModel()
    model.replace_project(make_sample_project())
    rd = dispatch(model, "reference_data", {})["result"]
    assert "aiModifiers" in rd["aiWeightAuthoring"]["note"]


# ----- validation ---------------------------------------------------------------

def test_validation_ai_weight_warnings():
    project = make_sample_project()
    f = project.focuses[0]
    f.aiWillDo = -1
    f.aiModifiers = [
        AiModifier(),                                                     # no weight
        AiModifier(factor=2),                                             # unconditional
        AiModifier(factor=-3, trigger=AvailabilityRule(rawLines=["has_war = yes"])),  # negative
        AiModifier(factor=0, trigger=AvailabilityRule(rawLines=["OR = {"])),          # unbalanced
        AiModifier(factor=0, trigger=AvailabilityRule(items=[RewardItem(kind="has_country_flag", params={"flag": ""})])),
    ]
    issues = validate_project(project)
    codes = [i.code for i in issues if i.focusId == f.id]
    assert "focus.ai.negativeBase" in codes
    assert "focus.ai.modifier.noWeight" in codes
    assert "focus.ai.modifier.unconditional" in codes
    assert "focus.ai.modifier.negative" in codes
    assert "focus.ai.script" in codes                # raw lint reaches modifier triggers
    assert "focus.ai.modifier.invalid" in codes      # empty required param
    # a sane focus produces none of these
    f.aiWillDo = 1
    f.aiModifiers = [AiModifier(factor=0, trigger=AvailabilityRule(items=[RewardItem(kind="at_war", params={})]))]
    assert not [i for i in validate_project(project) if i.code.startswith("focus.ai")]
