"""Corner minimap for the focus canvas.

The whole tree as a dot constellation (the welcome-card motif, live) with the
current viewport as an accent rectangle. Click or drag anywhere on it to jump
the view there. Perf: the dot field renders into a cached pixmap re-built only
when the layout changes (scene.layout_version) or the widget resizes — the
per-frame cost during pans is one pixmap blit plus one rectangle.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import theme as T

_W, _H = 200, 132
_PAD = 10       # inner padding around the dot field
_MARGIN = 12    # distance from the view's bottom-right corner


class MinimapOverlay(QWidget):
    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.setFixedSize(_W, _H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setToolTip("Minimap — click or drag to move the view")
        self._dots: QPixmap = QPixmap()
        self._dots_version = -1
        # Dot-field → scene mapping, rebuilt with the dots.
        self._scale = 1.0
        self._offset = QPointF(0, 0)  # scene coords of the field's top-left

    # ----- placement -----
    def reposition(self) -> None:
        self.move(self._view.width() - _W - _MARGIN,
                  self._view.height() - _H - _MARGIN)

    # ----- mapping -----
    def _rebuild_dots(self, points) -> None:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        avail_w = _W - _PAD * 2
        avail_h = _H - _PAD * 2
        self._scale = min(avail_w / span_x, avail_h / span_y)
        # Centre the tree inside the field.
        used_w = span_x * self._scale
        used_h = span_y * self._scale
        origin_x = _PAD + (avail_w - used_w) / 2
        origin_y = _PAD + (avail_h - used_h) / 2
        self._offset = QPointF(min_x - origin_x / self._scale,
                               min_y - origin_y / self._scale)

        pm = QPixmap(_W, _H)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        dot = QColor(T.ACCENT)
        dot.setAlpha(150)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        for x, y in points:
            wp = self._scene_to_widget(QPointF(x, y))
            p.drawEllipse(QRectF(wp.x() - 1.0, wp.y() - 1.0, 2.0, 2.0))
        p.end()
        self._dots = pm

    def _scene_to_widget(self, pt: QPointF) -> QPointF:
        return QPointF((pt.x() - self._offset.x()) * self._scale,
                       (pt.y() - self._offset.y()) * self._scale)

    def _widget_to_scene(self, pt: QPointF) -> QPointF:
        return QPointF(pt.x() / self._scale + self._offset.x(),
                       pt.y() / self._scale + self._offset.y())

    # ----- painting -----
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        scene = self._view.scene()
        points = scene.node_points() if hasattr(scene, "node_points") else []
        if not points:
            return
        version = getattr(scene, "layout_version", 0)
        if version != self._dots_version or self._dots.isNull():
            self._rebuild_dots(points)
            self._dots_version = version

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor(T.BG_PANEL)
        bg.setAlpha(225)
        p.setPen(QColor(T.BORDER_STRONG))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, _W - 1, _H - 1), 5, 5)
        p.drawPixmap(0, 0, self._dots)

        # Viewport rectangle (clamped to the widget so a tight zoom still
        # reads as "you are here" instead of vanishing off the field).
        vp_scene = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        tl = self._scene_to_widget(vp_scene.topLeft())
        br = self._scene_to_widget(vp_scene.bottomRight())
        rect = QRectF(tl, br).intersected(QRectF(1, 1, _W - 2, _H - 2))
        if not rect.isEmpty():
            frame = QColor(T.ACCENT)
            fill = QColor(T.ACCENT)
            fill.setAlpha(24)
            p.setPen(frame)
            p.setBrush(fill)
            p.drawRect(rect)
        p.end()

    # ----- navigation -----
    def _navigate(self, pos) -> None:
        self._view.centerOn(self._widget_to_scene(QPointF(pos)))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self._navigate(event.position())
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.buttons() & Qt.LeftButton:
            self._navigate(event.position())
            event.accept()
