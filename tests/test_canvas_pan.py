"""Zoomed-in panning: the scene rect must leave generous slack around the tree
(Qt clamps scroll-based panning to it), and scrollbars stay hidden so they
can't pop in mid-pan and resize the viewport."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.types import ExportSettings, FocusForgeProject, FocusNodeData, FocusPosition


def _app():
    return QApplication.instance() or QApplication([])


def _scene():
    from ui.graph_scene import GraphScene
    proj = FocusForgeProject(
        treeId="t", countryTag="LBA", projectName="p",
        focuses=[FocusNodeData(id=f"f{i}", title=f"F{i}",
                               position=FocusPosition(i % 3, i // 3))
                 for i in range(12)],
        exportSettings=ExportSettings(localisationPrefix="lba_forge"))
    s = GraphScene()
    s.reconcile(proj, "")
    return s


def test_scene_rect_leaves_pan_slack_below_the_tree():
    _app()
    scene = _scene()
    lowest = max(n.sceneBoundingRect().bottom() for n in scene._nodes.values())
    assert scene.sceneRect().bottom() - lowest >= 800   # room to pull the bottom up


def test_scrollbars_always_hidden():
    _app()
    from ui.graph_view import GraphView
    view = GraphView(_scene())
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_wheel_zoom_suppressed_while_panning():
    """MMB is the physical wheel — a fast pan can tick it, which zoomed
    mid-drag. Wheel events during a pan must not change the zoom."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent
    app = _app()
    from ui.graph_view import GraphView
    view = GraphView(_scene())
    view.resize(800, 600)
    view.show()
    app.processEvents()

    def wheel():
        return QWheelEvent(QPoint(400, 300), view.mapToGlobal(QPoint(400, 300)),
                           QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                           Qt.NoModifier, Qt.NoScrollPhase, False)

    zoom = view.transform().m11()
    view._panning = True
    view.wheelEvent(wheel())
    assert view.transform().m11() == zoom      # no zoom mid-pan
    view._panning = False
    view.wheelEvent(wheel())
    assert view.transform().m11() != zoom      # zoom works again after release
