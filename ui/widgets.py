"""Small reusable styled widgets shared across panels.

These centralise the section-header / divider / pill / issue-card construction
that was previously duplicated in several panels. Styling lives in ``ui/style.py``
keyed on the object names set here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from . import theme as T


class ClickableLabel(QLabel):
    """A QLabel that emits ``clicked`` on a left-button press and shows a hand
    cursor — used for the status-bar version link."""

    clicked = Signal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ClickableFrame(QFrame):
    """A QFrame that emits ``clicked`` on a left-button release inside the
    frame (so a press-then-drag-away doesn't trigger it)."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def mono_font(size: int = T.TEXT_BODY) -> QFont:
    """Cascadia Mono (with fallback) at a pixel size — for code/preview panes."""
    f = QFont(T.FONT_MONO_FAMILY)
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(size)
    return f


def panel_header(text: str) -> QLabel:
    """Large header shown at the top of each tab/panel."""
    lbl = QLabel(text)
    lbl.setObjectName("panelHeader")
    return lbl


def section_header(text: str) -> QLabel:
    """Small uppercase accent-tinted sub-section label."""
    lbl = QLabel(text)
    lbl.setObjectName("sectionHeader")
    return lbl


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    return line


_PILL_KINDS = {"ok": "pillOk", "error": "pillError", "warn": "pillWarn", "neutral": "pillNeutral"}


def pill(text: str, kind: str = "neutral") -> QLabel:
    """Rounded count/status badge. ``kind`` in {ok, error, warn, neutral}."""
    lbl = QLabel(text)
    lbl.setObjectName(_PILL_KINDS.get(kind, "pillNeutral"))
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


def issue_card(severity: str, message: str, on_click=None) -> QFrame:
    """A validation issue row: tinted card with a glyph + wrapped message.
    With ``on_click`` the card shows a hand cursor and calls it on left-click."""
    is_error = severity == "error"
    card = QFrame() if on_click is None else ClickableFrame()
    card.setObjectName("issueCardError" if is_error else "issueCardWarning")
    row = QHBoxLayout(card)
    row.setContentsMargins(T.SPACE_SM, T.SPACE_XS, T.SPACE_SM, T.SPACE_XS)
    row.setSpacing(T.SPACE_SM)

    symbol = QLabel("×" if is_error else "!")  # render in the UI font (Bahnschrift lacks ✕/⚠)
    symbol.setObjectName("issueSymbolError" if is_error else "issueSymbolWarning")
    symbol.setFixedWidth(16)
    symbol.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
    row.addWidget(symbol)

    text = QLabel(message)
    text.setObjectName("issueTextError" if is_error else "issueTextWarning")
    text.setWordWrap(True)
    row.addWidget(text, 1)

    if on_click is not None:
        card.clicked.connect(on_click)
    return card
