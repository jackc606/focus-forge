"""Dialog to pick an existing HOI4 focus tree to import from the game/mod files."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.focus_import import (
    FocusTreeRef,
    find_focus_trees,
    find_focus_trees_in_folder,
)

from . import theme as T
from .country_tag_picker import CountryTagPicker
from .widgets import divider, hint, panel_header

_GENERIC_TREE_ID = "generic_focus"

_REF_ROLE = Qt.UserRole


def _default_mod_dir(roots) -> str:
    """Best guess at the user's HOI4 `mod` folder for the folder picker.

    Prefer the parent of a configured root that already lives under
    ``Hearts of Iron IV/mod`` (so it tracks a non-default install), else the
    standard Documents location, else empty."""
    for root in roots:
        parent = os.path.dirname(os.path.normpath(root))
        if (os.path.basename(parent).lower() == "mod"
                and os.path.basename(os.path.dirname(parent)).lower()
                == "hearts of iron iv"):
            return parent
    standard = os.path.join(
        os.path.expanduser("~"), "Documents", "Paradox Interactive",
        "Hearts of Iron IV", "mod")
    return standard if os.path.isdir(standard) else ""


class ImportTreeDialog(QDialog):
    def __init__(self, roots, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Focus Tree")
        self.resize(720, 560)
        self._chosen = None
        self._roots = list(roots)
        self._added_folders: set = set()  # ad-hoc folders already scanned (dedup)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Import Focus Tree"))
        v.addWidget(hint("Pick an existing country's focus tree from your game and mod "
                         "files to load it as an editable project, or add a custom mod "
                         "folder to import a tree that isn't in your configured roots."))

        row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by tag or tree id…")
        self._search.textChanged.connect(self._apply_filter)
        row.addWidget(self._search, 1)
        self._add_folder_btn = QPushButton("Add Mod Folder…")
        self._add_folder_btn.setToolTip(
            "Scan a mod folder's common/national_focus for focus trees, without "
            "permanently adding it to your Settings roots.")
        self._add_folder_btn.clicked.connect(self._add_folder)
        row.addWidget(self._add_folder_btn)
        v.addLayout(row)

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

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select a mod folder (or its common/national_focus)",
            _default_mod_dir(self._roots))
        if not folder:
            return
        folder = os.path.normpath(folder)
        if folder in self._added_folders:
            QMessageBox.information(self, "Already added",
                                    "That folder's trees are already in the list.")
            return

        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Record the folder + configured roots so import-time loc resolves from
            # the browsed folder first, falling back to the configured game/mod files.
            found = find_focus_trees_in_folder(folder, [*self._roots, folder])
        finally:
            QGuiApplication.restoreOverrideCursor()

        if not found:
            QMessageBox.warning(
                self, "No focus trees found",
                "No focus_tree blocks were found in that folder.\n\n"
                "Pick a mod's root folder (the one containing common/national_focus) "
                "or the national_focus folder itself.")
            return

        # Dedup against trees already shown (same file + tree id).
        seen = {(r.file, r.tree_id) for r in self._refs}
        new = [r for r in found if (r.file, r.tree_id) not in seen]
        self._added_folders.add(folder)
        self._refs.extend(new)
        self._refs.sort(key=lambda t: (t.tag, t.tree_id))
        self._populate()
        self._apply_filter(self._search.text())
        if new:
            self._select_ref(new[0])

    def _select_ref(self, ref) -> None:
        """Select and scroll to the row for ``ref`` (e.g. a just-added tree)."""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, _REF_ROLE) is ref:
                self._tree.setCurrentItem(item)
                self._tree.scrollToItem(item)
                return

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
