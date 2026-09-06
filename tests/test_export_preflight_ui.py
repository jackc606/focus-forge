"""Offscreen smoke for the existing-tree collision UI: the export pre-flight
dialog + its model changes, the import dialog's replace/copy panel, and the
Export tab's status line. Panels are built directly (never MainWindow — it
auto-starts the TCP bridge), following tests/test_canvas_pan.py."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core import tree_index as TI
from core.serialization import project_to_dict
from core.tree_index import current_index, find_collisions, scan_base_trees
from core.types import FocusShortcut
from ui.project_model import ProjectModel

from tests.test_tree_index import NIGERIA, _project, _root


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _fresh_index_cache():
    TI.invalidate()
    yield
    TI.invalidate()


def _model(project):
    m = ProjectModel()
    m.replace_project(project, path=None)
    return m


# ----- pre-flight dialog + choices ----------------------------------------------------
def test_no_problem_means_no_dialog(qapp, tmp_path, monkeypatch):
    from ui import export_preflight as EP
    roots = _root(tmp_path)
    m = _model(_project(file_name="05_nigeria", tree_id="nigeria_focus"))

    def boom(*_a, **_k):
        raise AssertionError("dialog must not open when nothing collides")
    monkeypatch.setattr(EP, "ExportPreflightDialog", boom)
    assert EP.run_export_preflight(None, m, roots) is True
    assert EP.run_export_preflight(None, m, []) is True          # no roots → can't check → go


def test_problem_opens_dialog_and_replace_sets_file_name(qapp, tmp_path, monkeypatch):
    from ui import export_preflight as EP
    roots = _root(tmp_path)
    m = _model(_project())
    assert not m.is_dirty()
    opened = []

    class FakeDialog(EP.ExportPreflightDialog):
        def exec(self):
            opened.append(self)
            self.replace_btn.click()      # the primary "replace MD's tree" button
            return 1
    monkeypatch.setattr(EP, "ExportPreflightDialog", FakeDialog)
    assert EP.run_export_preflight(None, m, roots) is True
    assert len(opened) == 1
    dlg = opened[0]
    assert dlg.windowTitle() == "Your export would break the tree in-game"
    assert "05_nigeria" in dlg.replace_btn.text()
    assert dlg.choice == EP.CHOICE_REPLACE
    assert m.project.exportSettings.focusFileName == "05_nigeria"
    assert m.project.source.get("mode") == "replace"
    assert m.is_dirty()
    assert not find_collisions(m.project, scan_base_trees(roots)).is_problem
    m.undo()
    assert m.project.exportSettings.focusFileName == "nga_focus"   # undoable


def test_dialog_buttons_report_their_choice(qapp, tmp_path):
    from ui import export_preflight as EP
    report = find_collisions(_project(), scan_base_trees(_root(tmp_path)))
    for attr, choice in (("prefix_btn", EP.CHOICE_PREFIX), ("anyway_btn", EP.CHOICE_ANYWAY),
                         ("cancel_btn", EP.CHOICE_CANCEL)):
        dlg = EP.ExportPreflightDialog(report)
        getattr(dlg, attr).click()
        assert dlg.choice == choice
    assert EP.apply_choice(None, _model(_project()), report, EP.CHOICE_ANYWAY) is True
    assert EP.apply_choice(None, _model(_project()), report, EP.CHOICE_CANCEL) is False


def test_prefix_path_renames_everything_in_one_undo_step(qapp, tmp_path, monkeypatch):
    from ui import export_preflight as EP
    roots = _root(tmp_path)
    proj = _project()
    proj.focuses[1].prerequisites = ["NGA_a"]
    proj.focuses[1].mutuallyExclusive = ["NGA_a"]
    proj.shortcuts = [FocusShortcut(label="Go", target="NGA_b")]
    m = _model(proj)
    before = project_to_dict(m.project)
    monkeypatch.setattr(EP, "ask_prefix", lambda parent, default: "NGA_NEW")
    report = find_collisions(m.project, scan_base_trees(roots))
    assert EP.apply_choice(None, m, report, EP.CHOICE_PREFIX) is True
    ids = [f.id for f in m.project.focuses]
    assert ids == ["NGA_NEW_NGA_a", "NGA_NEW_NGA_b"]
    assert m.project.focuses[1].prerequisites == ["NGA_NEW_NGA_a"]
    assert m.project.focuses[1].mutuallyExclusive == ["NGA_NEW_NGA_a"]
    assert m.project.shortcuts[0].target == "NGA_NEW_NGA_b"
    assert m.project.treeId == "nga_new_focus"
    assert m.project.exportSettings.focusFileName == "nga_new_focus"
    assert m.project.source.get("mode") == "copy"
    assert not find_collisions(m.project, scan_base_trees(roots)).is_problem
    assert m.is_dirty()
    # ONE undo restores everything.
    assert m.undo()
    assert project_to_dict(m.project) == before
    assert not m.can_undo()


def test_prefix_prompt_cancel_aborts_export(qapp, tmp_path, monkeypatch):
    from ui import export_preflight as EP
    roots = _root(tmp_path)
    m = _model(_project())
    monkeypatch.setattr(EP, "ask_prefix", lambda parent, default: None)
    report = find_collisions(m.project, scan_base_trees(roots))
    assert EP.apply_choice(None, m, report, EP.CHOICE_PREFIX) is False
    assert [f.id for f in m.project.focuses] == ["NGA_a", "NGA_b"]


def test_prefix_validation_messages():
    from ui.export_preflight import prefix_problem
    assert prefix_problem("NGA_NEW") == ""
    assert prefix_problem("") and prefix_problem("1abc") and prefix_problem("a b") and prefix_problem("a-b")


# ----- import dialog: replace / copy panel --------------------------------------------
def test_import_dialog_shows_replace_panel_for_base_tree(qapp, tmp_path):
    from ui.import_tree_dialog import ImportTreeDialog
    roots = _root(tmp_path)
    dlg = ImportTreeDialog(roots)
    assert dlg._replace_panel.isVisibleTo(dlg) is False       # nothing selected yet
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
    assert dlg._replace_panel.isVisibleTo(dlg) is True
    text = dlg._replace_label.text()
    assert "Millennium Dawn's" in text and "05_nigeria.txt" in text and "REPLACE" in text
    assert "Nigeria" in text                                    # country name, not just the tag
    assert dlg._copy_row.isVisibleTo(dlg) is False
    # Default = replace: the ref carries no prefix.
    dlg._accept_selected()
    ref = dlg.selected_ref()
    assert ref.id_prefix == "" and ref.tag == "NIG"


def test_import_dialog_copy_checkbox_sets_prefix(qapp, tmp_path, monkeypatch):
    from ui import import_tree_dialog as ITD
    roots = _root(tmp_path)
    dlg = ITD.ImportTreeDialog(roots)
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
    dlg._copy_check.setChecked(True)
    assert dlg._copy_row.isVisibleTo(dlg) is True
    assert dlg._prefix_edit.text() == "NIG_NEW"
    assert dlg.copy_prefix() == "NIG_NEW"
    # An illegal prefix is refused (warning shown, dialog stays open).
    warned = []
    monkeypatch.setattr(ITD.QMessageBox, "warning", lambda *a, **k: warned.append(a))
    dlg._prefix_edit.setText("1 bad")
    dlg._accept_selected()
    assert warned and dlg.selected_ref() is None
    dlg._prefix_edit.setText("NGA_NEW")
    dlg._accept_selected()
    ref = dlg.selected_ref()
    assert ref.id_prefix == "NGA_NEW"
    # The cached discovery ref is untouched (the prefix lives on a copy).
    assert dlg._refs[0].id_prefix == ""


def test_import_dialog_panel_hidden_for_adhoc_folder_trees(qapp, tmp_path):
    from core.focus_import import find_focus_trees_in_folder
    from ui.import_tree_dialog import ImportTreeDialog
    roots = _root(tmp_path)
    other = tmp_path / "other_mod"
    _root(other, "10_ghana.txt", NIGERIA.replace("nigeria_focus", "ghana_focus")
          .replace("NGA", "GHA"))
    dlg = ImportTreeDialog(roots)
    found = find_focus_trees_in_folder(str(other), [*roots, str(other)])
    dlg._refs.extend(found)
    dlg._populate()
    dlg._select_ref(found[0])
    assert dlg._replace_panel.isVisibleTo(dlg) is False


# ----- export panel status line -----------------------------------------------------
def test_export_panel_status_line(qapp, tmp_path, monkeypatch):
    from ui import export_panel as XP
    roots = _root(tmp_path)
    current_index(lambda: roots)                 # warm the shared cache (blocking)
    monkeypatch.setattr(XP, "_configured_roots", lambda: roots)
    m = _model(_project())
    panel = XP.ExportPanel(m)
    assert "Would duplicate MD's 05_nigeria.txt" in panel._status.text()
    assert panel._fix_btn.isVisibleTo(panel) is True
    assert panel._status.objectName() == "pillError"

    m.update_export_settings(focusFileName="05_nigeria")
    panel._refresh_status()
    assert panel._status.text().startswith("Replaces Millennium Dawn's 05_nigeria.txt")
    assert panel._fix_btn.isVisibleTo(panel) is False
    assert panel._status.objectName() == "pillOk"

    m.update_export_settings(focusFileName="brand_new")
    m.update_project_meta(treeId="brand_new_focus")
    for f in m.project.focuses:
        f.id = "X_" + f.id
    panel._refresh_status()
    assert panel._status.text() == "New tree (brand_new.txt)"
    assert panel._status.objectName() == "pillNeutral"

    monkeypatch.setattr(XP, "_configured_roots", lambda: [])
    panel._refresh_status()
    assert "MD folder not configured" in panel._status.text()
    assert panel._fix_btn.isVisibleTo(panel) is False


def test_export_panel_fix_button_runs_preflight(qapp, tmp_path, monkeypatch):
    from ui import export_panel as XP
    from ui import export_preflight as EP
    roots = _root(tmp_path)
    current_index(lambda: roots)
    monkeypatch.setattr(XP, "_configured_roots", lambda: roots)
    m = _model(_project())
    panel = XP.ExportPanel(m)

    class FakeDialog(EP.ExportPreflightDialog):
        def exec(self):
            self.replace_btn.click()
            return 1
    monkeypatch.setattr(EP, "ExportPreflightDialog", FakeDialog)
    panel._fix_btn.click()
    assert m.project.exportSettings.focusFileName == "05_nigeria"
    assert panel._status.text().startswith("Replaces Millennium Dawn's")


def test_validation_panel_renders_collision_as_error(qapp, tmp_path):
    from core.tree_index import collision_issues
    from ui.validation_panel import ValidationPanel
    m = _model(_project())
    issues = collision_issues(find_collisions(m.project, scan_base_trees(_root(tmp_path))))
    panel = ValidationPanel(m)
    panel.refresh(issues)
    cards = [panel._issues_box.itemAt(i).widget() for i in range(panel._issues_box.count())]
    assert len(cards) == 1 and cards[0].objectName() == "issueCardError"
