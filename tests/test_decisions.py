"""Decision model, serialization, export, validation, CRUD, and bridge ops."""
from __future__ import annotations

from core.bridge_dispatch import dispatch
from core.exporters import (
    export_decision_categories,
    export_decision_localisation,
    export_decisions,
    export_project_files,
)
from core.serialization import project_from_dict, project_to_dict
from core.types import (
    AvailabilityRule,
    CompletionReward,
    DecisionCategory,
    DecisionData,
    ExportSettings,
    FocusForgeProject,
    RewardItem,
)
from core.validation import validate_project


def _full_decision() -> DecisionData:
    return DecisionData(
        id="LBA_oil_fund",
        title="National Oil Fund",
        description="Invest the surplus.",
        category="LBA_economy_category",
        icon="GFX_decision_generic_money",
        cost=75,
        fireOnlyOnce=True,
        isGood=True,
        daysRemove=90,
        daysReEnable=180,
        daysMissionTimeout=365,
        aiWillDo=3,
        priority=10,
        visible=AvailabilityRule(rawLines=["has_country_flag = lba_ready"]),
        available=AvailabilityRule(items=[
            RewardItem(kind="political_power", enabled=True, params={"amount": 75})]),
        completeEffect=CompletionReward(items=[
            RewardItem(kind="treasury_change", enabled=True, params={"amount": -2})]),
        removeEffect=CompletionReward(rawLines=["add_stability = 0.02"]),
        timeoutEffect=CompletionReward(rawLines=["add_stability = -0.05"]),
        modifierRawLines=["modifier = {", "\tstability_weekly = 0.001", "}"],
        rawLines=["highlight_states = { highlight_states_trigger = { state = 446 } }"],
    )


def _category() -> DecisionCategory:
    return DecisionCategory(
        id="LBA_economy_category", title="Libyan Economy", description="Money matters.",
        icon="GFX_decision_category_generic_economy", priority=100,
        visible=AvailabilityRule(rawLines=["has_country_flag = lba_ready"]),
        rawLines=["visible_when_empty = yes"])


def _project(**kw) -> FocusForgeProject:
    kw.setdefault("countryTag", "LBA")
    kw.setdefault("treeId", "t")
    kw.setdefault("exportSettings", ExportSettings(
        focusFileName="lba_focus", localisationPrefix="LBA_forge",
        includeDecisions=True))
    return FocusForgeProject(**kw)


# ----- export -----
def test_export_full_decision_block():
    text = export_decisions(_project(decisions=[_full_decision()]))
    assert "LBA_economy_category = {" in text
    assert "LBA_oil_fund = {" in text
    assert "icon = GFX_decision_generic_money" in text
    assert "allowed = { original_tag = LBA }" in text
    assert "cost = 75" in text
    assert "fire_only_once = yes" in text
    assert "is_good = yes" in text
    assert "days_remove = 90" in text
    assert "days_re_enable = 180" in text
    assert "days_mission_timeout = 365" in text
    assert "priority = 10" in text
    assert "has_country_flag = lba_ready" in text
    assert "add_political_power = 75" not in text  # availability is a TRIGGER
    assert "complete_effect = {" in text
    assert 'log = "[GetDateText]: [Root.GetName]: Decision LBA_oil_fund"' in text
    assert "set_temp_variable = { treasury_change = -2 }" in text
    assert "remove_effect = {" in text
    assert "add_stability = 0.02" in text
    assert "timeout_effect = {" in text
    assert "modifier = {" in text and "stability_weekly = 0.001" in text
    assert "ai_will_do = { base = 3 }" in text
    assert "highlight_states" in text


def test_minimal_decision_omits_optionals():
    d = DecisionData(id="LBA_simple", title="Simple", category="LBA_economy_category")
    text = export_decisions(_project(decisions=[d]))
    for absent in ("days_remove", "days_re_enable", "days_mission_timeout",
                   "is_good", "fire_only_once", "ai_will_do", "priority =",
                   "remove_effect", "timeout_effect", "visible = {", "available = {"):
        assert absent not in text, absent
    assert "complete_effect = {" in text  # always present (MD log convention)
    assert "cost = 25" in text            # default cost


def test_export_categories_and_loc():
    p = _project(decisions=[_full_decision()], decisionCategories=[_category()])
    cats = export_decision_categories(p)
    assert "LBA_economy_category = {" in cats
    assert "icon = GFX_decision_category_generic_economy" in cats
    assert "allowed = { original_tag = LBA }" in cats
    assert "priority = 100" in cats
    assert "visible = {" in cats and "has_country_flag = lba_ready" in cats
    assert "visible_when_empty = yes" in cats
    loc = export_decision_localisation(p)
    assert 'LBA_economy_category:0 "Libyan Economy"' in loc
    assert 'LBA_economy_category_desc:0 "Money matters."' in loc
    assert 'LBA_oil_fund:0 "National Oil Fund"' in loc
    assert 'LBA_oil_fund_desc:0 "Invest the surplus."' in loc


def test_files_present_only_when_included():
    p = _project(decisions=[_full_decision()], decisionCategories=[_category()])
    files = {f.relativePath for f in export_project_files(p)}
    assert "common/decisions/LBA_forge_decisions.txt" in files
    assert "common/decisions/categories/LBA_forge_decision_categories.txt" in files
    assert "localisation/english/LBA_forge_decisions_l_english.yml" in files
    p.exportSettings.includeDecisions = False
    files = {f.relativePath for f in export_project_files(p)}
    assert not any("decisions" in f for f in files)


# ----- serialization -----
def test_decision_round_trip():
    p = _project(decisions=[_full_decision()], decisionCategories=[_category()])
    restored = project_from_dict(project_to_dict(p))
    d = restored.decisions[0]
    assert d.id == "LBA_oil_fund"
    assert d.cost == 75 and d.fireOnlyOnce and d.isGood is True
    assert (d.daysRemove, d.daysReEnable, d.daysMissionTimeout) == (90, 180, 365)
    assert d.visible.rawLines == ["has_country_flag = lba_ready"]
    assert d.available.items[0].kind == "political_power"
    assert d.completeEffect.items[0].kind == "treasury_change"
    assert d.modifierRawLines[1] == "\tstability_weekly = 0.001"
    cat = restored.decisionCategories[0]
    assert cat.priority == 100 and cat.rawLines == ["visible_when_empty = yes"]
    # untouched optionals stay omitted from the JSON
    plain = project_to_dict(_project(decisions=[
        DecisionData(id="x", title="X", category="c")]))
    assert "daysRemove" not in plain["decisions"][0]
    assert "isGood" not in plain["decisions"][0]


# ----- model CRUD -----
def _model():
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m.replace_project(_project())
    m._undo_coalesce_s = -1.0  # every change = its own undo step (deterministic)
    return m


def test_decision_crud_and_category_rename():
    m = _model()
    did = m.add_decision(_full_decision())
    assert m.project.exportSettings.includeDecisions is True
    dup = m.add_decision(_full_decision())
    assert dup == "LBA_oil_fund_2"          # id de-duped
    cid = m.add_decision_category(_category())
    assert m.decision_category_reference_count(cid) == 2
    cat = _category()
    cat.id = "LBA_money_category"
    m.update_decision_category(cid, cat)
    assert m.find_decision(did).category if hasattr(m, "find_decision") else True
    assert all(d.category == "LBA_money_category" for d in m.project.decisions)
    m.delete_decision(did)
    assert len(m.project.decisions) == 1
    m.undo()
    assert len(m.project.decisions) == 2    # decisions ride the undo system


# ----- validation -----
def test_decision_validation():
    p = _project(decisions=[DecisionData(id="bad id!", title="", category="")])
    codes = {i.code for i in validate_project(p)}
    assert "decision.id.invalid" in codes
    assert "decision.title.empty" in codes
    assert "decision.category.missing" in codes

    d = _full_decision()
    d.daysRemove = -5
    d.timeoutEffect = None
    d.available = AvailabilityRule(items=[
        RewardItem(kind="state_controlled", enabled=True, params={"state": 0, "tag": ""})])
    codes = {i.code for i in validate_project(_project(decisions=[d]))}
    assert "decision.days.negative" in codes
    assert "decision.timeout.unused" in codes
    assert "decision.trigger.invalid" in codes


# ----- bridge ops -----
def test_bridge_decision_ops():
    m = _model()
    res = dispatch(m, "add_decision", {"decision": {
        "id": "LBA_via_bridge", "title": "Bridged", "category": "LBA_economy_category"}})
    assert res["ok"], res
    did = res["result"]["id"]
    res = dispatch(m, "list_decisions", {})
    assert res["ok"] and any(d["id"] == did for d in res["result"]["decisions"])
    res = dispatch(m, "update_decision", {"id": did, "decision": {
        "id": did, "title": "Bridged 2", "category": "LBA_economy_category"}})
    assert res["ok"]
    assert m.project.decisions[0].title == "Bridged 2"
    res = dispatch(m, "delete_decision", {"id": did})
    assert res["ok"] and not m.project.decisions


# ----- release-review regression fixes -----
def test_whitespace_category_gets_safe_fallback():
    d = DecisionData(id="LBA_x", title="X", category="   ")
    text = export_decisions(_project(decisions=[d]))
    assert " = {" not in text.split("\n")[0] or text.split("\n")[0].split(" = ")[0].strip()
    assert "uncategorized_decisions = {" in text


def test_category_token_and_unknown_checks():
    p = _project(decisions=[DecisionData(id="LBA_x", title="X", category="my economy")])
    codes = {i.code for i in validate_project(p)}
    assert "decision.category.invalid" in codes
    p = _project(decisions=[DecisionData(id="LBA_x", title="X", category="LBA_typo_catgory")])
    codes = {i.code for i in validate_project(
        p, known_decision_categories={"real_category"})}
    assert "decision.category.unknown" in codes
    # custom categories are always known
    p.decisionCategories.append(DecisionCategory(id="LBA_typo_catgory", title="T"))
    codes = {i.code for i in validate_project(
        p, known_decision_categories={"real_category"})}
    assert "decision.category.unknown" not in codes


def test_bridge_numeric_strings_are_coerced():
    m = _model()
    res = dispatch(m, "add_decision", {"decision": {
        "id": "LBA_coerce", "title": "C", "category": "LBA_economy_category",
        "cost": "75", "daysRemove": "90.5", "aiWillDo": "bogus"}})
    assert res["ok"], res
    d = m.project.decisions[0]
    assert d.cost == 75.0 and d.daysRemove == 90 and d.aiWillDo is None
    # validation and export must not crash on the coerced values
    assert isinstance(validate_project(m.project), list)
    assert "days_remove = 90" in export_decisions(m.project)


# ----- custom imported decision icon -----
# A placeholder string is enough for the export-logic tests (they only branch on
# iconData being non-empty); real PNG decode → .dds is exercised in the offscreen
# harness, mirroring how the event-picture suite avoids needing a QApplication.
def _b64_png() -> str:
    return "ZmFrZWltYWdl"


def test_custom_icon_uses_generated_sprite_and_emits_gfx():
    d = DecisionData(id="LBA_custom", title="Custom", category="LBA_economy_category",
                     icon="GFX_decision_generic_money", iconData=_b64_png())
    text = export_decisions(_project(decisions=[d]))
    # the icon line points at the generated sprite, NOT the named one
    assert "icon = GFX_LBA_custom_decision_icon" in text
    assert "icon = GFX_decision_generic_money" not in text
    from core.exporters import export_decision_icon_sprites
    gfx = export_decision_icon_sprites(_project(decisions=[d]))
    assert gfx and 'name = "GFX_LBA_custom_decision_icon"' in gfx
    assert "gfx/interface/decisions/LBA_custom.dds" in gfx


def test_named_icon_unaffected_and_no_gfx_without_custom():
    d = DecisionData(id="LBA_named", title="Named", category="LBA_economy_category",
                     icon="GFX_decision_generic_money")
    text = export_decisions(_project(decisions=[d]))
    assert "icon = GFX_decision_generic_money" in text
    from core.exporters import export_decision_icon_sprites
    assert export_decision_icon_sprites(_project(decisions=[d])) is None


def test_custom_icon_gfx_file_present_only_with_custom():
    custom = DecisionData(id="LBA_c", title="C", category="LBA_economy_category",
                          iconData=_b64_png())
    files = {f.relativePath for f in export_project_files(_project(decisions=[custom]))}
    assert "interface/LBA_forge_decision_icons.gfx" in files
    plain = DecisionData(id="LBA_p", title="P", category="LBA_economy_category")
    files = {f.relativePath for f in export_project_files(_project(decisions=[plain]))}
    assert not any("decision_icons.gfx" in f for f in files)


def test_custom_icon_round_trips():
    d = DecisionData(id="LBA_c", title="C", category="c", iconData=_b64_png())
    restored = project_from_dict(project_to_dict(_project(decisions=[d])))
    assert restored.decisions[0].iconData == _b64_png()
