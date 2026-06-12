"""Connector between two focus nodes.

Two kinds, both drawn the way HOI4 renders them in-game:
- ``prereq``: an orthogonal (right-angle) line flowing top-down from a parent's
  bottom edge into a child's top edge — solid, light steel-blue (the in-game
  colour for an incomplete prerequisite). No arrowheads (the game has none).
- ``mutex``: a red link between two mutually-exclusive focuses.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from . import theme as T
from .focus_node_item import ICON, ICON_Y, NODE_H, NODE_W, FocusNodeItem

_ICON_MID_Y = ICON_Y + ICON / 2  # vertical centre of the icon frame


class EdgeItem(QGraphicsPathItem):
    def __init__(self, source: FocusNodeItem, target: FocusNodeItem, kind: str = "prereq") -> None:
        super().__init__()
        self._source = source
        self._target = target
        self._kind = kind
        self.setZValue(-1)
        color = QColor(T.MUTEX_LINE if kind == "mutex" else T.PREREQ_LINE)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.SquareCap)
        pen.setJoinStyle(Qt.MiterJoin)
        pen.setCosmetic(True)  # constant on-screen weight, like the grid
        self.setPen(pen)
        self._shape_cache = None  # widened hit path, rebuilt when the path moves
        self.refresh()

    @property
    def kind(self) -> str:
        return self._kind

    def shape(self) -> QPainterPath:
        # Widen the hit area so the thin line is easy to right-click. Cached —
        # shape() runs on every hover/click hit-test over the scene.
        if self._shape_cache is None:
            stroker = QPainterPathStroker()
            stroker.setWidth(10)
            self._shape_cache = stroker.createStroke(self.path())
        return self._shape_cache

    @property
    def source_id(self) -> str:
        return self._source.focus_id

    @property
    def target_id(self) -> str:
        return self._target.focus_id

    def refresh(self) -> None:
        self._shape_cache = None
        if self._kind == "mutex":
            self.setPath(self._mutex_path())
        else:
            self.setPath(self._prereq_path())

    def _prereq_path(self) -> QPainterPath:
        s = self._source.scenePos()
        t = self._target.scenePos()
        s_pt = QPointF(s.x() + NODE_W / 2, s.y() + NODE_H)  # parent bottom-centre
        t_pt = QPointF(t.x() + NODE_W / 2, t.y())           # child top-centre
        mid_y = (s_pt.y() + t_pt.y()) / 2
        path = QPainterPath()
        path.moveTo(s_pt)
        path.lineTo(QPointF(s_pt.x(), mid_y))
        path.lineTo(QPointF(t_pt.x(), mid_y))
        path.lineTo(t_pt)
        return path

    def _mutex_path(self) -> QPainterPath:
        s = self._source.scenePos()
        t = self._target.scenePos()
        # Order left→right by scene x so the link exits the inner edges.
        if s.x() <= t.x():
            left, right = s, t
        else:
            left, right = t, s
        l_pt = QPointF(left.x() + NODE_W, left.y() + _ICON_MID_Y)
        r_pt = QPointF(right.x(), right.y() + _ICON_MID_Y)
        path = QPainterPath()
        path.moveTo(l_pt)
        if abs(l_pt.y() - r_pt.y()) < 0.5:
            path.lineTo(r_pt)
        else:
            mid_x = (l_pt.x() + r_pt.x()) / 2
            path.lineTo(QPointF(mid_x, l_pt.y()))
            path.lineTo(QPointF(mid_x, r_pt.y()))
            path.lineTo(r_pt)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())
