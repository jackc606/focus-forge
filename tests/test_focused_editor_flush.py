"""Finding 7: a value still sitting in a focused QLineEdit (commit-on-
editingFinished) must be flushed into the model before save/export snapshots.

Runs offscreen; widgets are shown+activated so QApplication.focusWidget()
works, and typing goes through QTest so the line edits mark themselves as
user-modified (programmatic setText would not fire editingFinished on
focus-out).
"""
from __future__ import annotations

import json
import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from core.types import ExportSettings, FocusForgeProject, FocusNodeData, FocusPosition


def _ensure_app():
    return QApplication.instance() or QApplication([])


def _focus_widget(app, w):
    """Give ``w`` keyboard focus (offscreen-safe) and verify it took."""
    top = w.window()
    top.show()
    top.activateWindow()
    w.setFocus()
    app.processEvents()
    assert QApplication.focusWidget() is w, "widget did not take focus"


def _proj() -> FocusForgeProject:
    return FocusForgeProject(
        countryTag="LBA", treeId="t", projectName="Original Name",
        focuses=[FocusNodeData(id="LBA_a", title="Alpha",
                               position=FocusPosition(0, 0))],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"))


class _StubProvider(QObject):
    """Minimal icon-provider stand-in so InspectorPanel never scans game files."""
    changed = Signal()
    roots_changed = Signal()
    icons_warmed = Signal()

    def pixmap(self, name):
        return None

    def is_indexed(self):
        return False

    def sprite_exists(self, name):
        return True

    def roots(self):
        return []

    def warm_focus_icons_async(self, icons):
        pass


# ----- the helper itself -----
def test_flush_fires_editing_finished_and_keeps_focus():
    app = _ensure_app()
    from ui.main_window import MainWindow
    holder = QWidget()
    edit = QLineEdit(holder)
    fired = []
    edit.editingFinished.connect(lambda: fired.append(True))
    _focus_widget(app, edit)
    QTest.keyClicks(edit, "hello")
    MainWindow._flush_focused_editor()
    assert fired == [True]                       # commit happened
    app.processEvents()
    assert QApplication.focusWidget() is edit    # caret handed back (autosave case)
    holder.close()


def test_flush_is_noop_without_editor_focus():
    _ensure_app()
    from ui.main_window import MainWindow
    MainWindow._flush_focused_editor()           # nothing focused → no crash


# ----- settings panel: project name lands in the model -----
def test_flush_commits_settings_panel_project_name():
    app = _ensure_app()
    from ui.main_window import MainWindow
    from ui.project_model import ProjectModel
    from ui.settings_panel import SettingsPanel
    m = ProjectModel()
    m.replace_project(_proj())
    panel = SettingsPanel(m)
    _focus_widget(app, panel._project_name)
    QTest.keyClicks(panel._project_name, " Extended")
    typed = panel._project_name.text()
    assert typed.endswith("Extended")
    assert m.project.projectName == "Original Name"   # not committed yet
    MainWindow._flush_focused_editor()
    assert m.project.projectName == typed             # committed by the flush
    panel.close()


# ----- inspector: focus title lands in the model -----
def test_flush_commits_inspector_title(monkeypatch):
    app = _ensure_app()
    import ui.icon_provider as ip
    monkeypatch.setattr(ip, "_INSTANCE", _StubProvider())
    from ui.main_window import MainWindow
    from ui.project_model import ProjectModel
    from ui.inspector_panel import InspectorPanel
    m = ProjectModel()
    m.replace_project(_proj())
    panel = InspectorPanel(m)
    assert m.selected_id == "LBA_a"
    _focus_widget(app, panel._title_edit)
    QTest.keyClicks(panel._title_edit, " Two")
    assert m.find_focus("LBA_a").title == "Alpha"     # still uncommitted
    MainWindow._flush_focused_editor()
    assert m.find_focus("LBA_a").title == "Alpha Two"
    panel.close()


# ----- end to end: Ctrl+S with focus still in the field saves the NEW value -----
def test_save_flushes_focused_editor_into_the_file(tmp_path, monkeypatch):
    app = _ensure_app()
    import ui.main_window as mw
    from ui.project_model import ProjectModel
    from ui.settings_panel import SettingsPanel

    win = mw.MainWindow.__new__(mw.MainWindow)
    win._model = ProjectModel()
    win._push_recent = lambda p: None            # don't touch real QSettings
    path = tmp_path / "p.focusforge.json"
    win._model.replace_project(_proj(), path=path)

    panel = SettingsPanel(win._model)
    _focus_widget(app, panel._project_name)
    QTest.keyClicks(panel._project_name, " Renamed")

    assert win._save() is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["projectName"].endswith("Renamed")   # typed value reached disk
    panel.close()
