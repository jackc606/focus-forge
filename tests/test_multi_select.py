"""Multi-select on the canvas: Ctrl+click extension, rubber-band sets, and
group drags must survive (a) the click → model → select_node echo and (b) the
reconcile that runs on every project change (including every grid step of a
drag). Wired exactly like MainWindow wires scene ↔ model."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.types import ExportSettings, FocusForgeProject, FocusNodeData, FocusPosition


def _ensure_app():
    return QApplication.instance() or QApplication([])


def _proj(n=3) -> FocusForgeProject:
    return FocusForgeProject(
        treeId="t", countryTag="LBA", projectName="p",
        focuses=[FocusNodeData(id=f"f{i}", title=f"F{i}",
                               position=FocusPosition(i, 0)) for i in range(n)],
        exportSettings=ExportSettings(localisationPrefix="lba_forge"))


def _harness():
    """ProjectModel + GraphScene connected the way MainWindow connects them."""
    from core.types import FocusPosition
    from ui.graph_scene import GraphScene
    from ui.project_model import ProjectModel

    model = ProjectModel()
    model.replace_project(_proj())
    scene = GraphScene()
    scene.node_clicked.connect(model.set_selection)
    scene.node_moved.connect(
        lambda fid, gx, gy: model.update_focus(fid, position=FocusPosition(x=gx, y=gy)))
    model.selection_changed.connect(scene.select_node)
    model.project_changed.connect(
        lambda: scene.reconcile(model.project, model.selected_id))
    scene.reconcile(model.project, model.selected_id)
    return model, scene


def _selected(scene):
    return {fid for fid, n in scene._nodes.items() if n.isSelected()}


def test_click_echo_does_not_collapse_multi_selection():
    _ensure_app()
    model, scene = _harness()
    # User rubber-bands / Ctrl+clicks f0+f1 (Qt native), last click lands on f1:
    scene._nodes["f0"].setSelected(True)
    scene._nodes["f1"].setSelected(True)
    scene.node_clicked.emit("f1")           # the click → model → select_node echo
    assert model.selected_id == "f1"
    assert _selected(scene) == {"f0", "f1"}  # extension survived the echo


def test_programmatic_selection_still_collapses():
    _ensure_app()
    model, scene = _harness()
    scene._nodes["f0"].setSelected(True)
    scene._nodes["f1"].setSelected(True)
    model.set_selection("f2")                # list-panel / undo style change
    assert _selected(scene) == {"f2"}


def test_reconcile_preserves_multi_selection():
    _ensure_app()
    model, scene = _harness()
    scene._nodes["f0"].setSelected(True)
    scene._nodes["f1"].setSelected(True)
    model.update_focus("f2", title="renamed")   # any edit → project_changed → reconcile
    assert _selected(scene) == {"f0", "f1"}


def test_new_node_takes_selection_on_reconcile():
    _ensure_app()
    model, scene = _harness()
    new_id = model.add_focus()
    assert scene._nodes[new_id].isSelected()


def test_group_drag_commits_every_selected_node():
    _ensure_app()
    from ui.focus_node_item import GRID_X, GRID_Y
    model, scene = _harness()
    a, b = scene._nodes["f0"], scene._nodes["f1"]
    a.setSelected(True)
    b.setSelected(True)
    # Qt moves all selected items together; emulate one grid-step of that drag.
    # Each setPos triggers itemChange → position_committed → model.update_focus
    # → project_changed → reconcile, i.e. the full mid-drag cascade.
    a.setPos(a.x(), a.y() + GRID_Y)
    b.setPos(b.x(), b.y() + GRID_Y)
    assert model.find_focus("f0").position.y == 1
    assert model.find_focus("f1").position.y == 1
    assert _selected(scene) == {"f0", "f1"}   # selection survived both reconciles
    # ...and the whole gesture stays draggable: one more step.
    a.setPos(a.x(), a.y() + GRID_Y)
    b.setPos(b.x(), b.y() + GRID_Y)
    assert model.find_focus("f0").position.y == 2
    assert model.find_focus("f1").position.y == 2
    assert _selected(scene) == {"f0", "f1"}


def test_ctrl_deselect_does_not_reselect_via_echo():
    _ensure_app()
    model, scene = _harness()
    scene._nodes["f0"].setSelected(True)
    scene._nodes["f1"].setSelected(True)
    # Ctrl+click on f1 toggles it OFF (Qt native). The node announces the click
    # only while selected — a deselect press must not echo:
    scene._nodes["f1"].setSelected(False)
    # (guard lives in FocusNodeItem.mousePressEvent: clicked fires only when
    # isSelected(); simulate its contract here)
    if scene._nodes["f1"].isSelected():
        scene.node_clicked.emit("f1")
    assert _selected(scene) == {"f0"}         # stays deselected


def test_multi_delete_selection_set(qapp=None):
    _ensure_app()
    model, scene = _harness()
    scene._nodes["f0"].setSelected(True)
    scene._nodes["f2"].setSelected(True)
    ids = [it.focus_id for it in scene.selectedItems()
           if hasattr(it, "focus_id")]
    model.delete_focuses(ids)
    assert {f.id for f in model.project.focuses} == {"f1"}
