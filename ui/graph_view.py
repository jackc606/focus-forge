"""QGraphicsView with pan (middle mouse), zoom (wheel) and a context menu."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsView, QMenu

from .edge_item import EdgeItem
from .focus_node_item import FocusNodeItem

# Zoom-in is clamped to a sensible upper bound; zoom-out floor is computed
# dynamically from the focus tree's bounding rect so the entire tree is
# always at least visible.
ZOOM_MAX = 4.0
ZOOM_OUT_FLOOR = 1.0     # never let the floor exceed 100%
TREE_FIT_MARGIN_PX = 80   # padding around the tree at the minimum zoom


class GraphView(QGraphicsView):
    create_focus_requested = Signal(QPointF)   # scene pos of the right-click
    delete_focus_requested = Signal(str)       # focus id
    delete_focuses_requested = Signal(list)    # focus ids (Delete key on selection)
    add_child_requested = Signal(str)          # parent focus id
    delete_link_requested = Signal(str, str, str)  # source_id, target_id, kind

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Repaint the whole viewport on any change so the strategic-grid
        # background and corner stamps stay anchored to the camera.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._panning = False
        self._pan_start = QPoint()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Delete / Backspace removes every selected (highlighted) focus. Scoped
        # to the canvas, so it never fires while typing in the inspector.
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            ids = [it.focus_id for it in self.scene().selectedItems()
                   if isinstance(it, FocusNodeItem)]
            if ids:
                self.delete_focuses_requested.emit(ids)
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom_by(factor)

    def _zoom_by(self, factor: float) -> None:
        current = self.transform().m11() or 1.0
        target = current * factor
        target = max(self._min_scale(), min(ZOOM_MAX, target))
        if abs(target - current) < 1e-4:
            return
        self.scale(target / current, target / current)

    def _min_scale(self) -> float:
        """Smallest allowed zoom — fits the focus tree, but never above 100%."""
        bounds = self._focus_tree_bounds()
        vw = self.viewport().width()
        vh = self.viewport().height()
        if bounds.isEmpty() or vw <= 0 or vh <= 0:
            return min(ZOOM_OUT_FLOOR, 0.1)
        usable_w = max(vw - 2 * TREE_FIT_MARGIN_PX, 1)
        usable_h = max(vh - 2 * TREE_FIT_MARGIN_PX, 1)
        s_fit = min(usable_w / max(bounds.width(), 1),
                    usable_h / max(bounds.height(), 1))
        return min(s_fit, ZOOM_OUT_FLOOR)

    def _focus_tree_bounds(self) -> QRectF:
        scene = self.scene()
        nodes = getattr(scene, "_nodes", None) or {}
        if not nodes:
            return QRectF()
        rects = [n.sceneBoundingRect() for n in nodes.values()]
        united = rects[0]
        for r in rects[1:]:
            united = united.united(r)
        return united

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _node_at(self, view_pos):
        for it in self.items(view_pos):
            if isinstance(it, FocusNodeItem):
                return it
        return None

    def _edge_at(self, view_pos):
        for it in self.items(view_pos):
            if isinstance(it, EdgeItem):
                return it
        return None

    def contextMenuEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.pos())
        node = self._node_at(event.pos())
        edge = None if node is not None else self._edge_at(event.pos())
        menu = QMenu(self)

        if node is not None:
            child_act = menu.addAction("Add child focus")
            menu.addSeparator()
            fid = node.focus_id
            label = fid if len(fid) <= 28 else fid[:25] + "…"
            del_act = menu.addAction(f"Delete  “{label}”")
            chosen = menu.exec(event.globalPos())
            if chosen is child_act:
                self.add_child_requested.emit(node.focus_id)
            elif chosen is del_act:
                self.delete_focus_requested.emit(node.focus_id)
            return

        new_act = menu.addAction("New Focus Here")
        unlink_act = None
        if edge is not None:
            verb = "mutual exclusivity" if edge.kind == "mutex" else "connection"
            unlink_act = menu.addAction(f"Delete {verb}")
        chosen = menu.exec(event.globalPos())
        if chosen is new_act:
            self.create_focus_requested.emit(scene_pos)
        elif unlink_act is not None and chosen is unlink_act:
            self.delete_link_requested.emit(edge.source_id, edge.target_id, edge.kind)

    def fit_to_content(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
