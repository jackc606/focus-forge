"""UI layer of multi-tree projects (core.multi_tree): the tree switcher above
the canvas, the SHARED marking on canvas / list / inspector, issue activation
across trees, and the correctness follow-ups (paste, clear, rename, prefix).

Runs offscreen. The tests that need a whole ``MainWindow`` build a real one —
see ``make_window`` for how it is kept away from the user's settings, the AI
bridge's shared discovery file, and the network.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from core import multi_tree as mt
from core.focus_import import find_focus_trees, import_focus_tree
from core.sample_project import make_sample_project
from core.types import FocusPosition, ValidationIssue
from tests.test_multi_tree import MD_AUSTRALIA, MD_ROOT, _ref, _setup


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _project(tmp_path, tree_id="tree_a"):
    """The 3-tree / 5-shared fixture file of test_multi_tree, imported."""
    roots = _setup(tmp_path)
    return import_focus_tree(_ref(roots, tree_id), roots)


@pytest.fixture()
def model(qapp, tmp_path):
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m.replace_project(_project(tmp_path))
    return m


@pytest.fixture()
def make_window(qapp, monkeypatch, tmp_path):
    """Factory for a real MainWindow that cannot reach anything outside the
    test: MainWindow.__init__ reads the user's QSettings (and would start the
    AI bridge — rewriting the discovery file a running Focus Forge owns — if
    the bridge is enabled there), kicks off an update check, and may re-point
    the icon provider's persisted roots.

    * every ``QSettings("FocusForge", "FocusForge")`` the window and its panels
      create is swapped for one on a temp .ini (``QSettings.setDefaultFormat``
      is NOT enough: the two-argument constructor always uses the native
      registry format);
    * the bridge can neither listen nor write / clear its discovery file;
    * the update check, game-data warm-up and every icon-root mutation are off.
    """
    import ui.agent_bridge as ab
    import ui.assistant_settings_dialog as asd
    import ui.icon_provider as ip
    import ui.inspector_panel as insp
    import ui.main_window as mw
    import ui.provider_warmup as pw
    import ui.settings_panel as sp
    import ui.workspace as ws

    ini = str(tmp_path / "focusforge-test-settings.ini")

    def temp_settings(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    for module in (mw, insp, sp, asd, ws):
        monkeypatch.setattr(module, "QSettings", temp_settings)
    monkeypatch.setattr(ab.AgentBridge, "start", lambda self: False)
    monkeypatch.setattr(ab.AgentBridge, "stop", lambda self: None)
    monkeypatch.setattr(ab, "write_bridge_info", lambda *a, **k: None)
    monkeypatch.setattr(ab, "clear_bridge_info", lambda *a, **k: None)
    monkeypatch.setattr(mw.MainWindow, "_check_for_updates", lambda self, manual=False: None)
    for name in ("set_roots", "add_extra_roots", "ensure_default_roots"):
        monkeypatch.setattr(ip.IconProvider, name, lambda self, *a, **k: None)
    monkeypatch.setattr(ip.IconProvider, "switch_md_edition", lambda self, key: (True, ""))
    monkeypatch.setattr(pw, "warm_game_data_async", lambda tag="": None)
    windows = []

    def build(project=None):
        # Refuse to construct a window unless the redirect is really in place.
        probe = mw.QSettings("FocusForge", "FocusForge")
        assert probe.format() == QSettings.IniFormat and _same_path(probe.fileName(), ini)
        assert not probe.value("ai_bridge_enabled", False, type=bool)
        win = mw.MainWindow()
        assert _same_path(win._settings.fileName(), ini) and not win._bridge.is_listening()
        if project is not None:
            win._model.replace_project(project, path=None)
        windows.append(win)
        return win

    try:
        yield build
    finally:
        for win in windows:
            win._autosave_timer.stop()
            win.deleteLater()


class _FakeMsgBox:
    """QMessageBox stand-in: records the text, answers Yes."""
    Yes, No = QMessageBox.Yes, QMessageBox.No
    calls: list = []

    @classmethod
    def warning(cls, parent, title, text, *args, **kwargs):
        cls.calls.append(text)
        return cls.Yes

    question = information = warning


def _combo_labels(win) -> list:
    return [win._tree_combo.itemText(i) for i in range(win._tree_combo.count())]


# ----- tree switcher -------------------------------------------------------------

def test_switcher_hidden_for_single_tree_project(make_window):
    win = make_window(make_sample_project())
    assert win._tree_bar.isHidden() and win._tree_combo.count() == 0


def test_switcher_lists_the_trees_of_a_multi_tree_project(make_window, tmp_path):
    win = make_window(_project(tmp_path))
    assert not win._tree_bar.isHidden()
    assert _combo_labels(win) == ["tree_a — 2 focuses + 5 shared",
                                  "tree_b — 2 focuses + 3 shared",
                                  "tree_c — 0 focuses + 2 shared"]
    assert win._tree_combo.currentIndex() == 0
    assert "3 trees in multi.txt" in win._tree_bar_note.text()
    # A single-tree project loaded afterwards hides it again.
    win._model.replace_project(make_sample_project(), path=None)
    assert win._tree_bar.isHidden() and win._tree_combo.count() == 0


def test_choosing_a_tree_switches_and_undo_restores_it(make_window, tmp_path):
    win = make_window(_project(tmp_path))
    m = win._model
    fits = []
    win._view.fit_to_content = lambda: fits.append(m.project.treeId)
    win._tree_combo.setCurrentIndex(1)
    assert m.project.treeId == "tree_b" and m.selected_id == ""
    assert set(win._scene._nodes) == {f.id for f in m.project.focuses}
    assert {"TB_root", "TB_child", "SH_a_root"} <= set(win._scene._nodes)
    assert "TA_root" not in win._scene._nodes
    assert fits == ["tree_b"]                              # view re-fitted once
    assert win._status_label.text() == "Showing tree_b — 2 focuses + 3 shared."

    assert m.undo() is True                                # one step back to tree_a
    assert m.project.treeId == "tree_a" and win._tree_combo.currentIndex() == 0
    assert m.can_undo() is False and m.can_redo() is True  # the sync switched nothing itself
    assert fits == ["tree_b", "tree_a"]
    assert m.redo() is True
    assert m.project.treeId == "tree_b" and win._tree_combo.currentIndex() == 1

    # Renaming the active tree's id (Settings) relabels its entry in place.
    m.update_project_meta(treeId="tree_beta")
    assert _combo_labels(win)[1] == "tree_beta — 2 focuses + 3 shared"
    assert win._tree_combo.currentIndex() == 1 and m.project.treeId == "tree_beta"


def test_switch_flushes_a_pending_inspector_edit(qapp, make_window, tmp_path):
    win = make_window(_project(tmp_path))
    m = win._model
    m.set_selection("TA_root")
    win.show()                                             # offscreen platform
    win.activateWindow()
    edit = win._inspector._title_edit
    edit.setFocus()
    qapp.processEvents()
    if QApplication.focusWidget() is not edit:
        pytest.skip("offscreen platform did not give the editor keyboard focus")
    edit.selectAll()
    QTest.keyClicks(edit, "Typed Before Switching")
    assert m.find_focus("TA_root").title != "Typed Before Switching"   # not committed yet
    win._tree_combo.setCurrentIndex(1)
    assert m.project.treeId == "tree_b"
    parked = {f.id: f for f in m.project.otherTrees[0].focuses}
    assert parked["TA_root"].title == "Typed Before Switching"
    win.hide()


# ----- shared marking ------------------------------------------------------------

def test_shared_marker_on_canvas_nodes(make_window, tmp_path):
    from ui.agent_bridge import render_scene_region
    from ui.focus_node_item import SHARED_TOOLTIP
    win = make_window(_project(tmp_path))
    nodes = win._scene._nodes
    shared = {f.id for f in win._model.project.focuses if f.shared}
    assert shared == {"SH_a_root", "SH_a_child", "SH_a_leaf", "SH_b_root", "SH_b_child"}
    assert {fid for fid, n in nodes.items() if n.is_shared} == shared
    assert nodes["SH_a_root"].toolTip() == SHARED_TOOLTIP
    assert nodes["TA_root"].is_shared is False and nodes["TA_root"].toolTip() == ""
    # Both kinds paint without error.
    img = render_scene_region(win._scene, win._scene.itemsBoundingRect(), 600)
    assert not img.isNull() and img.width() > 0
    # A pasted copy of a shared focus is an own focus → no marker.
    new_id = win._model.duplicate_focuses(["SH_a_root"])[0]
    assert nodes[new_id].is_shared is False and nodes["SH_a_root"].is_shared is True


def test_single_tree_nodes_carry_no_marker(make_window):
    win = make_window(make_sample_project())
    assert win._scene._nodes
    assert all(not n.is_shared and n.toolTip() == "" for n in win._scene._nodes.values())


def test_focuses_list_marks_shared(qapp, model):
    from ui.focuses_list_panel import ROLE_ID, ROLE_SHARED, FocusesListPanel
    panel = FocusesListPanel(model)
    rows = {panel._list.item(i).data(ROLE_ID): panel._list.item(i)
            for i in range(panel._list.count())}
    assert rows["SH_b_child"].data(ROLE_SHARED) is True
    assert not rows["TA_root"].data(ROLE_SHARED)
    assert panel._focus_count.text() == "7 focuses · 5 shared"
    panel.grab()                                           # the delegate paints the tag


def test_inspector_shared_note_and_global_id_uniqueness(qapp, model):
    from ui.inspector_panel import InspectorPanel
    panel = InspectorPanel(model)
    model.set_selection("SH_a_root")
    assert not panel._shared_note.isHidden()
    model.set_selection("TA_child")
    assert panel._shared_note.isHidden()
    # TB_root lives in the parked tree_b — still taken.
    assert panel._unique_focus_id("TB_root", ignore="TA_child") == "TB_root_2"
    assert panel._unique_focus_id("SH_b_root", ignore="TA_child") == "SH_b_root_2"
    panel._id_edit.setText("TB_root")
    panel._commit_id()
    assert model.selected_id == "TB_root_2" and model.find_focus("TB_root") is None
    assert panel._id_edit.text() == "TB_root_2"
    assert [f.id for f in model.project.otherTrees[0].focuses] == ["TB_root", "TB_child"]


def test_settings_names_the_active_tree(qapp, model):
    from ui.settings_panel import SettingsPanel
    panel = SettingsPanel(model)
    label = panel._project_form.labelForField(panel._tree_id)
    assert label.text() == "Active Tree ID" and "3 trees" in panel._tree_id.toolTip()
    assert not panel._country_hint.isHidden()              # verbatim country = { } block
    model.replace_project(make_sample_project())
    assert label.text() == "Tree ID" and panel._tree_id.toolTip() == ""
    assert panel._country_hint.isHidden()


# ----- correctness follow-ups ----------------------------------------------------

def test_paste_of_a_shared_focus_is_an_own_focus(model):
    assert model.switch_tree(1)                            # tree_b: SH_a_root is offset +5 x
    original = model.find_focus("SH_a_root")
    assert original.shared and original.appliedOffset == FocusPosition(x=5, y=0)
    assert original.offsets
    child_id = model.duplicate_focuses(["SH_a_child"])[0]
    new_id = model.duplicate_focuses(["SH_a_root"])[0]
    for fid in (child_id, new_id):
        copy = model.find_focus(fid)
        assert copy.shared is False and copy.appliedOffset is None
        assert copy.relativePositionId is None and copy.offsets is None
    copy = model.find_focus(new_id)
    assert (copy.position.x, copy.position.y) == (original.position.x + 1, original.position.y + 1)
    assert original.shared and original.offsets            # the original is untouched
    assert len(mt.all_shared(model.project)) == 5
    assert new_id in {f.id for f in mt.own_focuses(model.project)}


def test_clear_focuses_keeps_shared_and_other_trees(make_window, monkeypatch, tmp_path):
    import ui.main_window as mw
    win = make_window(_project(tmp_path))
    m = win._model
    _FakeMsgBox.calls = []
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    win._on_clear_focuses()
    text = _FakeMsgBox.calls[0]
    assert "all 2 focuses of the tree tree_a" in text and "5 shared focuses" in text
    assert "other 2 trees" in text and "ctrl+z" in text.lower()
    p = m.project
    assert mt.own_focuses(p) == [] and len(p.focuses) == 5 and all(f.shared for f in p.focuses)
    assert [[f.id for f in t.focuses] for t in p.otherTrees] == [["TB_root", "TB_child"], []]
    assert len(mt.all_shared(p)) == 5 and mt.tree_count(p) == 3
    # Nothing of its own left: a second clear is a no-op that says why.
    win._on_clear_focuses()
    assert len(_FakeMsgBox.calls) == 1 and "no focuses of its own" in win._status_label.text()
    assert m.undo() and len(mt.own_focuses(m.project)) == 2


def test_clear_focuses_wording_unchanged_for_single_tree(make_window, monkeypatch):
    import ui.main_window as mw
    win = make_window(make_sample_project())
    n = len(win._model.project.focuses)
    _FakeMsgBox.calls = []
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    win._on_clear_focuses()
    assert _FakeMsgBox.calls[0].startswith(f"This removes all {n} focuses from this project (")
    assert win._model.project.focuses == []


def test_rename_rewrites_shortcut_targets_in_every_tree(model):
    p = model.project
    assert p.shortcuts[0].target == "TA_root"
    assert model.rename_focus("TA_root", "TA_origin") == "TA_origin"
    assert model.project.shortcuts[0].target == "TA_origin"
    assert model.undo() and model.project.shortcuts[0].target == "TA_root"   # same undo step
    assert model.redo() and model.project.shortcuts[0].target == "TA_origin"
    # A parked tree's shortcut pointing at a shared focus follows its rename too.
    model.project.otherTrees[0].shortcuts[0].target = "SH_a_root"
    assert model.rename_focus("SH_a_root", "SH_alpha") == "SH_alpha"
    assert model.project.otherTrees[0].shortcuts[0].target == "SH_alpha"
    assert model.project.shortcuts[0].target == "TA_origin"


def test_event_reference_counts_cover_parked_trees(model):
    model.project.otherTrees[0].focuses[0].completionReward.events = []
    from core.types import EventReward
    model.project.otherTrees[0].focuses[0].completionReward.events.append(EventReward(id="TST.1"))
    assert model.event_reference_count("TST.1") == 1


def test_prefix_fix_is_refused_for_multi_tree_projects(qapp, model):
    from core.tree_index import CollisionReport
    from ui.export_preflight import (ExportPreflightDialog, apply_prefix,
                                     prefix_unavailable_reason)
    before = [f.id for f in mt.all_focuses(model.project)]
    reason = prefix_unavailable_reason(model.project)
    assert "all 3 trees" in reason
    with pytest.raises(ValueError):
        apply_prefix(model, "TST_NEW")
    assert [f.id for f in mt.all_focuses(model.project)] == before
    assert model.project.treeId == "tree_a" and model.can_undo() is False
    report = CollisionReport(export_basename="x.txt", duplicate_ids={"multi.txt": ["TA_root"]},
                             suggested_basename="multi.txt")
    dlg = ExportPreflightDialog(report, prefix_blocked=reason)
    assert not dlg.prefix_btn.isEnabled() and dlg.replace_btn.isEnabled()
    assert ExportPreflightDialog(report).prefix_btn.isEnabled()


def test_prefix_fix_moves_offset_triggers_with_the_tree_id(qapp, tmp_path):
    """A copy-mode import is one tree + its shared focuses: prefixable, and the
    shared focuses' per-tree offsets must follow the new tree id."""
    from ui.export_preflight import apply_prefix, prefix_unavailable_reason
    from ui.project_model import ProjectModel
    import dataclasses
    roots = _setup(tmp_path)
    ref = dataclasses.replace(_ref(roots, "tree_b"), id_prefix="ONE")
    m = ProjectModel()
    m.replace_project(import_focus_tree(ref, roots))
    assert not mt.is_multi(m.project) and prefix_unavailable_reason(m.project) == ""
    root = m.find_focus("ONE_SH_a_root")
    assert any("has_focus_tree = one_focus" in ln for block in root.offsets for ln in block)
    mapping = apply_prefix(m, "TWO")
    assert mapping["ONE_TB_root"] == "TWO_ONE_TB_root" and m.project.treeId == "two_focus"
    assert m.project.shortcuts[0].target == "TWO_ONE_TB_root"
    root = m.find_focus("TWO_ONE_SH_a_root")
    lines = [ln for block in root.offsets for ln in block]
    assert any("has_focus_tree = two_focus" in ln for ln in lines)
    assert not any("has_focus_tree = one_focus" in ln for ln in lines)


def test_custom_icons_are_written_for_every_tree(qapp, model, tmp_path):
    from ui.country_export import export_focus_icon_assets
    from ui.country_editor import _scaled_b64_png
    from PySide6.QtGui import QImage
    img = QImage(10, 10, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    data = _scaled_b64_png(img, 100, 88)
    model.project.focuses[0].iconData = data               # active tree
    model.project.otherTrees[0].focuses[0].iconData = data  # parked tree
    out = tmp_path / "mod"
    assert export_focus_icon_assets(model.project, str(out)) == 2


# ----- validation issues across trees --------------------------------------------

def _overlap_in_tree_b(project):
    """Put tree_b's two own focuses on one cell (the kind of error MD's Gillard
    tree really has) while tree_a is the active tree."""
    root, child = project.otherTrees[0].focuses
    child.position = FocusPosition(x=root.position.x, y=root.position.y)
    return child.id


def test_parked_tree_issue_carries_its_tree_id(model):
    fid = _overlap_in_tree_b(model.project)
    issues = [i for i in model.issues() if i.code == "focus.position.overlap"]
    assert len(issues) == 1
    assert issues[0].treeId == "tree_b" and issues[0].focusId == fid
    assert issues[0].message.startswith("[tree_b] ")
    assert all(i.treeId is None for i in model.issues() if not i.message.startswith("["))
    assert ValidationIssue().treeId is None                # default: old call sites unaffected


def test_activating_a_parked_tree_issue_switches_and_selects(make_window, tmp_path):
    from ui.widgets import ClickableFrame
    project = _project(tmp_path)
    fid = _overlap_in_tree_b(project)
    win = make_window(project)
    m = win._model
    issues = m.issues()
    win._validation.refresh(issues)
    box = win._validation._issues_box
    cards = [box.itemAt(i).widget() for i in range(box.count())]
    assert len(cards) == len(issues)
    target = next(n for n, i in enumerate(issues) if i.code == "focus.position.overlap")
    card = cards[target]
    assert isinstance(card, ClickableFrame)
    assert m.project.treeId == "tree_a" and m.find_focus(fid) is None
    card.clicked.emit()
    assert m.project.treeId == "tree_b" and m.selected_id == fid
    assert win._tree_combo.currentIndex() == 1
    assert win._scene._nodes[fid].isSelected()
    # The sidebar's warning cards use the same activation.
    assert m.undo() and m.project.treeId == "tree_a"
    win._focuses_panel._refresh_warnings([issues[target]])
    win._focuses_panel._warnings_box.itemAt(0).widget().clicked.emit()
    assert m.project.treeId == "tree_b" and m.selected_id == fid


def test_reveal_focus_finds_its_tree(model):
    assert model.tree_index_of_focus("TA_root") == -1      # already on the canvas
    assert model.tree_index_of_focus("nope") == -1
    assert model.reveal_focus("TB_child") is True
    assert model.project.treeId == "tree_b" and model.selected_id == "TB_child"
    assert model.reveal_focus("nope") is False and model.project.treeId == "tree_b"
    # An issue that names only a focus (no treeId) still lands on its tree.
    assert model.reveal_issue(ValidationIssue(focusId="TA_child")) is True
    assert model.project.treeId == "tree_a" and model.selected_id == "TA_child"
    # A stale tree id (renamed since) falls back to the focus.
    assert model.reveal_issue(ValidationIssue(focusId="TB_root", treeId="gone")) is True
    assert model.project.treeId == "tree_b" and model.selected_id == "TB_root"


# ----- import --------------------------------------------------------------------

def test_import_dialog_count_text_and_whole_file_wording(qapp, tmp_path):
    from ui.import_tree_dialog import _REF_ROLE, ImportTreeDialog, focus_count_text
    roots = _setup(tmp_path)
    (tmp_path / "common" / "national_focus" / "solo.txt").write_text(
        "focus_tree = {\n\tid = solo_tree\n\tcountry = { modifier = { tag = SOL } }\n"
        "\tfocus = {\n\t\tid = SOL_one\n\t\tx = 0\n\t\ty = 0\n\t}\n}\n", encoding="utf-8")
    refs = {r.tree_id: r for r in find_focus_trees(roots, use_cache=False)}
    assert focus_count_text(refs["tree_a"]) == "2 + 5 shared"
    assert focus_count_text(refs["tree_c"]) == "0 + 2 shared"
    assert focus_count_text(refs["solo_tree"]) == "1"
    assert refs["tree_a"].focus_count == 7 and refs["tree_a"].own_count == 2
    assert refs["tree_a"].trees_in_file == 3 and refs["solo_tree"].trees_in_file == 1

    dlg = ImportTreeDialog(roots)
    rows = {dlg._tree.topLevelItem(i).data(0, _REF_ROLE).tree_id: dlg._tree.topLevelItem(i)
            for i in range(dlg._tree.topLevelItemCount())}
    assert rows["tree_a"].text(2) == "2 + 5 shared" and rows["solo_tree"].text(2) == "1"

    dlg._tree.setCurrentItem(rows["tree_a"])
    text = dlg._replace_label.text()
    assert "whole file is imported" in text and "all 3 trees and the shared focuses" in text
    assert "tree_a is shown first" in text
    assert dlg._copy_check.text() == "Start a separate copy of tree_a only"
    assert "other 2 trees are not imported" in dlg._copy_note.text()

    dlg._tree.setCurrentItem(rows["solo_tree"])           # single-tree file: wording as before
    assert dlg._replace_label.text().startswith("This is ")
    assert "whole file" not in dlg._replace_label.text()
    assert dlg._copy_check.text() == "Start a separate copy instead"


class _FakeImportDialog:
    """ImportTreeDialog stand-in: 'the user picked ``ref`` and pressed Import'."""
    ref = None

    def __init__(self, roots, parent=None) -> None:
        pass

    def exec(self):
        return True

    def selected_ref(self):
        return type(self).ref


def _import_through_the_action(win, monkeypatch, ref):
    """Run MainWindow._import_tree — the Import Tree… action — with the picker
    answered by ``ref``."""
    import dataclasses
    import ui.main_window as mw
    # Carry the roots on the ref (as an ad-hoc folder import does), so the
    # localisation lookup stays inside the fixture / MD folder.
    _FakeImportDialog.ref = dataclasses.replace(ref, roots=tuple(ref.roots) or (MD_ROOT,))
    monkeypatch.setattr(mw, "ImportTreeDialog", _FakeImportDialog)
    win._import_tree()


def test_import_status_names_the_trees(make_window, monkeypatch, tmp_path):
    import dataclasses
    roots = _setup(tmp_path)
    win = make_window()
    ref = dataclasses.replace(_ref(roots, "tree_b"), roots=tuple(roots))
    _import_through_the_action(win, monkeypatch, ref)
    assert win._status_label.text() == (
        "Imported 3 trees (9 focuses, 5 shared) from multi.txt — showing tree_b. "
        "Save to keep, or Export into a mod.")
    assert win._tree_combo.currentIndex() == 1 and not win._tree_bar.isHidden()
    # Copy mode takes one tree → the single-tree wording, no switcher.
    ref = dataclasses.replace(ref, id_prefix="ONE")
    _import_through_the_action(win, monkeypatch, ref)
    assert win._status_label.text() == (
        "Imported 5 focuses from one_focus — Save to keep, or Export into a mod.")
    assert win._tree_bar.isHidden()


# ----- the real thing ------------------------------------------------------------

EXPECTED_OWN = {"howardgov_focus": 88, "australia_abbottgov_focus": 88,
                "costellogov_focus": 60, "ruddgov_focus": 64, "gillardgov_focus": 53,
                "ruddgov_return_focus": 7, "turnbullgov_focus": 1, "miscle_tree_focus": 0}
PNG_HOWARD = os.path.join(tempfile.gettempdir(), "focusforge_multitree_howardgov_focus.png")
PNG_ABBOTT = os.path.join(tempfile.gettempdir(),
                          "focusforge_multitree_australia_abbottgov_focus.png")


def _settle_icons(app) -> None:
    """Let the background icon decode finish so the render shows real icons
    (best effort — without configured game folders nodes show abbreviations)."""
    import ui.icon_provider as ip
    for _ in range(3):
        thread = getattr(ip.provider(), "_icon_warm_thread", None)
        if thread is not None:
            thread.join(120)
        app.processEvents()


def _render_canvas(win, path: str):
    """The bridge ``screenshot`` op's whole-tree render, saved to ``path``."""
    from ui.agent_bridge import _GRID_X, _GRID_Y, render_scene_region
    src = win._scene.itemsBoundingRect().adjusted(-_GRID_X, -_GRID_Y, _GRID_X, _GRID_Y)
    img = render_scene_region(win._scene, src, 4000)
    assert img.save(path, "PNG")
    return img


@pytest.mark.skipif(not os.path.isfile(MD_AUSTRALIA), reason="Millennium Dawn is not installed")
def test_real_md_australia_through_the_main_window(qapp, make_window, monkeypatch):
    from core.focus_import import _trees_in_file
    ref = next(r for r in _trees_in_file(MD_AUSTRALIA) if r.tree_id == "howardgov_focus")
    win = make_window()
    _import_through_the_action(win, monkeypatch, ref)
    m = win._model
    assert win._status_label.text() == (
        "Imported 8 trees (450 focuses, 89 shared) from 05_Australia.txt — showing "
        "howardgov_focus. Save to keep, or Export into a mod.")
    labels = _combo_labels(win)
    assert labels[0] == "howardgov_focus — 88 focuses + 89 shared"
    assert "miscle_tree_focus — 0 focuses + 89 shared" in labels
    assert "turnbullgov_focus — 1 focus + 89 shared" in labels
    assert len(labels) == 8 and win._tree_combo.currentIndex() == 0

    # Switch through all 8 trees with the switcher (ending back on Howard).
    order = list(range(1, 8)) + [0]
    for index in order:
        win._tree_combo.setCurrentIndex(index)
        tree_id = m.project.treeId
        assert mt.active_index(m.project) == index == win._tree_combo.currentIndex()
        nodes = win._scene._nodes
        assert len(nodes) == EXPECTED_OWN[tree_id] + 89 == len(m.project.focuses)
        assert sum(1 for n in nodes.values() if n.is_shared) == 89
        qapp.processEvents()
    assert m.project.treeId == "howardgov_focus"

    # MD's own same-cell pairs in the (parked) Gillard tree: the error can be
    # reached from the Validation tab.
    from core.validation import get_blocking_issues
    blocking = get_blocking_issues(m.project)
    assert blocking and all(i.treeId == "gillardgov_focus" for i in blocking)
    assert m.reveal_issue(blocking[0]) is True
    assert m.project.treeId == "gillardgov_focus" and m.selected_id == blocking[0].focusId
    assert win._scene._nodes[blocking[0].focusId].isSelected()
    assert win._tree_combo.currentText().startswith("gillardgov_focus — ")

    # Render Howard and Abbott for a visual check.
    for tree_id, path in (("howardgov_focus", PNG_HOWARD),
                          ("australia_abbottgov_focus", PNG_ABBOTT)):
        win._tree_combo.setCurrentIndex(mt.index_of_tree(m.project, tree_id))
        assert m.project.treeId == tree_id
        win._scene.clearSelection()
        _settle_icons(qapp)
        img = _render_canvas(win, path)
        assert img.width() > 500 and img.height() > 300 and os.path.getsize(path) > 10_000
    print(f"\nrendered: {PNG_HOWARD}\nrendered: {PNG_ABBOTT}")
