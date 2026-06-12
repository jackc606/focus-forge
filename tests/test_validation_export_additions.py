"""Validation/export additions: availability-item validation wiring, reward
reference checks, option-key format, icon resolution, layout warnings, loc
newline escaping, per-focus ai_will_do, and bypass blocks."""
from __future__ import annotations

from core.exporters import export_event_localisation, export_focus_tree
from core.serialization import project_from_dict, project_to_dict
from core.types import (
    AvailabilityRule,
    CompletionReward,
    EventData,
    EventOption,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    RewardItem,
)
from core.validation import validate_project


def _focus(fid="LBA_a", x=0, y=0, **kw) -> FocusNodeData:
    kw.setdefault("title", "T")
    kw.setdefault("description", "D")
    kw.setdefault("icon", "GFX_goal_generic_construct_civ_factory")
    return FocusNodeData(id=fid, position=FocusPosition(x=x, y=y), **kw)


def _project(*focuses, **kw) -> FocusForgeProject:
    kw.setdefault("countryTag", "LBA")
    kw.setdefault("treeId", "lba_tree")
    kw.setdefault("exportSettings", ExportSettings(
        focusFileName="lba_focus", localisationPrefix="LBA_forge"))
    return FocusForgeProject(focuses=list(focuses), **kw)


def _codes(project, **kw) -> set:
    return {i.code for i in validate_project(project, **kw)}


# ----- availability items are validated now -----
def test_invalid_availability_item_is_flagged():
    f = _focus(available=AvailabilityRule(items=[
        RewardItem(kind="state_controlled", enabled=True, params={"state": 0, "tag": ""})]))
    assert "focus.available.invalid" in _codes(_project(f))


def test_bypass_items_are_validated_too():
    f = _focus(bypass=AvailabilityRule(items=[
        RewardItem(kind="has_tech", enabled=True, params={"tech": ""})]))
    assert "focus.available.invalid" in _codes(_project(f))


# ----- reward references -----
def test_missing_project_event_reference_is_error():
    f = _focus(completionReward=CompletionReward(items=[
        RewardItem(kind="country_event", enabled=True,
                   params={"eventId": "LBA_forge.99", "days": 0})]))
    assert "focus.reward.event.missing" in _codes(_project(f))


def test_md_event_reference_is_not_flagged():
    f = _focus(completionReward=CompletionReward(items=[
        RewardItem(kind="country_event", enabled=True,
                   params={"eventId": "generic.1", "days": 0})]))
    codes = _codes(_project(f))
    assert "focus.reward.event.missing" not in codes


def test_unexported_event_reference_is_warning():
    ev = EventData(id="LBA_forge.1", title="E", options=[EventOption(key="a", text="ok")])
    f = _focus(completionReward=CompletionReward(items=[
        RewardItem(kind="country_event", enabled=True,
                   params={"eventId": "LBA_forge.1", "days": 0})]))
    p = _project(f, events=[ev])
    p.exportSettings.includeEvents = False
    assert "focus.reward.event.unexported" in _codes(p)


def test_missing_project_idea_reference_is_warning():
    # WARNING, not error: MD itself ships tag-prefixed ideas, so this can be a
    # legitimate base-mod reference — it must never block export.
    f = _focus(completionReward=CompletionReward(items=[
        RewardItem(kind="add_idea", enabled=True, params={"idea": "LBA_ghost_idea"})]))
    issues = validate_project(_project(f))
    hits = [i for i in issues if i.code == "focus.reward.idea.missing"]
    assert hits and all(i.severity == "warning" for i in hits)


# ----- event option keys -----
def test_bad_option_key_is_error():
    ev = EventData(id="LBA_forge.1", title="E",
                   options=[EventOption(key="bad key!", text="x")])
    p = _project(_focus(), events=[ev])
    p.exportSettings.includeEvents = True
    assert "event.option.key.invalid" in _codes(p)


# ----- icon resolution -----
def test_unresolved_icon_warns_only_with_resolver():
    f = _focus()
    assert "focus.icon.unresolved" not in _codes(_project(f))  # no resolver
    assert "focus.icon.unresolved" in _codes(_project(f), icon_exists=lambda n: False)
    assert "focus.icon.unresolved" not in _codes(_project(f), icon_exists=lambda n: True)
    assert "focus.icon.unresolved" not in _codes(_project(f), icon_exists=lambda n: None)


# ----- layout warnings -----
def test_focus_above_its_prerequisite_warns():
    a = _focus("LBA_a", 0, 2)
    b = _focus("LBA_b", 0, 1, prerequisites=["LBA_a"])  # child ABOVE parent
    assert "focus.position.above_prereq" in _codes(_project(a, b))


def test_one_sided_mutex_warns():
    a = _focus("LBA_a", 0, 0, mutuallyExclusive=["LBA_b"])
    b = _focus("LBA_b", 1, 0)  # no back-reference
    assert "focus.mutual.onesided" in _codes(_project(a, b))


# ----- loc escaping -----
def test_multiline_description_escapes_newlines():
    ev = EventData(id="LBA_forge.1", title="E", description="line one\nline two",
                   options=[EventOption(key="a", text="ok")])
    loc = export_event_localisation(_project(_focus(), events=[ev]))
    assert 'line one\\nline two' in loc
    assert "line one\nline two" not in loc


# ----- ai_will_do -----
def test_ai_will_do_default_and_custom():
    tree = export_focus_tree(_project(_focus()))
    assert "base = 10" in tree
    tree = export_focus_tree(_project(_focus(aiWillDo=50)))
    assert "base = 50" in tree
    # default (None) is omitted from the saved file entirely
    plain = project_to_dict(_project(_focus()))
    assert "aiWillDo" not in plain["focuses"][0]


# ----- bypass -----
def test_bypass_block_exports_and_round_trips():
    f = _focus(bypass=AvailabilityRule(
        items=[RewardItem(kind="nato_member", enabled=True, params={})],
        rawLines=["has_war = no"]))
    p = _project(f)
    tree = export_focus_tree(p)
    assert "bypass = {" in tree
    assert "has_idea = NATO_member" in tree
    assert "has_war = no" in tree
    restored = project_from_dict(project_to_dict(p))
    rb = restored.focuses[0].bypass
    assert rb is not None and rb.items[0].kind == "nato_member"
    assert rb.rawLines == ["has_war = no"]
    # no bypass → no block, and the key is omitted from the dict
    tree2 = export_focus_tree(_project(_focus()))
    assert "bypass" not in tree2
    assert "bypass" not in project_to_dict(_project(_focus()))["focuses"][0]
