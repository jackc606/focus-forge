"""Dialog to pick an existing HOI4 focus tree to import from the game/mod files."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.focus_import import FocusTreeRef, find_focus_trees

from . import theme as T
from .country_tag_picker import CountryTagPicker
from .widgets import divider, hint, panel_header

_GENERIC_TREE_ID = "generic_focus"

_REF_ROLE = Qt.UserRole


class ImportTreeDialog(QDialog):
    def __init__(self, roots, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Focus Tree")
        self.resize(720, 560)
        self._chosen = None

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Import Focus Tree"))
        v.addWidget(hint("Pick an existing country's focus tree from your game and mod "
                         "files to load it as an editable project."))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by tag or tree id…")
        self._search.textChanged.connect(self._apply_filter)
        v.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Tag", "Tree ID", "Focuses", "Source"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(False)
        self._tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self._tree.itemDoubleClicked.connect(lambda *_: self._accept_selected())
        self._tree.itemSelectionChanged.connect(self._update_ok)
        v.addWidget(self._tree, 1)

        if not roots:
            v.addWidget(hint("No game/mod folders configured — add them in "
                             "Settings → In-game Icons first."))

        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._refs = find_focus_trees(roots)
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._populate()

        # Fallback for countries MD ships no dedicated tree for (Mexico, Morocco,
        # Portugal, …): seed an editable copy of the generic MD tree, namespaced
        # to a chosen country tag so its ids don't collide with MD's own.
        self._generic_ref = next(
            (r for r in self._refs if r.tree_id == _GENERIC_TREE_ID), None)
        v.addWidget(divider())
        v.addWidget(hint("No tree for your country? Start from MD's generic focus "
                         "tree — its focuses are copied in and renamed to your tag."))
        row = QHBoxLayout()
        self._generic_tag = CountryTagPicker()
        self._generic_btn = QPushButton("Start from Generic Tree")
        self._generic_btn.clicked.connect(self._use_generic)
        row.addWidget(self._generic_tag, 1)
        row.addWidget(self._generic_btn)
        v.addLayout(row)
        if self._generic_ref is None:
            self._generic_tag.setEnabled(False)
            self._generic_btn.setEnabled(False)
            self._generic_btn.setToolTip(
                "generic_focus not found — add your game/MD folders in Settings.")

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Import")
        self._buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        self._buttons.accepted.connect(self._accept_selected)
        self._buttons.rejected.connect(self.reject)
        v.addWidget(self._buttons)
        self._update_ok()

    def _populate(self) -> None:
        self._tree.clear()
        for ref in self._refs:
            item = QTreeWidgetItem([
                ref.tag, ref.tree_id, str(ref.focus_count), os.path.basename(ref.file)])
            item.setData(0, _REF_ROLE, ref)
            item.setToolTip(3, ref.file)
            self._tree.addTopLevelItem(item)
        for c in (0, 2, 3):
            self._tree.resizeColumnToContents(c)

    def _apply_filter(self, text: str) -> None:
        q = (text or "").strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            ref = item.data(0, _REF_ROLE)
            hidden = bool(q) and q not in ref.tag.lower() and q not in ref.tree_id.lower()
            item.setHidden(hidden)

    def _update_ok(self) -> None:
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self._tree.selectedItems()))

    def _accept_selected(self) -> None:
        items = self._tree.selectedItems()
        if items:
            self._chosen = items[0].data(0, _REF_ROLE)
            self.accept()

    def _use_generic(self) -> None:
        if self._generic_ref is None:
            return
        text = self._generic_tag.text().strip()
        tag = text.split(" - ", 1)[0].strip().upper()
        tag = "".join(ch for ch in tag if ch.isalnum())[:3]
        if not tag:
            self._generic_tag.setFocus()
            return
        self._chosen = FocusTreeRef(
            tag=tag,
            tree_id=self._generic_ref.tree_id,
            focus_count=self._generic_ref.focus_count,
            file=self._generic_ref.file,
            prefix_ids=True,
        )
        self.accept()

    def selected_ref(self):
        return self._chosen
