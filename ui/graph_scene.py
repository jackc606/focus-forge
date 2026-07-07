"""QGraphicsScene that reconciles itself against the project model."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsScene

from core.types import iter_prereq_ids

from . import theme as T
from .edge_item import EdgeItem
from .focus_node_item import FocusNodeItem
from .graph_background import draw_strategic_background


class GraphScene(QGraphicsScene):
    node_clicked = Signal(str)
    node_moved = Signal(str, int, int)
    link_requested = Signal(str, str)          # source_id (prerequisite), target_id (dependent)
    create_child_requested = Signal(str, QPointF)  # source_id, drop scene pos (empty space)

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QColor(T.BG_BASE))
        self._nodes: dict = {}  # focus_id -> FocusNodeItem
        self._edges: dict = {}  # (src_id, dst_id) -> EdgeItem
        self._last_positions: dict = {}  # focus_id -> (x, y) at last reconcile
        self._temp_line = None
        self._connect_anchor = None

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802 — Qt API
        # Paint ONLY the dirty patch (`rect`). The vignette radius comes from the
        # stable scene extent, not the patch, so each scene point is coloured
        # consistently — letting the view repaint only changed item regions
        # instead of the whole tree on every hover/select (huge on big trees).
        sr = self.sceneRect()
        extent = max(abs(sr.left()), abs(sr.right()),
                     abs(sr.top()), abs(sr.bottom()), 1.0)
        draw_strategic_background(painter, rect, extent)

    def reconcile(self, project, selected_id: str = "") -> None:
        # Track desired state
        desired_node_keys = {f.id for f in project.focuses}
        focuses_by_id = {f.id: f for f in project.focuses}

        # Remove stale nodes
        for stale_id in list(self._nodes.keys()):
            if stale_id not in desired_node_keys:
                self.removeItem(self._nodes[stale_id])
                del self._nodes[stale_id]

        # Add or update nodes
        for f in project.focuses:
            prereq_count = sum(1 for _ in iter_prereq_ids(f.prerequisites))
            existing = self._nodes.get(f.id)
            if existing:
                existing.update_data(f.title, f.icon, int(f.position.x), int(f.position.y),
                                     cost=f.cost, prereq_count=prereq_count,
                                     icon_data=getattr(f, "iconData", ""))
            else:
                node = FocusNodeItem(f.id, f.title, f.icon, int(f.position.x), int(f.position.y),
                                     cost=f.cost, prereq_count=prereq_count,
                                     icon_data=getattr(f, "iconData", ""))
                node.position_committed.connect(self.node_moved.emit)
                node.clicked.connect(self.node_clicked.emit)
                node.connect_started.connect(self._on_connect_started)
                node.connect_moved.connect(self._on_connect_moved)
                node.connect_ended.connect(self._on_connect_ended)
                self.addItem(node)
                self._nodes[f.id] = node
                # Only a NEWLY created item takes the model's selection (add /
                # paste selects the new node). Existing items keep whatever
                # selection they have: reconcile runs on EVERY project change
                # (each grid-step of a drag included), so resetting selection
                # here destroyed multi-select mid-gesture.
                node.setSelected(f.id == selected_id)

        # Reconcile edges — prerequisite (top-down) + mutually-exclusive (red).
        # Keys: ("prereq", src, dst) and ("mutex", a, b) with a<b deduped.
        desired_edges: dict = {}
        for f in project.focuses:
            for prereq in iter_prereq_ids(f.prerequisites):
                if prereq in desired_node_keys:
                    desired_edges[("prereq", prereq, f.id)] = (prereq, f.id)
            for mx in f.mutuallyExclusive:
                if mx in desired_node_keys:
                    a, b = sorted((f.id, mx))
                    desired_edges[("mutex", a, b)] = (a, b)

        for stale_key in list(self._edges.keys()):
            if stale_key not in desired_edges:
                self.removeItem(self._edges[stale_key])
                del self._edges[stale_key]

        for key, (src_id, dst_id) in desired_edges.items():
            if key not in self._edges:
                # EdgeItem builds its path in __init__, no refresh needed here.
                edge = EdgeItem(self._nodes[src_id], self._nodes[dst_id], kind=key[0])
                self.addItem(edge)
                self._edges[key] = edge

        # Rebuild edge paths only for edges whose endpoints actually moved —
        # a title edit on a 500-focus tree shouldn't re-route every connector.
        positions = {fid: (node.x(), node.y()) for fid, node in self._nodes.items()}
        moved = {fid for fid, pos in positions.items()
                 if self._last_positions.get(fid) != pos}
        self._last_positions = positions
        if moved:
            for (kind, a, b), edge in self._edges.items():
                if a in moved or b in moved:
                    edge.refresh()

        if project.focuses:
            xs = [n.scenePos().x() for n in self._nodes.values()]
            ys = [n.scenePos().y() for n in self._nodes.values()]
            # Generous pan room: the view scrolls via scrollbars, which Qt
            # clamps to this rect — a tight margin made it impossible to pull
            # the tree's bottom row up the screen when zoomed in. 1000 scene px
            # covers a full viewport of slack at any zoom ≥ 1.
            margin = 1000
            new_rect = QRectF(min(xs) - margin, min(ys) - margin,
                              max(xs) - min(xs) + margin * 2 + 240,
                              max(ys) - min(ys) + margin * 2 + 100)
            if new_rect != self.sceneRect():
                self.setSceneRect(new_rect)

    def select_node(self, focus_id: str) -> None:
        """Sync the canvas to a programmatic selection change (list panel,
        undo, delete-picks-next). NO-OP when the target is already part of the
        current selection: every node click round-trips through the model back
        to here (click → set_selection → selection_changed → select_node), and
        collapsing to a single node on that echo made Ctrl+click / rubber-band
        multi-select impossible."""
        target = self._nodes.get(focus_id)
        if target is not None and target.isSelected():
            return
        for fid, item in self._nodes.items():
            item.setSelected(fid == focus_id)

    def set_search_matches(self, match_ids) -> None:
        """Highlight matching focuses (amber ring) and dim the rest. Pass None to
        clear the search highlight."""
        for fid, item in self._nodes.items():
            if match_ids is None:
                item.set_search_match(None)
                item.setOpacity(1.0)
            else:
                matched = fid in match_ids
                item.set_search_match(matched)
                item.setOpacity(1.0 if matched else 0.3)

    # ----- drag-to-connect -----
    def _on_connect_started(self, source_id: str, anchor: QPointF) -> None:
        self._connect_anchor = anchor
        if self._temp_line is None:
            self._temp_line = QGraphicsPathItem()
            pen = QPen(QColor(T.ACCENT), 2)
            pen.setStyle(Qt.DashLine)
            pen.setCosmetic(True)
            self._temp_line.setPen(pen)
            self._temp_line.setZValue(5)
            self.addItem(self._temp_line)
        self._temp_line.setVisible(True)

    def _on_connect_moved(self, scene_pos: QPointF) -> None:
        if self._temp_line is None or self._connect_anchor is None:
            return
        a = self._connect_anchor
        mid_y = (a.y() + scene_pos.y()) / 2
        path = QPainterPath()
        path.moveTo(a)
        path.lineTo(QPointF(a.x(), mid_y))
        path.lineTo(QPointF(scene_pos.x(), mid_y))
        path.lineTo(scene_pos)
        self._temp_line.setPath(path)

    def _on_connect_ended(self, source_id: str, target_id: str, drop_pos: QPointF) -> None:
        anchor = self._connect_anchor
        if self._temp_line is not None:
            self._temp_line.setVisible(False)
            self._temp_line.setPath(QPainterPath())
        self._connect_anchor = None
        if target_id and target_id != source_id:
            self.link_requested.emit(source_id, target_id)
        elif not target_id and anchor is not None:
            # Released on empty canvas → spawn a connected child, but only on a
            # real drag (ignore a stray click on the port).
            dx = drop_pos.x() - anchor.x()
            dy = drop_pos.y() - anchor.y()
            if (dx * dx + dy * dy) >= 30 * 30:
                self.create_child_requested.emit(source_id, drop_pos)
