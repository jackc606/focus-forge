"""Unsaved-changes guard on project-replacing actions, closeEvent reuse of the
same prompt, and the clear-focuses dialog wording.

MainWindow's full __init__ spins up threads / timers / the AI bridge and reads
real QSettings, so these tests use a bare ``MainWindow.__new__`` instance with
just the attributes each method touches (same pattern as the pipeline tests).
Dialogs are monkeypatched at the ui.main_window module level so nothing blocks.
"""
from __future__ import annotations

import os
import types
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import ui.main_window as mw


def _ensure_app():
    return QApplication.instance() or QApplication([])


class _FakeMsgBox:
    """Stand-in for QMessageBox: records calls, returns a scripted answer."""
    Save = QMessageBox.Save
    Discard = QMessageBox.Discard
    Cancel = QMessageBox.Cancel
    Yes = QMessageBox.Yes
    No = QMessageBox.No

    question_answer = Cancel
    question_calls: list = []
    warning_calls: list = []

    @classmethod
    def reset(cls, answer):
        cls.question_answer = answer
        cls.question_calls = []
        cls.warning_calls = []

    @classmethod
    def question(cls, parent, title, text, *args, **kwargs):
        cls.question_calls.append((title, text))
        return cls.question_answer

    @classmethod
    def warning(cls, parent, title, text, *args, **kwargs):
        cls.warning_calls.append((title, text))
        return cls.No

    @classmethod
    def information(cls, parent, title, text, *args, **kwargs):
        return cls.Yes


def _window():
    """Bare MainWindow with a real ProjectModel and no Qt window machinery."""
    _ensure_app()
    from ui.project_model import ProjectModel
    win = mw.MainWindow.__new__(mw.MainWindow)
    win._model = ProjectModel()
    win._view = types.SimpleNamespace(fit_to_content=lambda: None)
    win._bridge = MagicMock()
    win._default_export_dir = None
    return win


def _dirty_window():
    win = _window()
    win._model.add_focus()
    assert win._model.is_dirty()
    return win


# ----- _confirm_discard_changes itself -----
def test_confirm_clean_project_no_prompt(monkeypatch):
    win = _window()
    _FakeMsgBox.reset(_FakeMsgBox.Cancel)
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    assert win._confirm_discard_changes() is True
    assert _FakeMsgBox.question_calls == []      # no prompt when nothing to lose


def test_confirm_cancel_returns_false(monkeypatch):
    win = _dirty_window()
    _FakeMsgBox.reset(_FakeMsgBox.Cancel)
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    assert win._confirm_discard_changes() is False
    assert len(_FakeMsgBox.question_calls) == 1


def test_confirm_discard_returns_true(monkeypatch):
    win = _dirty_window()
    _FakeMsgBox.reset(_FakeMsgBox.Discard)
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    assert win._confirm_discard_changes() is True


def test_confirm_save_success_returns_true(monkeypatch):
    win = _dirty_window()
    _FakeMsgBox.reset(_FakeMsgBox.Save)
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    win._save = lambda: True
    assert win._confirm_discard_changes() is True


def test_confirm_save_cancelled_saveas_returns_false(monkeypatch):
    # Save chosen, but the Save-As dialog was cancelled → the action must abort.
    win = _dirty_window()
    _FakeMsgBox.reset(_FakeMsgBox.Save)
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    win._save = lambda: False
    assert win._confirm_discard_changes() is False


# ----- every project-replacing path consults the guard FIRST -----
def test_open_aborts_when_guard_declines(monkeypatch):
    win = _dirty_window()
    win._confirm_discard_changes = lambda: False
    boom = MagicMock(side_effect=AssertionError("file dialog must not open"))
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", boom)
    win._open()
    boom.assert_not_called()


def test_load_sample_aborts_when_guard_declines():
    win = _dirty_window()
    win._confirm_discard_changes = lambda: False
    before = [f.id for f in win._model.project.focuses]
    win._load_sample()
    assert [f.id for f in win._model.project.focuses] == before
    assert win._model.is_dirty()                 # nothing was discarded


def test_load_sample_proceeds_when_guard_allows():
    win = _dirty_window()
    win._confirm_discard_changes = lambda: True
    win._load_sample()
    assert win._model.is_dirty() is False        # fresh sample project is clean


def test_import_tree_aborts_when_guard_declines():
    win = _dirty_window()
    win._confirm_discard_changes = lambda: False
    win._choose_and_import_tree = MagicMock(
        side_effect=AssertionError("import picker must not open"))
    win._import_tree()
    win._choose_and_import_tree.assert_not_called()


def test_new_submod_aborts_when_guard_declines(monkeypatch):
    win = _dirty_window()
    win._confirm_discard_changes = lambda: False
    boom = MagicMock(side_effect=AssertionError("new-submod dialog must not open"))
    monkeypatch.setattr(mw, "NewSubmodDialog", boom)
    win._new_submod()
    boom.assert_not_called()


def test_welcome_recent_open_respects_guard(monkeypatch):
    class _FakeWelcome:
        def __init__(self, recent=None, parent=None):
            self.choice = "recent"
            self.recent_path = "C:/somewhere/proj.focusforge.json"

        def exec(self):
            return 1

    import ui.welcome_dialog as wd
    monkeypatch.setattr(wd, "WelcomeDialog", _FakeWelcome)

    win = _dirty_window()
    win._recent_projects = lambda: []
    opened = []
    win._open_path = lambda p: opened.append(p)

    win._confirm_discard_changes = lambda: False
    win.show_welcome()
    assert opened == []                          # guarded

    win._confirm_discard_changes = lambda: True
    win.show_welcome()
    assert len(opened) == 1                      # allowed through


# ----- closeEvent goes through the same guard -----
def test_close_event_cancel_keeps_window_open():
    win = _dirty_window()
    win._confirm_discard_changes = lambda: False
    ev = MagicMock()
    win.closeEvent(ev)
    ev.ignore.assert_called_once()
    ev.accept.assert_not_called()
    win._bridge.stop.assert_not_called()


def test_close_event_discard_closes():
    win = _dirty_window()
    win._confirm_discard_changes = lambda: True
    ev = MagicMock()
    win.closeEvent(ev)
    ev.accept.assert_called_once()
    ev.ignore.assert_not_called()
    win._bridge.stop.assert_called_once()        # port released on real close


# ----- finding 6: clear-focuses dialog no longer claims it's not undoable -----
def test_clear_focuses_message_mentions_undo(monkeypatch):
    win = _window()
    _FakeMsgBox.reset(_FakeMsgBox.No)
    monkeypatch.setattr(mw, "QMessageBox", _FakeMsgBox)
    n_before = len(win._model.project.focuses)
    assert n_before > 0
    win._on_clear_focuses()                      # No → nothing deleted
    assert len(win._model.project.focuses) == n_before
    assert len(_FakeMsgBox.warning_calls) == 1
    text = _FakeMsgBox.warning_calls[0][1]
    assert "ctrl+z" in text.lower()
    assert "can't be undone" not in text.lower()
    assert "cannot be undone" not in text.lower()
