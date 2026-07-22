"""Startup launcher — shown when Focus Forge opens, instead of auto-loading a
project. Recent projects render as cards with a tiny "constellation" of the
tree's real focus positions; summaries load after the dialog paints so a
shelf of big projects never delays the launcher."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.version import version_label

from . import theme as T
from .widgets import ClickableFrame, hint, panel_header, section_header

_MAX_CARDS = 5


class _TreeThumb(QWidget):
    """The project's focus tree as a constellation: one dot per focus at its
    real (scaled) grid position. Instantly recognizable per project."""

    W, H = 104, 64

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self._points: list = []

    def set_positions(self, positions) -> None:
        self._points = list(positions or [])
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.W - 1, self.H - 1)
        p.setPen(QColor(T.BORDER_SUBTLE))
        p.setBrush(QColor(T.BG_INSET))
        p.drawRoundedRect(r, 4, 4)
        if self._points:
            xs = [x for x, _ in self._points]
            ys = [y for _, y in self._points]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span_x = max(max_x - min_x, 1)
            span_y = max(max_y - min_y, 1)
            pad = 7
            dot = QColor(T.ACCENT)
            dot.setAlpha(165)
            p.setPen(Qt.NoPen)
            p.setBrush(dot)
            for x, y in self._points:
                px = pad + (x - min_x) / span_x * (self.W - pad * 2)
                py = pad + (y - min_y) / span_y * (self.H - pad * 2)
                p.drawEllipse(QRectF(px - 1.1, py - 1.1, 2.2, 2.2))
        p.end()


class _RecentCard(ClickableFrame):
    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recentCard")
        self.path = path
        h = QHBoxLayout(self)
        h.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_SM)
        h.setSpacing(T.SPACE_MD)
        self.thumb = _TreeThumb()
        h.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(_pretty_name(path))
        name.setObjectName("recentName")
        col.addWidget(name)
        self.meta = QLabel("…")
        self.meta.setObjectName("hint")
        col.addWidget(self.meta)
        path_lbl = QLabel(_elide_path(path))
        path_lbl.setObjectName("recentPath")
        col.addWidget(path_lbl)
        col.addStretch(1)
        h.addLayout(col, 1)
        self.setToolTip(path)


class WelcomeDialog(QDialog):
    def __init__(self, recent=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to Focus Forge")
        self.resize(620, 640)
        self.choice = None          # 'new' | 'open' | 'recent' | 'sample' | None
        self.recent_path = None
        self._cards: list = []

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_XL, T.SPACE_XL, T.SPACE_XL, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Focus Forge"))
        v.addWidget(hint(f"{version_label()} — HOI4 / Millennium Dawn focus-tree editor"))
        v.addSpacing(T.SPACE_SM)

        actions = QHBoxLayout()
        actions.setSpacing(T.SPACE_SM)
        new_btn = QPushButton("＋  Create New Submod")
        new_btn.setObjectName("primary")
        new_btn.setMinimumHeight(T.BUTTON_TALL)
        new_btn.setToolTip("Start a fresh submod project (optionally from an existing tree).")
        new_btn.clicked.connect(lambda: self._choose("new"))
        actions.addWidget(new_btn, 1)
        open_btn = QPushButton("Open Project…")
        open_btn.setMinimumHeight(T.BUTTON_TALL)
        open_btn.setToolTip("Open an existing .focusforge.json project.")
        open_btn.clicked.connect(lambda: self._choose("open"))
        actions.addWidget(open_btn, 1)
        v.addLayout(actions)

        recent = list(recent or [])[:_MAX_CARDS]
        if recent:
            v.addSpacing(T.SPACE_SM)
            v.addWidget(section_header("Recent"))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(scroll.Shape.NoFrame)
            holder = QWidget()
            cards_box = QVBoxLayout(holder)
            cards_box.setContentsMargins(0, 0, 0, 0)
            cards_box.setSpacing(T.SPACE_SM)
            for path in recent:
                card = _RecentCard(path)
                card.clicked.connect(lambda p=path: self._open_recent(p))
                cards_box.addWidget(card)
                self._cards.append(card)
            cards_box.addStretch(1)
            scroll.setWidget(holder)
            v.addWidget(scroll, 1)
            # Fill thumbnails after the first paint — one card per event-loop
            # turn, so five multi-megabyte projects never stall the launcher.
            self._pending = list(self._cards)
            QTimer.singleShot(0, self._load_next_summary)
        else:
            v.addWidget(hint("No recent projects yet — create or open one to get started."))
            v.addStretch(1)

        footer = QHBoxLayout()
        sample_btn = QPushButton("Explore the sample project")
        sample_btn.setObjectName("link")
        sample_btn.setToolTip("Load the built-in example tree to look around.")
        sample_btn.clicked.connect(lambda: self._choose("sample"))
        footer.addWidget(sample_btn)
        footer.addStretch(1)
        close_btn = QPushButton("Continue without a project")
        close_btn.setToolTip("Close this launcher and start with an empty editor.")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        v.addLayout(footer)

    # ----- async card summaries -----
    def _load_next_summary(self) -> None:
        if not self._pending:
            return
        card = self._pending.pop(0)
        summary = _project_summary(card.path)
        if summary is None:
            card.meta.setText("could not read project")
        else:
            positions, count, tag = summary
            card.thumb.set_positions(positions)
            bits = [f"{count} focus{'es' if count != 1 else ''}"]
            if tag:
                bits.append(tag)
            card.meta.setText(" · ".join(bits))
        QTimer.singleShot(0, self._load_next_summary)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def _open_recent(self, path: str) -> None:
        self.choice = "recent"
        self.recent_path = path
        self.accept()


def _project_summary(path: str):
    """(positions, focus_count, tag) from a project file, or None. Tolerates
    missing/corrupt files — the launcher must never crash over a stale recent."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        focuses = data.get("focuses") or []
        positions = []
        for f in focuses:
            pos = f.get("position") or {}
            positions.append((float(pos.get("x", 0)), float(pos.get("y", 0))))
        return positions, len(focuses), (data.get("countryTag") or "").strip()
    except Exception:
        return None


def _elide_path(path: str, limit: int = 58) -> str:
    if len(path) <= limit:
        return path
    return "…" + path[-(limit - 1):]


def _pretty_name(path: str) -> str:
    base = os.path.basename(path)
    for suffix in (".focusforge.json", ".json"):
        if base.lower().endswith(suffix):
            return base[: -len(suffix)]
    return base
