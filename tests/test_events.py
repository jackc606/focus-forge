"""Event model, serialization, export, and validation (the Event editor flow)."""
from __future__ import annotations

from core.exporters import (
    export_event_localisation,
    export_event_picture_sprites,
    export_events,
    export_project_files,
)
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


def _full_event() -> EventData:
    return EventData(
        id="LBA_forge.1",
        title="A Decision",
        description="The cabinet must decide.",
        picture="GFX_report_event_political_meeting",
        eventType="country_event",
        isTriggeredOnly=True,
        hidden=False,
        fireOnlyOnce=True,
        trigger=AvailabilityRule(items=[
            RewardItem(kind="has_country_flag", enabled=True, params={"flag": "lba_ready"})]),
        options=[
            EventOption(
                key="a", text="Accept.",
                items=[
                    RewardItem(kind="political_power", enabled=True, params={"amount": 50}),
                    RewardItem(kind="set_country_flag", enabled=True, params={"flag": "lba_accepted"}),
                ],
                trigger=AvailabilityRule(items=[
                    RewardItem(kind="political_power", enabled=True, params={"amount": 100})]),
                aiChance=80.0,
            ),
            EventOption(key="b", text="Refuse.", effectRawLines=["add_stability = -0.05"]),
        ],
    )


def _project_with_event(event: EventData) -> FocusForgeProject:
    return FocusForgeProject(
        countryTag="LBA", treeId="t", events=[event],
        exportSettings=ExportSettings(focusFileName="lba_focus", localisationPrefix="LBA_forge",
                                      includeEvents=True),
    )


# ----- export -----
def test_export_full_event_block():
    text = export_events(_project_with_event(_full_event()))
    assert "add_namespace = LBA_forge" in text
    assert "country_event = {" in text
    assert "id = LBA_forge.1" in text
    assert "picture = GFX_report_event_political_meeting" in text
    assert "is_triggered_only = yes" in text
    assert "fire_only_once = yes" in text
    assert "trigger = {" in text
    assert "has_country_flag = lba_ready" in text
    assert "option = {" in text
    assert "name = LBA_forge.1.a" in text
    assert "ai_chance = { base = 80 }" in text
    assert "add_political_power = 50" in text
    assert "set_country_flag = lba_accepted" in text
    assert "name = LBA_forge.1.b" in text
    assert "add_stability = -0.05" in text


def test_news_event_uses_news_keyword():
    ev = _full_event()
    ev.eventType = "news_event"
    text = export_events(_project_with_event(ev))
    assert "news_event = {" in text
    assert "country_event = {" not in text


def test_mtth_only_when_not_triggered_only():
    ev = _full_event()
    ev.isTriggeredOnly = False
    ev.meanTimeToHappen = 30
    text = export_events(_project_with_event(ev))
    assert "is_triggered_only = yes" not in text
    assert "mean_time_to_happen = { days = 30 }" in text
    # flip it back on → mtth suppressed
    ev.isTriggeredOnly = True
    text2 = export_events(_project_with_event(ev))
    assert "mean_time_to_happen" not in text2


def test_fire_on_date_forces_schedule_flags_and_trigger():
    ev = _full_event()
    ev.isTriggeredOnly = False
    ev.fireOnlyOnce = False
    ev.meanTimeToHappen = 30
    ev.fireOnDate = "2003.3.20"
    text = export_events(_project_with_event(ev))
    assert "is_triggered_only = yes" in text          # forced by the schedule
    assert "fire_only_once = yes" in text             # forced by the schedule
    assert "mean_time_to_happen" not in text          # suppressed by the schedule
    assert "tag = LBA" in text                        # on_daily fires per-country
    assert "date > 2003.3.20" in text
    # the user's own trigger conditions are kept after the schedule gate
    assert "has_country_flag = lba_ready" in text


def test_fire_on_date_emits_on_actions_file():
    ev = _full_event()
    ev.fireOnDate = "2003.3.20"
    files = {f.relativePath: f.content
             for f in export_project_files(_project_with_event(ev))}
    path = "common/on_actions/LBA_forge_on_actions.txt"
    assert path in files
    body = files[path]
    assert "on_daily = {" in body
    assert "LBA_forge.1" in body


def test_no_on_actions_file_without_dated_events():
    files = {f.relativePath for f in export_project_files(_project_with_event(_full_event()))}
    assert not any("on_actions" in p for p in files)


def test_fire_on_date_round_trips():
    ev = _full_event()
    ev.fireOnDate = "2003.3.20"
    restored = project_from_dict(project_to_dict(_project_with_event(ev)))
    assert restored.events[0].fireOnDate == "2003.3.20"
    # undated events stay undated (and the key is omitted from the dict)
    plain = project_to_dict(_project_with_event(_full_event()))
    assert "fireOnDate" not in plain["events"][0]


def test_fire_on_date_validation():
    ev = _full_event()
    ev.fireOnDate = "March 20, 2003"
    issues = validate_project(_project_with_event(ev))
    assert any(i.code == "event.fireOnDate.invalid" for i in issues)
    ev.fireOnDate = "2003.13.1"                       # month out of range
    issues = validate_project(_project_with_event(ev))
    assert any(i.code == "event.fireOnDate.invalid" for i in issues)
    ev.fireOnDate = "2003.3.20"
    issues = validate_project(_project_with_event(ev))
    assert not any(i.code == "event.fireOnDate.invalid" for i in issues)


def test_event_localisation():
    loc = export_event_localisation(_project_with_event(_full_event()))
    assert 'LBA_forge.1.t:0 "A Decision"' in loc
    assert 'LBA_forge.1.d:0 "The cabinet must decide."' in loc
    assert 'LBA_forge.1.a:0 "Accept."' in loc
    assert 'LBA_forge.1.b:0 "Refuse."' in loc


def test_event_files_present_when_included():
    files = {f.relativePath for f in export_project_files(_project_with_event(_full_event()))}
    assert "events/LBA_forge_events.txt" in files
    assert "localisation/english/LBA_forge_events_l_english.yml" in files


def test_legacy_event_round_trips_and_exports():
    """An event with only the legacy fields (key/text/effectRawLines) still works."""
    legacy = EventData(id="LBA_forge.9", title="Old", description="Legacy.",
                       options=[EventOption(key="a", text="OK", effectRawLines=["add_war_support = 0.05"])])
    # default picture + is_triggered_only fill in
    text = export_events(_project_with_event(legacy))
    assert "picture = GFX_report_event_generic_parliament" in text
    assert "is_triggered_only = yes" in text
    assert "name = LBA_forge.9.a" in text
    assert "add_war_support = 0.05" in text


# ----- custom event picture (imported image) -----
def _custom_pic_event() -> EventData:
    return EventData(id="LBA_forge.3", title="Custom", pictureData="ZmFrZWltYWdl",
                     options=[EventOption(key="a", text="OK")])


def test_custom_picture_uses_generated_sprite():
    text = export_events(_project_with_event(_custom_pic_event()))
    # the picture points at the generated sprite, not a raw GFX preset
    assert "picture = GFX_LBA_forge_3_event_pic" in text


def test_preset_picture_unaffected():
    ev = EventData(id="LBA_forge.4", picture="GFX_report_event_protest",
                   options=[EventOption(key="a")])
    text = export_events(_project_with_event(ev))
    assert "picture = GFX_report_event_protest" in text


def test_event_picture_sprite_gfx_generated():
    gfx = export_event_picture_sprites(_project_with_event(_custom_pic_event()))
    assert gfx is not None
    assert 'name = "GFX_LBA_forge_3_event_pic"' in gfx
    assert 'texturefile = "gfx/event_pictures/LBA_forge_3.dds"' in gfx
    # no custom pictures → no .gfx
    assert export_event_picture_sprites(_project_with_event(_full_event())) is None


def test_event_picture_gfx_file_present_only_with_custom():
    custom = {f.relativePath for f in export_project_files(_project_with_event(_custom_pic_event()))}
    assert "interface/LBA_forge_event_pictures.gfx" in custom
    preset = {f.relativePath for f in export_project_files(_project_with_event(_full_event()))}
    assert not any("event_pictures.gfx" in f for f in preset)


def test_round_trip_preserves_picture_data():
    proj = _project_with_event(_custom_pic_event())
    restored = project_from_dict(project_to_dict(proj))
    assert restored.events[0].pictureData == "ZmFrZWltYWdl"


def test_round_trip_preserves_full_event():
    proj = _project_with_event(_full_event())
    restored = project_from_dict(project_to_dict(proj))
    ev = restored.events[0]
    assert ev.id == "LBA_forge.1"
    assert ev.picture == "GFX_report_event_political_meeting"
    assert ev.fireOnlyOnce is True
    assert ev.trigger.items[0].kind == "has_country_flag"
    opt_a = ev.options[0]
    assert [it.kind for it in opt_a.items] == ["political_power", "set_country_flag"]
    assert opt_a.trigger.items[0].params["amount"] == 100
    assert opt_a.aiChance == 80.0
    assert restored.events[0].options[1].effectRawLines == ["add_stability = -0.05"]


# ----- model CRUD -----
def _model_with_event_reward():
    from ui.project_model import ProjectModel
    proj = FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[FocusNodeData(
            id="LBA_f", title="F", position=FocusPosition(0, 0),
            completionReward=CompletionReward(items=[
                RewardItem(kind="country_event", enabled=True,
                           params={"eventId": "LBA_forge.1", "days": 0})]))],
        events=[_full_event()],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"),
    )
    m = ProjectModel()
    m.replace_project(proj, path=None)
    return m


def test_add_event_dedupes_and_flips_include():
    m = _model_with_event_reward()
    fid = m.add_event(EventData(id="LBA_forge.1", title="Dup"))
    assert fid == "LBA_forge.2"          # bumps the trailing number
    assert m.project.exportSettings.includeEvents is True


def test_update_event_renames_reward_reference():
    m = _model_with_event_reward()
    assert m.event_reference_count("LBA_forge.1") == 1
    final = m.update_event("LBA_forge.1", EventData(id="LBA_forge.7", title="Moved"))
    assert final == "LBA_forge.7"
    assert m.project.focuses[0].completionReward.items[0].params["eventId"] == "LBA_forge.7"


def test_delete_event():
    m = _model_with_event_reward()
    m.delete_event("LBA_forge.1")
    assert m.project.events == []


# ----- validation -----
def _codes(project):
    return {i.code for i in validate_project(project)}


def test_duplicate_option_key_is_error():
    ev = EventData(id="LBA_forge.1", title="T",
                   options=[EventOption(key="a", text="x"), EventOption(key="a", text="y")])
    assert "event.option.key.duplicate" in _codes(_project_with_event(ev))


def test_no_options_is_warning_unless_hidden():
    ev = EventData(id="LBA_forge.1", title="T", options=[])
    assert "event.options.empty" in _codes(_project_with_event(ev))
    ev.hidden = True
    assert "event.options.empty" not in _codes(_project_with_event(ev))


def test_full_event_has_no_event_errors():
    codes = _codes(_project_with_event(_full_event()))
    assert not any(c.startswith("event.option") for c in codes)
