"""Headless UI smoke tests — the regressions this suite guards against were
all UI-layer (auto-id latch, per-drag validation cost, panel wiring), which
the core-only tests could never see. Runs on the offscreen Qt platform."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.sample_project import make_sample_project
from core.types import CompletionReward, FocusNodeData, FocusPosition, IdeaData, EventData, EventOption


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def model(qapp):
    from ui.project_model import ProjectModel
    m = ProjectModel()
    project = make_sample_project()
    project.countryTag = "EGY"
    project.focuses.append(FocusNodeData(
        id="EGY_auto_named", title="Auto Named",
        position=FocusPosition(x=20, y=0), cost=10,
        completionReward=CompletionReward(rawLines=[
            "add_political_power = 150",
            "set_temp_variable = { treasury_change = -5 }",
            "modify_treasury_effect = yes",
        ])))
    project.focuses.append(FocusNodeData(
        id="EGY_ex_hand_named", title="A Fancy Title",
        position=FocusPosition(x=24, y=0), cost=5))
    project.ideas.append(IdeaData(
        id="EGY_test_idea", title="Test Spirit", description="d", picture="",
        modifierRawLines=["modifier = {", "\tstability_factor = 0.05", "}"]))
    project.events.append(EventData(
        id="EGY.900", title="Test Event", description="d",
        options=[EventOption(key="a", text="OK")]))
    m.replace_project(project, path=None)
    return m


# ----- inspector -----

def test_inspector_retitle_syncs_auto_id(model):
    from ui.inspector_panel import InspectorPanel
    panel = InspectorPanel(model)
    # Id matches its title slug -> retitle must rename the id (the latch
    # regression: it only re-armed for placeholder ids).
    model.set_selection("EGY_auto_named")
    panel._title_edit.setText("Renamed Later")
    panel._commit_title()
    assert model.find_focus("EGY_renamed_later") is not None
    assert model.selected_id == "EGY_renamed_later"


def test_inspector_retitle_preserves_hand_named_id(model):
    from ui.inspector_panel import InspectorPanel
    panel = InspectorPanel(model)
    model.set_selection("EGY_ex_hand_named")
    panel._title_edit.setText("Another Title")
    panel._commit_title()
    f = model.find_focus("EGY_ex_hand_named")
    assert f is not None and f.title == "Another Title"


def test_inspector_meta_and_counts(model):
    from ui.inspector_panel import InspectorPanel
    panel = InspectorPanel(model)
    model.set_selection("EGY_auto_named")
    assert "(20, 0)" in panel._meta_pos.text()
    assert "70d" in panel._meta_cost.text()          # cost 10 -> 70 days
    assert "70 in-game days" in panel._cost_days.text()
    # Raw reward lines: 150 pp + treasury idiom = 3 top-level statements.
    assert panel._reward_count.text().startswith("3 effects")
    assert panel._avail_count.text() == "always"


def test_inspector_status_dot_uses_cached_validation(model):
    from ui.inspector_panel import InspectorPanel
    panel = InspectorPanel(model)
    model.set_selection("EGY_auto_named")
    calls = {"n": 0}
    real_issues = model.issues

    def counting_issues():
        calls["n"] += 1
        return real_issues()

    model.issues = counting_issues  # type: ignore[method-assign]
    panel._issues_cache = None
    panel._refresh_status()
    first = calls["n"]
    panel._refresh_status()          # cache hit — no second validation pass
    assert calls["n"] == first == 1


# ----- chip selector performance guard -----

def test_chip_suggestions_skip_identical_rebuild(qapp):
    from ui.chip_selector import ChipSelector
    chips = ChipSelector(placeholder="x")
    rebuilds = {"n": 0}
    real = chips._rebuild_combo

    def counting():
        rebuilds["n"] += 1
        real()

    chips._rebuild_combo = counting  # type: ignore[method-assign]
    chips.update_suggestions(["a", "b", "c"])
    chips.update_suggestions(["a", "b", "c"])   # identical -> early-out
    chips.update_suggestions(["a", "b"])        # changed -> rebuild
    assert rebuilds["n"] == 2


# ----- focuses list -----

def test_focuses_list_rows_and_selection(model):
    from ui.focuses_list_panel import ROLE_ID, FocusesListPanel
    panel = FocusesListPanel(model)
    n = len(model.project.focuses)
    assert panel._list.count() == n
    assert panel._focus_count.text() == f"{n} focuses"
    item = next(panel._list.item(i) for i in range(panel._list.count())
                if panel._list.item(i).data(ROLE_ID) == "EGY_auto_named")
    panel._on_clicked(item)
    assert model.selected_id == "EGY_auto_named"


def test_focuses_list_status_dots_follow_validation(model):
    from ui.focuses_list_panel import ROLE_ID, ROLE_STATUS, FocusesListPanel
    panel = FocusesListPanel(model)
    model.find_focus("EGY_auto_named").description = ""
    issues = model.issues()
    panel._refresh_warnings(issues)
    statuses = {panel._list.item(i).data(ROLE_ID): panel._list.item(i).data(ROLE_STATUS)
                for i in range(panel._list.count())}
    assert statuses["EGY_auto_named"] in ("warning", "error")


# ----- stats -----

def test_stats_panel_parses_raw_rewards(model):
    from ui.stats_panel import StatsPanel
    panel = StatsPanel(model)
    panel.refresh()
    assert panel._tile_focuses.text() == str(len(model.project.focuses))
    mix = {label for label, _v, _t in panel._reward_chart._rows}
    assert "Political power" in mix and "Treasury" in mix
    # The raw 150pp is recognized by the parser -> counted in the pp economy.
    from core.tree_stats import compute_stats
    assert compute_stats(model.project)["pp_gained"] >= 150


# ----- welcome -----

def test_welcome_cards_load_and_degrade(qapp, tmp_path):
    from ui.welcome_dialog import WelcomeDialog
    good = tmp_path / "good.focusforge.json"
    good.write_text(json.dumps({
        "countryTag": "EGY",
        "focuses": [{"id": "a", "position": {"x": 1, "y": 2}},
                    {"id": "b", "position": {"x": 3, "y": 4}}],
    }), encoding="utf-8")
    bad = tmp_path / "bad.focusforge.json"
    bad.write_text("{not json", encoding="utf-8")
    dlg = WelcomeDialog(recent=[str(good), str(bad)])
    dlg._load_next_summary()
    dlg._load_next_summary()
    assert "2 focuses" in dlg._cards[0].meta.text()
    assert "EGY" in dlg._cards[0].meta.text()
    assert dlg._cards[1].meta.text() == "could not read project"


# ----- idea / event editors -----

def test_idea_editor_card_chips(model):
    from ui.idea_editor import IdeaEditorDialog
    dlg = IdeaEditorDialog(model, model.project.ideas[-1])
    assert dlg._mods_chip.text() == "1 modifier"
    assert dlg._id.text() == "EGY_test_idea"


def test_event_editor_card_chips(model):
    from ui.event_editor import EventEditorDialog
    dlg = EventEditorDialog(model, model.project.events[-1])
    assert dlg._type_chip.text() == "country event"
    assert dlg._options_chip.text() == "1 option"


# ----- canvas: hover lineage + minimap -----

def _lineage_scene(model):
    from ui.graph_scene import GraphScene
    scene = GraphScene()
    scene.reconcile(model.project, "")
    return scene


def _chain_model(qapp):
    from core.types import FocusForgeProject, FocusNodeData, FocusPosition
    from ui.project_model import ProjectModel
    m = ProjectModel()
    project = FocusForgeProject(countryTag="EGY", focuses=[
        FocusNodeData(id="root", position=FocusPosition(0, 0)),
        FocusNodeData(id="mid", position=FocusPosition(0, 1),
                      prerequisites=["root"]),
        FocusNodeData(id="leaf", position=FocusPosition(0, 2),
                      prerequisites=["mid"]),
        FocusNodeData(id="stranger", position=FocusPosition(4, 0)),
    ])
    m.replace_project(project, path=None)
    return m


def test_hover_lineage_lights_ancestry_and_clears(qapp):
    m = _chain_model(qapp)
    scene = _lineage_scene(m)
    scene.on_node_hover("leaf", True)
    lit = {k for k, e in scene._edges.items() if e._lineage}
    assert lit == {("prereq", "mid", "leaf"), ("prereq", "root", "mid")}
    scene.on_node_hover("leaf", False)
    assert not any(e._lineage for e in scene._edges.values())


def test_hover_lineage_root_has_no_edges(qapp):
    m = _chain_model(qapp)
    scene = _lineage_scene(m)
    scene.on_node_hover("stranger", True)
    assert not any(e._lineage for e in scene._edges.values())


def test_minimap_mapping_roundtrip_and_cache(qapp):
    from PySide6.QtCore import QPointF
    from ui.graph_scene import GraphScene
    from ui.graph_view import GraphView
    m = _chain_model(qapp)
    scene = GraphScene()
    view = GraphView(scene)
    view.resize(800, 600)
    scene.reconcile(m.project, "")
    mini = view._minimap
    mini._rebuild_dots(scene.node_points())
    pt = QPointF(120.0, 340.0)
    rt = mini._widget_to_scene(mini._scene_to_widget(pt))
    assert abs(rt.x() - pt.x()) < 0.01 and abs(rt.y() - pt.y()) < 0.01
    # layout_version only bumps when the layout actually changes.
    v = scene.layout_version
    scene.reconcile(m.project, "")            # no changes
    assert scene.layout_version == v
    from core.types import FocusPosition
    m.update_focus("stranger", position=FocusPosition(6, 0))
    scene.reconcile(m.project, "")
    assert scene.layout_version == v + 1


# ----- canvas: grid labels gated by zoom -----

def test_grid_labels_skip_when_unreadable(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QTransform
    from ui import graph_background as gb

    orig = QPainter.drawText
    calls = {"n": 0}

    def counting(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    QPainter.drawText = counting
    try:
        def draw_at(scale):
            calls["n"] = 0
            img = QImage(400, 300, QImage.Format_ARGB32)
            p = QPainter(img)
            p.setTransform(QTransform().scale(scale, scale))
            gb._paint_grid_labels(p, QRectF(0, 0, 4000, 3000))
            p.end()
            return calls["n"]

        assert draw_at(0.15) == 0    # fit-to-content zoom: no sub-pixel glyphs
        assert draw_at(1.0) > 0      # editing zoom: labels visible
    finally:
        QPainter.drawText = orig


# ----- settings: diagnostic report -----

def test_settings_diagnostic_report_to_clipboard(model, tmp_path):
    from core import applog
    applog.install(tmp_path, force=True)
    applog.logger().info("smoke-test event")
    from ui.settings_panel import SettingsPanel
    panel = SettingsPanel(model)
    panel._copy_diagnostics()
    text = QApplication.clipboard().text()
    assert "=== Focus Forge diagnostic report ===" in text
    assert "[EGY]" in text                  # project line
    assert "focuses" in text                # content counts
    assert "smoke-test event" in text       # log tail included


# ----- reward editor: structure-raw-script conversion -----

def test_reward_editor_structures_raw_script(model):
    from ui.reward_editor import RewardEditor
    editor = RewardEditor(model)
    model.set_selection("EGY_auto_named")
    editor.set_focus_id("EGY_auto_named")
    assert editor._convert_btn.isVisibleTo(editor)
    editor._convert_raw()
    reward = model.find_focus("EGY_auto_named").completionReward
    assert not reward.rawLines
    assert [i.kind for i in reward.items] == ["political_power", "treasury_change"]
    assert reward.items[0].params["amount"] == "150"
