"""Unsaved-changes (dirty) tracking on the project model."""
from __future__ import annotations

from core.types import FocusForgeProject, FocusNodeData, FocusPosition
from ui.project_model import ProjectModel


def _proj():
    return FocusForgeProject(countryTag="LBA", treeId="t", focuses=[
        FocusNodeData(id="LBA_a", title="A", position=FocusPosition(0, 0))])


def test_fresh_model_is_clean():
    assert ProjectModel().is_dirty() is False


def test_mutation_marks_dirty():
    m = ProjectModel()
    m.replace_project(_proj(), path=None)
    assert m.is_dirty() is False           # load is clean
    m.add_focus_at(2, 2)
    assert m.is_dirty() is True


def test_save_clears_dirty(tmp_path):
    m = ProjectModel()
    m.replace_project(_proj(), path=None)
    m.add_focus_at(2, 2)
    assert m.is_dirty() is True
    m.save_to_file(tmp_path / "p.focusforge.json")
    assert m.is_dirty() is False


def test_dirty_changed_signal():
    m = ProjectModel()
    m.replace_project(_proj(), path=None)
    seen = []
    m.dirty_changed.connect(seen.append)
    m.add_focus_at(2, 2)          # False -> True (one emit)
    m.add_focus_at(3, 3)          # stays True (no emit)
    assert seen == [True]
