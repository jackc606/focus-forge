"""QGraphicsObject for a single focus node — styled to read like an in-game
HOI4 / Millennium Dawn focus: a bracket-framed square icon with the focus name
on a plate directly below it, so the canvas previews the in-game tree (WYSIWYG)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
)

from . import theme as T
from .country_export import _qimage_from_b64
from .icon_provider import provider

# Grid: x-neighbours sit side by side; y+1 is one level down with room for the
# orthogonal connector. Taller-than-wide cells mirror the in-game tree.
GRID_X = 124
GRID_Y = 158

NODE_W = 112
NODE_H = 126

ICON = 76
ICON_X = (NODE_W - ICON) // 2
ICON_Y = 6
PLATE_Y = ICON_Y + ICON + 4       # name plate top
PLATE_H = 26
ID_Y = PLATE_Y + PLATE_H          # focus id row top
ID_H = 14
BRACKET = 13                      # corner-bracket arm length

PORT_R = 5                        # connection port dot radius
PORT_HIT = 12                     # grab radius around the bottom port
PORT_PAD = 12                     # boundingRect padding so ports paint/hit fully
GLOW_PAD = 5                      # horizontal padding so the selection glow paints fully


def _ui_font(size: int, weight: int = T.WEIGHT_REGULAR) -> QFont:
    f = QFont(T.FONT_UI_FAMILY)
    f.setStyleHint(QFont.SansSerif)
    f.setWeight(QFont.Weight(weight))
    f.setPixelSize(size)
    return f


def _mono_font(size: int, weight: int = T.WEIGHT_REGULAR) -> QFont:
    f = QFont(T.FONT_MONO_FAMILY)
    f.setStyleHint(QFont.Monospace)
    f.setWeight(QFont.Weight(weight))
    f.setPixelSize(size)
    return f


class FocusNodeItem(QGraphicsObject):
    position_committed = Signal(str, int, int)  # focus_id, grid_x, grid_y
    clicked = Signal(str)
    connect_started = Signal(str, QPointF)      # source focus_id, anchor scene pos
    connect_moved = Signal(QPointF)             # current scene pos
    connect_ended = Signal(str, str, QPointF)   # source_id, target_id ("" if none), drop pos

    def __init__(self, focus_id: str, title: str, icon: str, grid_x: int, grid_y: int,
                 cost=5, prereq_count: int = 0, icon_data: str = "") -> None:
        super().__init__()
        self._focus_id = focus_id
        self._title = title or focus_id
        self._icon = icon or "?"
        self._icon_data = icon_data or ""
        self._custom_pm = None  # decoded pixmap for a custom imported icon
        self._grid_x = grid_x
        self._grid_y = grid_y
        self._cost = cost
        self._prereq_count = prereq_count
        self._hover = False
        self._connecting = False
        self._search_match = None  # None=no search, True=match, False=non-match
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setPos(grid_x * GRID_X, grid_y * GRID_Y)
        # NOTE: deliberately no QGraphicsDropShadowEffect here. A QGraphicsEffect
        # on a scene item segfaults (PySide6/Qt) when items are removed from a
        # live, painting scene — i.e. when deleting focuses. The selection glow
        # is painted directly in paint() instead.

    @property
    def focus_id(self) -> str:
        return self._focus_id

    def grid_position(self) -> tuple:
        return (self._grid_x, self._grid_y)

    def update_data(self, title: str, icon: str, grid_x: int, grid_y: int,
                    cost=None, prereq_count: int = None, icon_data: str = "") -> None:
        changed = False
        if title != self._title:
            self._title = title or self._focus_id
            changed = True
        if icon != self._icon:
            self._icon = icon or "?"
            changed = True
        if (icon_data or "") != self._icon_data:
            self._icon_data = icon_data or ""
            self._custom_pm = None  # re-decode lazily on next paint
            changed = True
        if cost is not None and cost != self._cost:
            self._cost = cost
        if prereq_count is not None and prereq_count != self._prereq_count:
            self._prereq_count = prereq_count
        if (grid_x, grid_y) != (self._grid_x, self._grid_y):
            self._grid_x = grid_x
            self._grid_y = grid_y
            self.setPos(grid_x * GRID_X, grid_y * GRID_Y)
        if changed:
            self.update()

    def boundingRect(self) -> QRectF:
        # Padded top/bottom so the ports paint/hit fully, and a little left/right
        # so the painted selection glow isn't clipped (avoids repaint artifacts).
        return QRectF(-GLOW_PAD, -PORT_PAD, NODE_W + 2 * GLOW_PAD, NODE_H + 2 * PORT_PAD)

    # ----- painting -----
    def _icon_pixmap(self):
        """The node's icon art: a custom imported image wins over the named
        in-game sprite (mirrors what the exporter emits)."""
        if self._icon_data:
            if self._custom_pm is None:
                img = _qimage_from_b64(self._icon_data)
                self._custom_pm = QPixmap.fromImage(img) if img is not None else QPixmap()
            if not self._custom_pm.isNull():
                return self._custom_pm
        return provider().pixmap(self._icon)

    def _paint_glow(self, painter: QPainter, selected: bool) -> None:
        """Painted accent halo for the selected node (replaces the old
        QGraphicsDropShadowEffect, which crashes on item removal). Outline-only
        strokes, so it never fills the node's transparent gaps."""
        if not selected:
            return
        body = QRectF(2, ICON_Y - 2, NODE_W - 4, (ID_Y + ID_H) - ICON_Y + 4)
        painter.setBrush(Qt.NoBrush)
        for i, alpha in enumerate((120, 60, 26)):
            c = QColor(T.ACCENT)
            c.setAlpha(alpha)
            painter.setPen(QPen(c, 2 + i * 2))
            painter.drawRoundedRect(body.adjusted(-i * 2, -i * 2, i * 2, i * 2), 9, 9)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        selected = self.isSelected()
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_glow(painter, selected)

        if selected:
            frame = QColor(T.ACCENT)
            bracket = QColor(T.ACCENT_HOVER)
        elif self._hover:
            frame = QColor(T.BORDER_HOVER)
            bracket = QColor(T.TEXT_SECONDARY)
        else:
            frame = QColor(T.FOCUS_FRAME)
            bracket = QColor(T.FOCUS_BRACKET)

        icon_rect = QRectF(ICON_X, ICON_Y, ICON, ICON)
        pm = self._icon_pixmap()
        if pm is not None and not pm.isNull():
            # Real in-game icon — the .dds already carries its own frame art, so
            # draw it edge-to-edge (preserving aspect) and skip the synthetic frame.
            avail = QRectF(4, ICON_Y, NODE_W - 8, ICON)
            scaled = pm.scaled(int(avail.width()), int(avail.height()),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dx = avail.x() + (avail.width() - scaled.width()) / 2
            dy = avail.y() + (avail.height() - scaled.height()) / 2
            painter.drawPixmap(QPointF(dx, dy), scaled)
            if selected or self._hover:
                painter.setPen(QPen(frame, 2 if selected else 1.5))
                painter.setBrush(Qt.NoBrush)
                ring = QRectF(dx - 2, dy - 2, scaled.width() + 4, scaled.height() + 4)
                painter.drawRoundedRect(ring, 4, 4)
        else:
            # Fallback: synthetic bracket-framed square with the icon abbreviation.
            painter.fillRect(icon_rect, QColor(T.BG_INSET))
            painter.setPen(QPen(QColor(T.BG_ELEVATED), 1))
            painter.drawRect(icon_rect.adjusted(1.5, 1.5, -1.5, -1.5))
            painter.setPen(QPen(frame, 2 if selected else 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(icon_rect)
            self._draw_brackets(painter, icon_rect, bracket)
            painter.setPen(QColor(T.TEXT_SECONDARY))
            painter.setFont(_mono_font(T.TEXT_LABEL, T.WEIGHT_BOLD))
            painter.drawText(icon_rect, Qt.AlignCenter, self._icon[:4].upper())

        # ---- name plate ----
        plate = QRectF(2, PLATE_Y, NODE_W - 4, PLATE_H)
        path = QPainterPath()
        path.addRoundedRect(plate, 3, 3)
        painter.fillPath(path, QColor(T.FOCUS_PLATE))
        if selected:
            painter.setPen(QPen(QColor(T.ACCENT_DIM), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        painter.setPen(QColor(T.TEXT_PRIMARY))
        painter.setFont(_ui_font(T.TEXT_BODY, T.WEIGHT_SEMIBOLD))
        painter.drawText(plate.adjusted(3, 1, -3, -1),
                         Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
                         self._title)

        # ---- focus id (editor affordance, kept subtle) ----
        painter.setPen(QColor(T.TEXT_MUTED))
        painter.setFont(_mono_font(10))
        id_rect = QRectF(2, ID_Y, NODE_W - 4, ID_H)
        fm = painter.fontMetrics()
        eid = fm.elidedText(self._focus_id, Qt.ElideMiddle, int(NODE_W - 8))
        painter.drawText(id_rect, Qt.AlignHCenter | Qt.AlignVCenter, eid)

        if self._search_match is True:
            painter.setPen(QPen(QColor(T.SEARCH_HL), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(1, 1, NODE_W - 2, NODE_H - 2), 6, 6)

        self._draw_ports(painter)

    def set_search_match(self, state) -> None:
        if state != self._search_match:
            self._search_match = state
            self.update()

    def _draw_ports(self, painter: QPainter) -> None:
        # Ports appear on hover/selection — drag the bottom (accent) port onto
        # another focus to make it a prerequisite.
        if not (self._hover or self.isSelected() or self._connecting):
            return
        bottom = QPointF(NODE_W / 2, NODE_H)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T.ACCENT))
        painter.drawEllipse(bottom, PORT_R, PORT_R)
        painter.setPen(QPen(QColor(T.BG_BASE), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(bottom, PORT_R, PORT_R)
        # top (input) — subtle
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T.BORDER_HOVER))
        painter.drawEllipse(QPointF(NODE_W / 2, 0), PORT_R - 1, PORT_R - 1)

    def _in_bottom_port(self, pos: QPointF) -> bool:
        dx = pos.x() - NODE_W / 2
        dy = pos.y() - NODE_H
        return (dx * dx + dy * dy) <= PORT_HIT * PORT_HIT

    @staticmethod
    def _draw_brackets(painter: QPainter, r: QRectF, color: QColor) -> None:
        painter.setPen(QPen(color, 2))
        b = BRACKET
        # each corner: two short arms forming an L
        corners = [
            (r.left(), r.top(), 1, 1),
            (r.right(), r.top(), -1, 1),
            (r.left(), r.bottom(), 1, -1),
            (r.right(), r.bottom(), -1, -1),
        ]
        for x, y, sx, sy in corners:
            painter.drawLine(int(x), int(y), int(x + sx * b), int(y))
            painter.drawLine(int(x), int(y), int(x), int(y + sy * b))

    # ----- interaction -----
    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            # snap to grid
            x = round(value.x() / GRID_X) * GRID_X
            y = round(value.y() / GRID_Y) * GRID_Y
            value.setX(x)
            value.setY(y)
            return value
        if change == QGraphicsItem.ItemPositionHasChanged:
            new_x = int(round(self.x() / GRID_X))
            new_y = int(round(self.y() / GRID_Y))
            if (new_x, new_y) != (self._grid_x, self._grid_y):
                self._grid_x = new_x
                self._grid_y = new_y
                self.position_committed.emit(self._focus_id, new_x, new_y)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.update()  # repaint the painted selection glow
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._in_bottom_port(event.pos()):
            # Start a connection drag instead of moving the node.
            self._connecting = True
            anchor = self.mapToScene(QPointF(NODE_W / 2, NODE_H))
            self.connect_started.emit(self._focus_id, anchor)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)
        self.clicked.emit(self._focus_id)

    def mouseMoveEvent(self, event) -> None:
        if self._connecting:
            self.connect_moved.emit(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._connecting:
            self._connecting = False
            target_id = ""
            for it in self.scene().items(event.scenePos()):
                if isinstance(it, FocusNodeItem) and it is not self:
                    target_id = it.focus_id
                    break
            self.connect_ended.emit(self._focus_id, target_id, event.scenePos())
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)
