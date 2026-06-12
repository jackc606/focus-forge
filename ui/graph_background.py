"""Strategic-operations themed background for the focus-tree canvas.

A clean dark field with a faint alignment grid, axes and coordinate stamps —
drawn live in QPainter primitives (no images, no animation) so it pans and
zooms cleanly with the QGraphicsView and stays cheap to repaint.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient

from . import theme as T
from .focus_node_item import GRID_X, GRID_Y

_MONO = T.FONT_MONO_FAMILY

# ---- palette -----------------------------------------------------------------
# Deliberately quiet: the field reads as texture behind the nodes, not foreground.
# Vignette is near-flat (no bright central bloom) so nodes pop off the board.
COLOR_BG_OUTER = QColor(T.BG_BASE)         # vignette outer = window void
COLOR_BG_MID = QColor("#0c1017")           # vignette-only shades between BG_BASE
COLOR_BG_INNER = QColor("#10151e")         # and the panel tone — faint core lift
COLOR_GRID_MINOR = QColor(70, 105, 150, 16)
COLOR_GRID_MAJOR = QColor(100, 145, 200, 32)
COLOR_AXIS = QColor(170, 200, 235, 55)
COLOR_LABEL = QColor(140, 180, 215, 85)

# ---- spacing ------------------------------------------------------------------
MAJOR_EVERY = 4               # every Nth minor cell becomes a major line

# Built on first use (not import) so no QFont exists before the QApplication,
# and not per frame — grid labels repaint on every pan/zoom.
_LABEL_FONT = None


def _label_font() -> QFont:
    global _LABEL_FONT
    if _LABEL_FONT is None:
        f = QFont(_MONO)
        f.setPointSize(7)
        _LABEL_FONT = f
    return _LABEL_FONT


def draw_strategic_background(painter: QPainter, rect: QRectF,
                             vignette_radius: float = 0.0) -> None:
    """Paint the canvas backdrop over ``rect`` (the dirty patch).

    ``vignette_radius`` sizes the centre→edge gradient. It must be a STABLE value
    (derived from the scene extent, not the dirty rect) so every scene point maps
    to the same colour regardless of which patch triggers the repaint — that's
    what lets the view repaint only changed regions instead of the whole tree."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    radius = vignette_radius or max(rect.width(), rect.height())
    _paint_vignette(painter, rect, radius)
    _paint_minor_grid(painter, rect)
    _paint_major_grid(painter, rect)
    _paint_axes(painter, rect)
    _paint_grid_labels(painter, rect)

    painter.restore()


# ---- layers ------------------------------------------------------------------

def _paint_vignette(painter: QPainter, rect: QRectF, radius: float) -> None:
    # Gradient is in scene coordinates centred at the origin, so a given scene
    # point gets the same colour in any dirty patch (scroll-safe / partial-safe).
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


def _paint_grid_labels(painter: QPainter, rect: QRectF) -> None:
    """Coordinate stamps at major-grid intersections — like ops-room map ticks."""
    painter.setFont(_label_font())
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
