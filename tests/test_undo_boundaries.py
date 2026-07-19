"""Regression tests for undo-boundary ordering and ``replace_project`` behavior.

These run WITH a (offscreen) QApplication on purpose: with an app instance the
model defers mid-burst snapshot materialization to a QTimer, which is exactly
the condition under which the boundary-ordering bugs reproduced. Without an
app the model materializes eagerly and the bugs are invisible.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.types import (
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    iter_prereq_ids,
)


def _ensure_app():
    return QApplication.instance() or QApplication([])


def _model(coalesce: float = 60.0):
    _ensure_app()
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m._undo_coalesce_s = coalesce  # aggressive window: everything coalesces
    return m


def _proj(mutex: bool = False) -> FocusForgeProject:
    ab = ["LBA_b"] if mutex else []
    ba = ["LBA_a"] if mutex else []
    return FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[
            FocusNodeData(id="LBA_a", title="A", position=FocusPosition(0, 0),
                          mutuallyExclusive=list(ab)),
            FocusNodeData(id="LBA_b", title="B", position=FocusPosition(1, 0),
                          prerequisites=["LBA_a"], mutuallyExclusive=list(ba)),
        ],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"))


def _burst(m, fid="LBA_a"):
    """Simulate typing: several coalescing edits (materialization stays pending)."""
    for t in ("X", "XY", "XYZ"):
        m.update_focus(fid, title=t)


# ----- finding 1: _force_undo_boundary must materialize the pending burst -----
def test_structural_op_after_burst_is_its_own_undo_step():
    m = _model()
    m.replace_project(_proj())
    _burst(m)                      # typing burst, snapshot left stale
    m.delete_focus("LBA_b")        # structural op inside the coalescing window
    assert m.find_focus("LBA_b") is None
    assert m.undo()                # first undo: ONLY the delete comes back
    assert m.find_focus("LBA_b") is not None
    assert m.find_focus("LBA_a").title == "XYZ"   # the typing survived undo #1
    assert m.undo()                # second undo: the typing burst
    assert m.find_focus("LBA_a").title == "A"


def test_undo_depth_grows_when_burst_is_followed_by_structural_op():
    m = _model()
    m.replace_project(_proj())
    _burst(m)
    depth_after_burst = len(m._undo_stack)
    m.delete_focus("LBA_b")
    assert len(m._undo_stack) == depth_after_burst + 1


def test_drag_then_add_focus_makes_two_undo_steps():
    m = _model()
    m.replace_project(_proj())
    # Simulate a node drag: coalescing position updates.
    for x in (1, 2, 3):
        m.update_focus("LBA_a", position=FocusPosition(x=x, y=0))
    new_id = m.add_focus_at(5, 5)
    assert m.undo()                                    # undo the add only
    assert m.find_focus(new_id) is None
    assert int(m.find_focus("LBA_a").position.x) == 3  # drag intact
    assert m.undo()                                    # undo the drag
    assert int(m.find_focus("LBA_a").position.x) == 0


# ----- finding 2: remove_prerequisite / remove_mutex / set_mutually_exclusive -----
def test_remove_prerequisite_is_its_own_undo_step():
    m = _model()
    m.replace_project(_proj())
    _burst(m)
    msg = m.remove_prerequisite("LBA_b", "LBA_a")
    assert msg
    assert list(iter_prereq_ids(m.find_focus("LBA_b").prerequisites)) == []
    assert m.undo()
    assert list(iter_prereq_ids(m.find_focus("LBA_b").prerequisites)) == ["LBA_a"]
    assert m.find_focus("LBA_a").title == "XYZ"   # typing NOT swept into this undo


def test_remove_mutex_is_its_own_undo_step():
    m = _model()
    m.replace_project(_proj(mutex=True))
    _burst(m)
    msg = m.remove_mutex("LBA_a", "LBA_b")
    assert msg
    assert m.find_focus("LBA_a").mutuallyExclusive == []
    assert m.find_focus("LBA_b").mutuallyExclusive == []
    assert m.undo()
    assert m.find_focus("LBA_a").mutuallyExclusive == ["LBA_b"]
    assert m.find_focus("LBA_b").mutuallyExclusive == ["LBA_a"]
    assert m.find_focus("LBA_a").title == "XYZ"


def test_set_mutually_exclusive_is_its_own_undo_step():
    m = _model()
    m.replace_project(_proj())
    _burst(m)
    msg = m.set_mutually_exclusive("LBA_a", "LBA_b")
    assert msg
    assert m.find_focus("LBA_a").mutuallyExclusive == ["LBA_b"]
    assert m.undo()
    assert m.find_focus("LBA_a").mutuallyExclusive == []
    assert m.find_focus("LBA_b").mutuallyExclusive == []
    assert m.find_focus("LBA_a").title == "XYZ"


def test_noop_remove_mutex_burns_no_undo_step():
    m = _model()
    m.replace_project(_proj())      # no mutex present
    depth = len(m._undo_stack)
    assert m.remove_mutex("LBA_a", "LBA_b") == ""
    assert len(m._undo_stack) == depth


def test_noop_remove_prerequisite_burns_no_undo_step():
    m = _model()
    m.replace_project(_proj())
    depth = len(m._undo_stack)
    assert m.remove_prerequisite("LBA_a", "LBA_b") == ""   # a has no prereqs
    assert len(m._undo_stack) == depth


# ----- finding 1 (second half): replace_project clears burst bookkeeping -----
def test_first_edit_after_replace_project_is_undoable_mid_burst():
    m = _model()
    m.replace_project(_proj())
    _burst(m)                       # leaves _last_mutation recent + state stale
    m.replace_project(_proj())      # e.g. File→Open right after typing
    assert not m.can_undo()
    assert m._state_stale is False
    m.update_focus("LBA_a", title="first edit after import")
    assert m.can_undo()
    assert m.undo()
    assert m.find_focus("LBA_a").title == "A"


# ----- finding 3: replace_project announces the (new) selection -----
def test_replace_project_emits_selection_changed_after_project_changed():
    m = _model()
    order = []
    m.project_changed.connect(lambda: order.append("project"))
    m.selection_changed.connect(lambda s: order.append(("selection", s)))
    m.replace_project(_proj())
    assert ("selection", "LBA_a") in order
    assert order.index("project") < order.index(("selection", "LBA_a"))
    assert m.selected_id == "LBA_a"


def test_replace_project_with_empty_project_announces_empty_selection():
    m = _model()
    seen = []
    m.selection_changed.connect(seen.append)
    m.replace_project(FocusForgeProject(
        countryTag="LBA", treeId="t", focuses=[],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge")))
    assert seen[-1] == ""


# ----- finding 4: replace_project dirty flag -----
def test_replace_project_defaults_to_clean():
    m = _model()
    m.add_focus()
    m.replace_project(_proj())
    assert m.is_dirty() is False


def test_replace_project_dirty_true_marks_unsaved():
    m = _model()
    m.replace_project(_proj(), dirty=True)
    assert m.is_dirty() is True


def test_llm_import_marks_project_dirty():
    import json
    from core.serialization import project_to_dict
    from ui.llm_panel import LlmPanel
    m = _model()
    m.replace_project(_proj())      # clean baseline
    panel = LlmPanel(m)
    edited = project_to_dict(_proj())
    edited["projectName"] = "LLM Edited"
    panel._area.setPlainText("```json\n" + json.dumps(edited) + "\n```")
    panel._import()
    assert m.project.projectName == "LLM Edited"
    assert m.is_dirty() is True     # imported-but-unsaved must not read as clean


# ----- batch(): atomic, single-undo-step, single-notify -----
def test_batch_emits_project_changed_exactly_once():
    m = _model()
    m.replace_project(_proj())
    count = []
    m.project_changed.connect(lambda: count.append(1))
    with m.batch():
        for i in range(5):
            m.add_focus_at(10 + i, 0)
    assert len(count) == 1                 # the canvas repaints once, not 5 times
    assert len(m.project.focuses) == 2 + 5


def test_batch_emits_selection_changed_exactly_once():
    # add_focus_at moves the selection per call; inside a batch those must be
    # silenced (blockSignals) with ONE re-announce at the end, or a 200-op
    # batch rebuilds the inspector 200 times.
    m = _model()
    m.replace_project(_proj())
    seen = []
    m.selection_changed.connect(seen.append)
    with m.batch():
        for i in range(5):
            m.add_focus_at(10 + i, 0)
    assert len(seen) == 1
    assert seen[0] == m.selected_id        # final selection, not an intermediate


def test_batch_is_one_undo_step_even_after_a_pending_burst():
    m = _model()
    m.replace_project(_proj())
    _burst(m)                              # typing burst, snapshot left stale
    with m.batch():
        m.add_focus_at(10, 0)
        m.add_focus_at(11, 0)
    assert m.undo()                        # undo #1: ONLY the batch
    assert len(m.project.focuses) == 2
    assert m.find_focus("LBA_a").title == "XYZ"   # the typing survived undo #1
    assert m.undo()                        # undo #2: the typing burst
    assert m.find_focus("LBA_a").title == "A"


def test_batch_rollback_restores_state_and_emits_once():
    from core.serialization import project_to_dict
    m = _model()
    m.replace_project(_proj())
    before = project_to_dict(m.project)
    depth = len(m._undo_stack)
    count = []
    m.project_changed.connect(lambda: count.append(1))
    try:
        with m.batch():
            m.add_focus_at(10, 0)
            raise ValueError("boom")
    except ValueError:
        pass
    assert project_to_dict(m.project) == before
    assert len(m._undo_stack) == depth     # stacks untouched by the rollback
    assert len(count) == 1                 # the single rollback notify


def test_batch_rollback_keeps_clean_project_clean():
    m = _model()
    m.replace_project(_proj())             # clean baseline
    assert m.is_dirty() is False
    try:
        with m.batch():
            m.add_focus_at(10, 0)
            raise ValueError("boom")
    except ValueError:
        pass
    assert m.is_dirty() is False           # nothing was applied -> still clean


def test_batch_success_marks_dirty_once():
    m = _model()
    m.replace_project(_proj())
    seen = []
    m.dirty_changed.connect(seen.append)
    with m.batch():
        m.add_focus_at(10, 0)
        m.add_focus_at(11, 0)
    assert m.is_dirty() is True
    assert seen == [True]


def test_nested_batch_raises_and_outer_rolls_back():
    m = _model()
    m.replace_project(_proj())
    n = len(m.project.focuses)
    import pytest
    with pytest.raises(RuntimeError):
        with m.batch():
            m.add_focus_at(10, 0)
            with m.batch():
                pass  # pragma: no cover
    assert len(m.project.focuses) == n     # outer batch rolled back too


# ----- finding 6 support: "clear all focuses" really is undoable -----
def test_clear_all_focuses_is_undoable():
    m = _model()
    m.replace_project(_proj())
    n = len(m.project.focuses)
    m.delete_focuses([f.id for f in m.project.focuses])
    assert len(m.project.focuses) == 0
    assert m.undo()
    assert len(m.project.focuses) == n
