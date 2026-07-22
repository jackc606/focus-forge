"""QGraphicsView with pan (middle mouse), zoom (wheel) and a context menu."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsView, QMenu

from .edge_item import EdgeItem
from .focus_node_item import GRID_X, GRID_Y, NODE_H, NODE_W, FocusNodeItem
from .minimap import MinimapOverlay

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
    add_shortcut_requested = Signal(str)       # focus id to bookmark as a tree shortcut
    delete_link_requested = Signal(str, str, str)  # source_id, target_id, kind
    group_prereq_requested = Signal(str, str)    # source_id, target_id — make OR alternative
    ungroup_prereq_requested = Signal(str, str)  # source_id, target_id — make required (AND)
    paste_requested = Signal(QPointF)          # scene pos to paste copied focuses at

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        # Always off: MMB-pan + wheel-zoom are the navigation model, and
        # as-needed scrollbars popping in at the edges resized the viewport
        # mid-pan (the "canvas jumps around while dragging" complaint).
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Repaint only the bounding rect of what changed — NOT the whole
        # viewport. With a 700+ focus tree fitted on screen, full-viewport
        # repaints (one per hover/select/drag-cell) made the canvas unusable;
        # the background is now scene-consistent so per-region updates are safe.
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self._panning = False
        self._pan_start = QPoint()
        self._minimap = MinimapOverlay(self)
        self._minimap.reposition()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._minimap.reposition()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)
        # Keep the minimap's viewport rectangle live during pans/zooms — its
        # own paint is a cached-pixmap blit plus one rect, so this is cheap.
        self._minimap.update()

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
        # MMB *is* the wheel — holding it to pan and moving fast makes the
        # wheel physically tick, which zoomed mid-pan. No zooming while panning.
        if self._panning:
            event.accept()
            return
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

    # ----- paste-position helpers -----
    @staticmethod
    def scene_to_grid(scene_pos) -> tuple:
        """Snap a scene point to the focus grid cell whose node would be CENTRED
        on the point (matches right-click 'New Focus Here')."""
        gx = round((scene_pos.x() - NODE_W / 2) / GRID_X)
        gy = round((scene_pos.y() - NODE_H / 2) / GRID_Y)
        return int(gx), int(gy)

    def paste_anchor_scene(self) -> QPointF:
        """Scene point to anchor a Ctrl+V paste at: under the cursor when it's
        over this view, otherwise the centre of the visible area."""
        vp = self.viewport()
        local = vp.mapFromGlobal(QCursor.pos())
        if not vp.rect().contains(local):
            local = vp.rect().center()
        return self.mapToScene(local)

    @staticmethod
    def _clipboard_has_focuses() -> bool:
        # Cheap peek — avoid a full JSON parse just to decide the menu item.
        return '"focuses"' in (QApplication.clipboard().text() or "")

    def contextMenuEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.pos())
        node = self._node_at(event.pos())
        edge = None if node is not None else self._edge_at(event.pos())
        menu = QMenu(self)

        if node is not None:
            child_act = menu.addAction("Add child focus")
            shortcut_act = menu.addAction("Add tree shortcut")
            menu.addSeparator()
            fid = node.focus_id
            label = fid if len(fid) <= 28 else fid[:25] + "…"
            del_act = menu.addAction(f"Delete  “{label}”")
            chosen = menu.exec(event.globalPos())
            if chosen is child_act:
                self.add_child_requested.emit(node.focus_id)
            elif chosen is shortcut_act:
                self.add_shortcut_requested.emit(node.focus_id)
            elif chosen is del_act:
                self.delete_focus_requested.emit(node.focus_id)
            return

        new_act = menu.addAction("New Focus Here")
        paste_act = menu.addAction("Paste Here") if self._clipboard_has_focuses() else None
        unlink_act = group_act = ungroup_act = None
        if edge is not None:
            if edge.kind == "prereq":
                # reconcile keeps the edge's `alternative` flag current, so the
                # view can offer the right toggle without asking the model.
                if edge.alternative:
                    ungroup_act = menu.addAction("Make required (AND)")
                else:
                    group_act = menu.addAction("Make OR alternative (any one unlocks)")
            verb = "mutual exclusivity" if edge.kind == "mutex" else "connection"
            unlink_act = menu.addAction(f"Delete {verb}")
        chosen = menu.exec(event.globalPos())
        if chosen is new_act:
            self.create_focus_requested.emit(scene_pos)
        elif paste_act is not None and chosen is paste_act:
            self.paste_requested.emit(scene_pos)
        elif group_act is not None and chosen is group_act:
            self.group_prereq_requested.emit(edge.source_id, edge.target_id)
        elif ungroup_act is not None and chosen is ungroup_act:
            self.ungroup_prereq_requested.emit(edge.source_id, edge.target_id)
        elif unlink_act is not None and chosen is unlink_act:
            self.delete_link_requested.emit(edge.source_id, edge.target_id, edge.kind)

    def fit_to_content(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
