"""Dev Log dialog — the in-app release history, opened by clicking the version
label in the status bar. Content comes from ``core.changelog.CHANGELOG``."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.changelog import CHANGELOG
from core.version import version_label

from . import theme as T
from .widgets import hint, panel_header, pill


class DevLogDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dev Log")
        self.resize(560, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        outer.setSpacing(T.SPACE_MD)
        outer.addWidget(panel_header("Dev Log"))
        outer.addWidget(hint(f"What's new in Focus Forge — currently {version_label()}."))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        holder = QWidget()
        scroll.setWidget(holder)
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_MD)
        for entry in CHANGELOG:
            v.addWidget(self._make_entry(entry))
        v.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    @staticmethod
    def _make_entry(entry: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("helpCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_MD)
        cv.setSpacing(T.SPACE_XS)

        head = QLabel(f"v{entry.get('version', '')}"
                      + (f"  ·  {entry['date']}" if entry.get("date") else ""))
        head.setObjectName("helpTitle")
        cv.addWidget(head)

        if entry.get("title"):
            sub = QLabel(entry["title"])
            sub.setObjectName("helpBody")
            sub.setWordWrap(True)
            cv.addWidget(sub)

        for change in entry.get("changes", []):
            row = QLabel(f"•  {change}")
            row.setObjectName("helpBody")
            row.setWordWrap(True)
            row.setTextFormat(Qt.PlainText)
            row.setTextInteractionFlags(Qt.TextSelectableByMouse)
            cv.addWidget(row)
        return card
