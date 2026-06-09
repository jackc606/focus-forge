"""Startup launcher — shown when Focus Forge opens, instead of auto-loading a
project. Lets the user create a new submod, open a project, reopen a recent one,
or explore the bundled sample."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from core.version import version_label

from . import theme as T
from .widgets import hint, panel_header, section_header

_PATH_ROLE = Qt.UserRole


class WelcomeDialog(QDialog):
    def __init__(self, recent=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to Focus Forge")
        self.resize(560, 480)
        self.choice = None          # 'new' | 'open' | 'recent' | 'sample' | None
        self.recent_path = None

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_XL, T.SPACE_XL, T.SPACE_XL, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Focus Forge"))
        v.addWidget(hint(f"{version_label()} — HOI4 / Millennium Dawn focus-tree editor"))
        v.addSpacing(T.SPACE_SM)

        new_btn = QPushButton("＋   Create New Submod")
        new_btn.setObjectName("primary")
        new_btn.setMinimumHeight(40)
        new_btn.setToolTip("Start a fresh submod project (optionally from an existing tree).")
        new_btn.clicked.connect(lambda: self._choose("new"))
        v.addWidget(new_btn)

        open_btn = QPushButton("📂   Open Project…")
        open_btn.setMinimumHeight(40)
        open_btn.setToolTip("Open an existing .focusforge.json project.")
        open_btn.clicked.connect(lambda: self._choose("open"))
        v.addWidget(open_btn)

        recent = list(recent or [])
        if recent:
            v.addSpacing(T.SPACE_SM)
            v.addWidget(section_header("Recent"))
            self._list = QListWidget()
            self._list.setAlternatingRowColors(False)
            for path in recent:
                item = QListWidgetItem(f"{_pretty_name(path)}\n{path}")
                item.setData(_PATH_ROLE, path)
                item.setToolTip(path)
                self._list.addItem(item)
            self._list.itemDoubleClicked.connect(self._open_recent_item)
            self._list.itemActivated.connect(self._open_recent_item)
            v.addWidget(self._list, 1)
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

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def _open_recent_item(self, item: QListWidgetItem) -> None:
        self.choice = "recent"
        self.recent_path = item.data(_PATH_ROLE)
        self.accept()


def _pretty_name(path: str) -> str:
    base = os.path.basename(path)
    for suffix in (".focusforge.json", ".json"):
        if base.lower().endswith(suffix):
            return base[: -len(suffix)]
    return base
