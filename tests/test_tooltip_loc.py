"""Custom tooltips carry their text: the ``custom_tooltip`` / ``hydroelectric_dam``
presets take the sentence the player reads, the export writes it into the
owning content type's localisation, and validation / the smoke check warn about
keys that would show raw in-game."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.bridge_dispatch import dispatch
from core.export_check import smoke_check
from core.exporters import (
    export_decision_localisation,
    export_event_localisation,
    export_focus_localisation,
    export_project_files,
)
from core.reward_presets import (
    build_reward_item_lines,
    get_reward_preset,
    iter_reward_item_sites,
    tooltip_texts_by_owner,
)
from core.sample_project import make_sample_project
from core.types import (
    CompletionReward,
    DecisionData,
    EventData,
    EventOption,
    ExportedFile,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    RewardItem,
)
from core.validation import validate_project

KEY = "LBA_court_plant_tt"


def _tt(key=KEY, text="", kind="custom_tooltip", **extra) -> RewardItem:
    if kind == "hydroelectric_dam":
        params = {"state": 1, "production": 0.8, "tooltip": key, "tooltipText": text}
    else:
        params = {"tooltipId": key, "text": text}
    params.update(extra)
    return RewardItem(kind=kind, params=params)


def _project(focus_items=(), option_items=(), decision_items=()) -> FocusForgeProject:
    return FocusForgeProject(
        treeId="t", countryTag="LBA", projectName="p",
        focuses=[FocusNodeData(id="LBA_a", title="A", description="d", icon="GFX_goal_generic",
                               position=FocusPosition(0, 0),
                               completionReward=CompletionReward(items=list(focus_items)))],
        events=[EventData(id="LBA_forge.1", title="T", description="D",
                          options=[EventOption(key="a", text="Ok", items=list(option_items))])],
        decisions=[DecisionData(id="LBA_dec", title="Dec", category="LBA_cat",
                                completeEffect=CompletionReward(items=list(decision_items)))],
        exportSettings=ExportSettings(focusFileName="lba_focus", localisationPrefix="LBA_forge",
                                      includeEvents=True, includeDecisions=True))


def _codes(project, **kw) -> set:
    return {i.code for i in validate_project(project, **kw)}


# ----- preset -----------------------------------------------------------------------

def test_presets_declare_text_params_and_builders_are_unchanged():
    assert [p.key for p in get_reward_preset("custom_tooltip").params] == ["tooltipId", "text"]
    text = next(p for p in get_reward_preset("custom_tooltip").params if p.key == "text")
    assert text.type == "string" and not text.required and text.helpText
    assert [p.key for p in get_reward_preset("hydroelectric_dam").params][-2:] == ["tooltip", "tooltipText"]
    assert build_reward_item_lines(_tt(text="Anything")) == [f"custom_effect_tooltip = {KEY}"]
    hydro = build_reward_item_lines(_tt(kind="hydroelectric_dam", text="The dam comes online."))
    assert hydro[0] == f"custom_effect_tooltip = {KEY}" and "tooltipText" not in "\n".join(hydro)


def test_item_sites_cover_focus_event_and_decision():
    p = _project([_tt()], [_tt("E_tt")], [_tt("D_tt")])
    sites = list(iter_reward_item_sites(p))
    assert [(s.owner, s.owner_id, s.focus_id) for s in sites] == [
        ("focus", "LBA_a", "LBA_a"), ("event", "LBA_forge.1", None), ("decision", "LBA_dec", None)]
    assert sites[1].label == "event LBA_forge.1 option a effect 1"
    assert sites[2].label == "decision LBA_dec complete effect 1"


def test_reward_card_shows_the_text_field():
    from PySide6.QtWidgets import QApplication, QLineEdit
    from ui.item_card import PresetItemCard
    from ui.param_widgets import make_param_widget
    QApplication.instance() or QApplication([])
    item = _tt()
    card = PresetItemCard(0, item, get_reward_preset("custom_tooltip"),
                          on_change=lambda *a: None, on_delete=lambda *a: None,
                          build_lines=build_reward_item_lines, empty_text="",
                          make_widget=lambda p, c, s: make_param_widget(p, c, s))
    fields = [w for w in card.findChildren(QLineEdit) if "player reads" in w.placeholderText()]
    assert len(fields) == 1


# ----- export -----------------------------------------------------------------------

def test_export_writes_text_into_the_owning_loc_file():
    p = _project([_tt(text="Foreign plants take notice.")],
                 [_tt("LBA_evt_tt", "The cabinet agrees.")],
                 [_tt("LBA_dec_tt", "Funds are released.")])
    assert export_focus_localisation(p).endswith(
        ' LBA_a_desc:0 "d"\n LBA_court_plant_tt:0 "Foreign plants take notice."\n')
    assert export_event_localisation(p).endswith(
        ' LBA_forge.1.a:0 "Ok"\n LBA_evt_tt:0 "The cabinet agrees."\n')
    assert export_decision_localisation(p).endswith(
        ' LBA_dec:0 "Dec"\n LBA_dec_tt:0 "Funds are released."\n')
    # Nothing leaks across files.
    assert "LBA_evt_tt" not in export_focus_localisation(p)
    assert KEY not in export_event_localisation(p)


def test_export_hydro_tooltip_text_and_sorted_keys():
    p = _project([_tt("LBA_z_tt", "Z"), _tt("LBA_b_tt", "B", kind="hydroelectric_dam")])
    assert export_focus_localisation(p).endswith(' LBA_b_tt:0 "B"\n LBA_z_tt:0 "Z"\n')


def test_export_dedupes_first_text_wins_and_skips_empty():
    p = _project([_tt(text=""), _tt(text="First"), _tt(text="Second")], [_tt(text="Third")])
    texts = tooltip_texts_by_owner(p)
    assert texts == {"focus": {KEY: "First"}, "event": {}, "decision": {}}
    assert export_focus_localisation(p).count(KEY) == 1
    assert KEY not in export_event_localisation(p)


def test_export_escapes_quotes_like_titles():
    p = _project([_tt(text='They call it "progress".')])
    assert ' LBA_court_plant_tt:0 "They call it \\"progress\\"."' in export_focus_localisation(p)


def test_export_without_texts_is_byte_identical():
    # The existing exporter fixture: no tooltip texts anywhere, so the loc
    # writers must add nothing (not even a trailing line).
    sample = export_project_files(make_sample_project())
    assert all(f.content.endswith("\n") and not f.content.endswith("\n\n") for f in sample
               if f.relativePath.endswith(".yml"))
    bare = _project([_tt()], [_tt("LBA_evt_tt")], [_tt("LBA_dec_tt")])
    empty = _project([], [], [])
    for with_key, without in zip(export_project_files(bare), export_project_files(empty)):
        if with_key.relativePath.endswith(".yml"):
            assert with_key.content == without.content


# ----- validation -------------------------------------------------------------------

def test_validation_warns_without_text_at_every_site():
    p = _project([_tt()], [_tt("LBA_evt_tt")], [_tt("LBA_dec_tt", kind="hydroelectric_dam")])
    warned = [i for i in validate_project(p) if i.code == "reward.tooltip.unlocalised"]
    assert [i.focusId for i in warned] == ["LBA_a", None, None]
    assert all(i.severity == "warning" for i in warned)
    assert "raw key" in warned[0].message and KEY in warned[0].message


def test_validation_quiet_with_text_or_known_key():
    assert "reward.tooltip.unlocalised" not in _codes(_project([_tt(text="Some text")]))
    assert "reward.tooltip.unlocalised" not in _codes(_project([_tt()]), loc_key_exists=lambda k: True)
    assert "reward.tooltip.unlocalised" in _codes(_project([_tt()]), loc_key_exists=lambda k: False)
    assert "reward.tooltip.unlocalised" in _codes(_project([_tt()]), loc_key_exists=lambda k: None)


def test_validation_bad_key_is_error_and_conflict_warns():
    bad = [i for i in validate_project(_project([_tt("1st key")])) if i.code == "reward.tooltip.invalidKey"]
    assert bad and bad[0].severity == "error"
    p = _project([_tt(text="One")], [_tt(text="Two")])
    conflict = [i for i in validate_project(p) if i.code == "reward.tooltip.conflict"]
    assert len(conflict) == 1 and "event LBA_forge.1 option a" in conflict[0].message
    assert "reward.tooltip.conflict" not in _codes(_project([_tt(text="Same")], [_tt(text="Same")]))


def test_disabled_items_are_ignored():
    p = _project([RewardItem(kind="custom_tooltip", enabled=False, params={"tooltipId": KEY})])
    assert "reward.tooltip.unlocalised" not in _codes(p)


# ----- smoke check ------------------------------------------------------------------

def _files(loc_lines="", tooltip_text=""):
    return [
        ExportedFile(relativePath="common/national_focus/lba.txt",
                     content=f"focus_tree = {{\n\tid = t\n\tfocus = {{\n\t\tid = LBA_a\n"
                             f"\t\tcompletion_reward = {{ custom_effect_tooltip = {KEY} }}\n\t}}\n}}\n"),
        ExportedFile(relativePath="localisation/english/LBA_focus_l_english.yml", bom=True,
                     content=f'l_english:\n LBA_a:0 "A"\n LBA_a_desc:0 "d"\n{loc_lines}'),
    ]


def test_smoke_check_warns_missing_tooltip_loc():
    issues = [i for i in smoke_check(_files()) if i.code == "loc.tooltip.missing"]
    assert len(issues) == 1 and KEY in issues[0].message and issues[0].severity == "warning"


def test_smoke_check_satisfied_by_exported_loc_or_known_loc():
    assert not [i for i in smoke_check(_files(f' {KEY}:0 "Text"\n')) if i.code == "loc.tooltip.missing"]
    assert not [i for i in smoke_check(_files(), known_loc={KEY}) if i.code == "loc.tooltip.missing"]
    assert [i for i in smoke_check(_files(), known_loc=set()) if i.code == "loc.tooltip.missing"]


def test_smoke_check_on_real_export_matches_validation():
    p = _project([_tt(text="Foreign plants take notice.")], [_tt("LBA_evt_tt")])
    codes = {i.code for i in smoke_check(export_project_files(p))}
    assert "loc.tooltip.missing" in codes            # the event option's bare key
    assert "export.loc.duplicate" not in codes
    p_ok = _project([_tt(text="Foreign plants take notice.")], [_tt("LBA_evt_tt", "Agreed.")])
    assert "loc.tooltip.missing" not in {i.code for i in smoke_check(export_project_files(p_ok))}


# ----- bridge -----------------------------------------------------------------------

def test_bridge_add_focus_reports_bare_tooltip_inline():
    from ui.project_model import ProjectModel
    item = {"kind": "custom_tooltip", "params": {"tooltipId": "MEX_plant_tt"}}
    r = dispatch(ProjectModel(), "add_focus", {"x": 4, "y": 6, "title": "T",
                                               "completionReward": {"items": [item]}})
    assert r["ok"], r
    inline = [i for i in r["result"]["issues"] if i["code"] == "reward.tooltip.unlocalised"]
    assert len(inline) == 1 and "MEX_plant_tt" in inline[0]["message"]
    item["params"]["text"] = "Foreign plants take notice."
    r = dispatch(ProjectModel(), "add_focus", {"x": 4, "y": 6, "title": "T",
                                               "completionReward": {"items": [item]}})
    assert r["ok"], r
    assert "reward.tooltip.unlocalised" not in [i["code"] for i in r["result"]["issues"]]


def test_bridge_compact_presets_list_text():
    from ui.project_model import ProjectModel
    r = dispatch(ProjectModel(), "list_reward_presets", {"compact": True})
    ct = next(p for p in r["result"] if p["kind"] == "custom_tooltip")
    assert ct["params"] == "tooltipId:string*, text:string"


# ----- project model wiring ---------------------------------------------------------

def test_project_model_resolves_keys_in_background_and_revalidates(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from core import pdx_loc
    from ui.project_model import ProjectModel
    app = QApplication.instance() or QApplication([])
    calls = []

    def fake_load(roots, needed):
        calls.append((list(roots), set(needed)))
        return {"MD_known_tt": "Known text"}

    monkeypatch.setattr(pdx_loc, "load_english_localisation", fake_load)
    monkeypatch.setattr(ProjectModel, "_loc_roots", staticmethod(lambda: ["C:/fake/md"]))
    import ui.project_model as pm
    monkeypatch.setattr(pm, "_TOOLTIP_LOC_CACHE", {})     # process-wide cache: start clean
    monkeypatch.setattr(pm, "_TOOLTIP_LOC_BUILDING", {})
    model = ProjectModel()
    model.replace_project(_project([_tt("MD_known_tt")], [_tt("LBA_evt_tt")]))
    landed = []
    model.validation_changed.connect(lambda issues: landed.append(issues))

    # The fake resolver is instant, so the first pass may or may not already
    # see its answer — what matters is that ONE background lookup was kicked
    # off for exactly the project's keys.
    model.issues()
    model._tooltip_loc_thread.join(5)
    # Other tests' models (their debounced validation) may also hit the
    # patched loader — count only lookups for THIS project's keys.
    mine = lambda: [c for c in calls if c[1] == {"MD_known_tt", "LBA_evt_tt"}]
    assert mine() == [(["C:/fake/md"], {"MD_known_tt", "LBA_evt_tt"})]
    app.processEvents()                          # queued tooltip_loc_ready → validation timer
    for _ in range(50):                          # let the 250 ms debounce fire
        if landed:
            break
        app.processEvents()
        import time
        time.sleep(0.02)
    assert landed, "validation did not re-run after the lookup landed"
    warned = [i for i in landed[-1] if i.code == "reward.tooltip.unlocalised"]
    assert [i.focusId for i in warned] == [None]  # MD_known_tt resolved; LBA_evt_tt still bare
    assert model.known_tooltip_loc() == {"MD_known_tt"}
    model.issues()
    assert len(mine()) == 1                      # same (roots, keys) → cached, no re-scan
