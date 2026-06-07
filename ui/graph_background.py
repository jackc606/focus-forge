"""Strategic-operations themed background for the focus-tree canvas.

The aesthetic is a NORAD/war-room polar plot centred on the focus tree's origin.
Everything here is drawn live in QPainter primitives — no images, no animation —
so it pans and zooms cleanly with the QGraphicsView and stays cheap to repaint.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from . import theme as T
from .focus_node_item import GRID_X, GRID_Y

_MONO = T.FONT_MONO_FAMILY

# ---- palette -----------------------------------------------------------------
# Deliberately quiet: the field reads as texture behind the nodes, not foreground.
# Vignette is near-flat (no bright central bloom) so nodes pop off the board.
COLOR_BG_OUTER = QColor("#0b0e13")         # vignette outer (== BG_BASE)
COLOR_BG_MID = QColor("#0c1017")           # mid
COLOR_BG_INNER = QColor("#10151e")         # faint core lift
COLOR_GRID_MINOR = QColor(70, 105, 150, 16)
COLOR_GRID_MAJOR = QColor(100, 145, 200, 32)
COLOR_AXIS = QColor(170, 200, 235, 55)
COLOR_RING = QColor(110, 165, 215, 26)
COLOR_RING_BRIGHT = QColor(160, 210, 245, 46)
COLOR_SPOKE = QColor(110, 165, 215, 22)
COLOR_HEX = QColor(60, 95, 145, 10)
COLOR_LABEL = QColor(140, 180, 215, 85)
COLOR_STAMP = QColor(120, 165, 195, 40)
COLOR_COMPASS = QColor(150, 190, 220, 80)
COLOR_COMPASS_DARK = QColor(70, 110, 160, 95)
COLOR_ACCENT = QColor(79, 208, 138, 95)    # the app's signature green (== ACCENT)

# ---- spacing ------------------------------------------------------------------
MAJOR_EVERY = 4               # every Nth minor cell becomes a major line
RING_STEP = GRID_Y * 4        # concentric ring spacing in scene units
MAX_RINGS = 12
SPOKE_COUNT = 8               # radial spokes from origin
HEX_SIZE = GRID_Y * 2         # hex tile radius for the watermark grid

CARDINAL_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


# =============================================================================

# Decorative "war-room" layers (compass rose, hex watermark, polar rings, radial
# spokes, briefing stamps) are OFF by default so the board reads like the in-game
# focus tree — a clean dark field with a faint alignment grid. Flip to True to
# bring back the full command-console flavour.
DECORATIONS = False


def draw_strategic_background(painter: QPainter, rect: QRectF) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    _paint_vignette(painter, rect)
    _paint_minor_grid(painter, rect)
    _paint_major_grid(painter, rect)
    _paint_axes(painter, rect)
    _paint_grid_labels(painter, rect)

    if DECORATIONS:
        _paint_hex_watermark(painter, rect)
        _paint_polar_rings(painter, rect)
        _paint_radial_spokes(painter, rect)
        _paint_corner_stamps(painter, rect)
        _paint_compass_rose(painter)

    painter.restore()


# ---- layers ------------------------------------------------------------------

def _paint_vignette(painter: QPainter, rect: QRectF) -> None:
    cx = rect.center().x()
    cy = rect.center().y()
    radius = max(rect.width(), rect.height())
    g = QRadialGradient(QPointF(0, 0), radius * 1.1)
    g.setColorAt(0.0, COLOR_BG_INNER)
    g.setColorAt(0.45, COLOR_BG_MID)
    g.setColorAt(1.0, COLOR_BG_OUTER)
    painter.fillRect(rect, QBrush(g))

    # Soft atmospheric tint behind everything
    painter.fillRect(rect, QColor(20, 35, 60, 6))


def _paint_minor_grid(painter: QPainter, rect: QRectF) -> None:
    pen = QPen(COLOR_GRID_MINOR, 1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    left = math.floor(rect.left() / GRID_X) * GRID_X
    right = rect.right()
    top = math.floor(rect.top() / GRID_Y) * GRID_Y
    bottom = rect.bottom()
    x = left
    while x <= right:
        painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
        x += GRID_X
    y = top
    while y <= bottom:
        painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
        y += GRID_Y


def _paint_major_grid(painter: QPainter, rect: QRectF) -> None:
    pen = QPen(COLOR_GRID_MAJOR, 1)
    pen.setCosmetic(True)
    pen.setStyle(Qt.DashLine)
    pen.setDashPattern([6, 6])
    painter.setPen(pen)
    step_x = GRID_X * MAJOR_EVERY
    step_y = GRID_Y * MAJOR_EVERY
    left = math.floor(rect.left() / step_x) * step_x
    top = math.floor(rect.top() / step_y) * step_y
    x = left
    while x <= rect.right():
        painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
        x += step_x
    y = top
    while y <= rect.bottom():
        painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
        y += step_y


def _paint_axes(painter: QPainter, rect: QRectF) -> None:
    if rect.left() <= 0 <= rect.right():
        pen = QPen(COLOR_AXIS, 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(QLineF(0, rect.top(), 0, rect.bottom()))
    if rect.top() <= 0 <= rect.bottom():
        pen = QPen(COLOR_AXIS, 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(QLineF(rect.left(), 0, rect.right(), 0))


def _paint_polar_rings(painter: QPainter, rect: QRectF) -> None:
    diag = math.hypot(
        max(abs(rect.left()), abs(rect.right())),
        max(abs(rect.top()), abs(rect.bottom())),
    )
    max_radius = min(diag, RING_STEP * MAX_RINGS)
    radius = RING_STEP
    i = 1
    while radius <= max_radius:
        bright = (i % 4 == 0)
        pen = QPen(COLOR_RING_BRIGHT if bright else COLOR_RING, 1.0 if bright else 0.8)
        pen.setCosmetic(True)
        if not bright:
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([2, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        # tick label on the ring at the east cardinal
        if bright and rect.contains(QPointF(radius, 0)):
            painter.setPen(COLOR_LABEL)
            f = QFont(_MONO)
            f.setPointSize(7)
            painter.setFont(f)
            painter.drawText(QPointF(radius + 6, -4), f"R{i}")
        radius += RING_STEP
        i += 1


def _paint_radial_spokes(painter: QPainter, rect: QRectF) -> None:
    pen = QPen(COLOR_SPOKE, 0.8)
    pen.setCosmetic(True)
    pen.setStyle(Qt.DotLine)
    painter.setPen(pen)
    diag = math.hypot(rect.width(), rect.height()) * 1.2
    for i in range(SPOKE_COUNT):
        angle = (i * 360 / SPOKE_COUNT) - 90  # 0 = north
        rad = math.radians(angle)
        x = math.cos(rad) * diag
        y = math.sin(rad) * diag
        painter.drawLine(QLineF(0, 0, x, y))


def _paint_hex_watermark(painter: QPainter, rect: QRectF) -> None:
    """Very faint hex-grid texture suggesting a strategic theatre map."""
    pen = QPen(COLOR_HEX, 1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    r = HEX_SIZE
    h = math.sqrt(3) * r
    col_step = 1.5 * r
    row_step = h
    left = math.floor(rect.left() / col_step) * col_step - col_step
    top = math.floor(rect.top() / row_step) * row_step - row_step
    col = 0
    x = left
    while x <= rect.right() + col_step:
        offset = 0 if col % 2 == 0 else row_step / 2
        y = top + offset
        while y <= rect.bottom() + row_step:
            _draw_hex(painter, x, y, r)
            y += row_step
        x += col_step
        col += 1


def _draw_hex(painter: QPainter, cx: float, cy: float, r: float) -> None:
    path = QPainterPath()
    for i in range(6):
        angle = math.radians(60 * i)
        px = cx + r * math.cos(angle)
        py = cy + r * math.sin(angle)
        if i == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    path.closeSubpath()
    painter.drawPath(path)


def _paint_grid_labels(painter: QPainter, rect: QRectF) -> None:
    """Coordinate stamps at major-grid intersections — like ops-room map ticks."""
    f = QFont(_MONO)
    f.setPointSize(7)
    painter.setFont(f)
    painter.setPen(COLOR_LABEL)
    step_x = GRID_X * MAJOR_EVERY
    step_y = GRID_Y * MAJOR_EVERY
    left = math.floor(rect.left() / step_x) * step_x
    top = math.floor(rect.top() / step_y) * step_y
    x = left
    while x <= rect.right():
        gx = int(round(x / GRID_X))
        y = top
        while y <= rect.bottom():
            gy = int(round(y / GRID_Y))
            if gx == 0 and gy == 0:
                y += step_y
                continue
            painter.drawText(QPointF(x + 4, y + 11), f"{gx:+d},{gy:+d}")
            y += step_y
        x += step_x


def _paint_corner_stamps(painter: QPainter, rect: QRectF) -> None:
    """Briefing-style watermarks anchored to the visible viewport corners."""
    painter.setPen(COLOR_STAMP)
    head = QFont(_MONO)
    head.setPointSize(11)
    head.setBold(True)
    body = QFont(_MONO)
    body.setPointSize(8)

    # top-left
    painter.setFont(head)
    painter.drawText(QPointF(rect.left() + 14, rect.top() + 22), "MILLENNIUM DAWN")
    painter.setFont(body)
    painter.drawText(QPointF(rect.left() + 14, rect.top() + 38), "// FOCUS DOCTRINE / TIER I")
    painter.drawText(QPointF(rect.left() + 14, rect.top() + 52), "// AUTHOR: FORGE-OPS")

    # top-right
    painter.setFont(body)
    painter.drawText(QPointF(rect.right() - 150, rect.top() + 22), "OPERATIONAL THEATRE")
    painter.drawText(QPointF(rect.right() - 150, rect.top() + 38), "GRID  120 x 94 SU")
    painter.drawText(QPointF(rect.right() - 150, rect.top() + 52), "EPOCH  2000.01.01")

    # bottom-right
    painter.drawText(QPointF(rect.right() - 150, rect.bottom() - 30), "STRATCOM // FOCUS")
    painter.drawText(QPointF(rect.right() - 150, rect.bottom() - 16), "CLASSIFICATION: OPEN")

    # bottom-left
    painter.setPen(COLOR_ACCENT)
    painter.drawText(QPointF(rect.left() + 14, rect.bottom() - 30), "▲ NODE LATTICE")
    painter.setPen(COLOR_STAMP)
    painter.drawText(QPointF(rect.left() + 14, rect.bottom() - 16), "FOCUS FORGE  /  v0.1")


def _paint_compass_rose(painter: QPainter) -> None:
    """Ornamental 8-point compass at scene origin (0, 0) — the world's centre."""
    painter.save()

    outer_r = GRID_Y * 1.9
    inner_r = GRID_Y * 0.45
    mid_r = GRID_Y * 1.1

    # base disc — faint, so the origin doesn't bloom over nearby nodes
    grad = QRadialGradient(QPointF(0, 0), outer_r)
    grad.setColorAt(0.0, QColor(30, 50, 85, 70))
    grad.setColorAt(0.7, QColor(20, 35, 60, 40))
    grad.setColorAt(1.0, QColor(20, 35, 60, 0))
    painter.setBrush(QBrush(grad))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(0, 0), outer_r, outer_r)

    # outer rings
    pen_outer = QPen(COLOR_COMPASS, 1.2)
    pen_outer.setCosmetic(True)
    painter.setPen(pen_outer)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(0, 0), outer_r, outer_r)
    painter.drawEllipse(QPointF(0, 0), mid_r, mid_r)

    # 16 fine ticks
    fine_pen = QPen(COLOR_COMPASS, 0.7)
    fine_pen.setCosmetic(True)
    painter.setPen(fine_pen)
    for i in range(32):
        angle = math.radians(i * 360 / 32 - 90)
        x1 = math.cos(angle) * (outer_r - 4)
        y1 = math.sin(angle) * (outer_r - 4)
        x2 = math.cos(angle) * outer_r
        y2 = math.sin(angle) * outer_r
        painter.drawLine(QLineF(x1, y1, x2, y2))

    # 8 cardinal points (filled triangle blades)
    for i, label in enumerate(CARDINAL_LABELS):
        angle = math.radians(i * 45 - 90)
        primary = (i % 2 == 0)
        radius = outer_r - 6 if primary else mid_r - 6
        side = math.radians((i * 45 - 90) + 90)
        side_w = (GRID_Y * 0.22) if primary else (GRID_Y * 0.14)

        tip = QPointF(math.cos(angle) * radius, math.sin(angle) * radius)
        base_left = QPointF(math.cos(side) * side_w, math.sin(side) * side_w)
        base_right = QPointF(-math.cos(side) * side_w, -math.sin(side) * side_w)

        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(base_left)
        path.lineTo(base_right)
        path.closeSubpath()
        if primary:
            painter.setBrush(COLOR_COMPASS)
        else:
            painter.setBrush(COLOR_COMPASS_DARK)
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)

        # mirrored darker half-blade for depth
        path2 = QPainterPath()
        mid = QPointF(math.cos(angle) * radius * 0.5, math.sin(angle) * radius * 0.5)
        path2.moveTo(tip)
        path2.lineTo(mid)
        path2.lineTo(base_left)
        path2.closeSubpath()
        painter.setBrush(QColor(30, 55, 90, 90) if primary else QColor(20, 40, 70, 80))
        painter.drawPath(path2)

    # cardinal letters
    f = QFont(_MONO)
    f.setBold(True)
    f.setPointSize(9)
    painter.setFont(f)
    painter.setPen(COLOR_COMPASS)
    label_r = outer_r + 12
    for i, label in enumerate(CARDINAL_LABELS):
        if i % 2 != 0:
            continue  # only show major cardinals
        angle = math.radians(i * 45 - 90)
        x = math.cos(angle) * label_r - 5
        y = math.sin(angle) * label_r + 4
        painter.drawText(QPointF(x, y), label)

    # central hub
    painter.setPen(QPen(COLOR_COMPASS, 1.0))
    painter.setBrush(QColor(30, 55, 90, 130))
    painter.drawEllipse(QPointF(0, 0), inner_r, inner_r)
    painter.setPen(QPen(COLOR_ACCENT, 1.4))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(0, 0), inner_r * 0.55, inner_r * 0.55)

    # tiny "0,0" stamp under the hub
    painter.setPen(COLOR_LABEL)
    sf = QFont(_MONO)
    sf.setPointSize(7)
    painter.setFont(sf)
    painter.drawText(QPointF(-12, inner_r + 14), "0,0")

    painter.restore()
