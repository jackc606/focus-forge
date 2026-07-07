"""Manage the focus tree's shortcuts (bottom-left branch bookmarks) — list,
create, edit, delete, reorder.

Shortcuts have no unique id and their order is meaningful (the game shows the
first 8), so this is a dedicated index-keyed dialog rather than a subclass of
the id-keyed ``ListManagerDialog``."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import theme as T
from .shortcut_editor import ShortcutEditorDialog
from .widgets import hint, panel_header


class ShortcutsManagerDialog(QDialog):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Tree Shortcuts")
        self.resize(*T.DIALOG_SM)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Focus Tree Shortcuts"))
        v.addWidget(hint("Branch bookmarks shown bottom-left in-game; clicking one "
                         "jumps the camera to its target focus. HOI4 shows at most "
                         "8 slots, in this order."))

        self._list = QListWidget()
        self._list.itemActivated.connect(lambda *_: self._edit())
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        v.addWidget(self._list, 1)

        self._empty = hint("No shortcuts yet — click New... to add one.")
        self._empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self._empty)

        row = QHBoxLayout()
        self._new_btn = QPushButton("New...")
        self._edit_btn = QPushButton("Edit...")
        self._del_btn = QPushButton("Delete")
        self._up_btn = QPushButton("Move Up")
        self._down_btn = QPushButton("Move Down")
        self._new_btn.setObjectName("primary")
        self._new_btn.clicked.connect(self._new)
        self._edit_btn.clicked.connect(self._edit)
        self._del_btn.clicked.connect(self._delete)
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn.clicked.connect(lambda: self._move(1))
        for btn in (self._new_btn, self._edit_btn, self._del_btn,
                    self._up_btn, self._down_btn):
            row.addWidget(btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

        self._refresh()

    # ----- helpers -----
    def _shortcuts(self) -> list:
        return self._model.project.shortcuts

    def _selected_index(self) -> int:
        return self._list.currentRow()

    def _refresh(self, select: int = -1) -> None:
        self._list.clear()
        shortcuts = self._shortcuts()
        for sc in shortcuts:
            label = sc.label or "(no label)"
            target = sc.target or "(no target)"
            QListWidgetItem(f"{label}  ->  {target}", self._list)
        self._empty.setVisible(len(shortcuts) == 0)
        if shortcuts:
            row = min(max(select, 0), len(shortcuts) - 1) if select >= 0 else -1
            if row >= 0:
                self._list.setCurrentRow(row)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        idx = self._selected_index()
        has = idx >= 0
        n = len(self._shortcuts())
        self._edit_btn.setEnabled(has)
        self._del_btn.setEnabled(has)
        self._up_btn.setEnabled(has and idx > 0)
        self._down_btn.setEnabled(has and 0 <= idx < n - 1)

    # ----- actions -----
    def _new(self) -> None:
        dlg = ShortcutEditorDialog(self._model, parent=self)
        if dlg.exec():
            self._model.add_shortcut(dlg.result_shortcut())
            self._refresh(select=len(self._shortcuts()) - 1)
            self._model.status_message.emit("Added tree shortcut.")

    def _edit(self) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        existing = self._shortcuts()[idx]
        dlg = ShortcutEditorDialog(self._model, shortcut=existing, parent=self)
        if dlg.exec():
            self._model.update_shortcut(idx, dlg.result_shortcut())
            self._refresh(select=idx)
            self._model.status_message.emit("Updated tree shortcut.")

    def _delete(self) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        sc = self._shortcuts()[idx]
        who = sc.label or sc.target or f"#{idx + 1}"
        if QMessageBox.question(self, "Delete shortcut",
                                f"Delete tree shortcut “{who}”?") != QMessageBox.Yes:
            return
        self._model.delete_shortcut(idx)
        self._refresh(select=idx)
        self._model.status_message.emit("Deleted tree shortcut.")

    def _move(self, delta: int) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        self._model.move_shortcut(idx, delta)
        self._refresh(select=idx + delta)
