"""Manage the project's custom ideas / national spirits — list, create, edit, delete.

The authoring widget itself is ``IdeaEditorDialog``; this dialog is the browser
that lets you pick an existing idea to edit (or make a new one).
"""
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
from .idea_editor import IdeaEditorDialog
from .widgets import hint, panel_header

_ID_ROLE = Qt.UserRole


def _modifier_count(idea) -> int:
    return sum(1 for ln in (idea.modifierRawLines or [])
              if ln.strip() and not ln.strip().startswith("modifier")
              and ln.strip() not in ("{", "}"))


class IdeasManagerDialog(QDialog):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Ideas")
        self.resize(460, 480)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Ideas / National Spirits"))
        v.addWidget(hint("Custom ideas you've authored in this project. Select one "
                         "to edit, or create a new one."))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda *_: self._edit())
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        v.addWidget(self._list, 1)

        row = QHBoxLayout()
        self._new_btn = QPushButton("New…")
        self._edit_btn = QPushButton("Edit…")
        self._del_btn = QPushButton("Delete")
        self._new_btn.setObjectName("primary")
        self._new_btn.clicked.connect(self._new)
        self._edit_btn.clicked.connect(self._edit)
        self._del_btn.clicked.connect(self._delete)
        row.addWidget(self._new_btn)
        row.addWidget(self._edit_btn)
        row.addWidget(self._del_btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

        self._refresh()

    # ----- helpers -----
    def _refresh(self) -> None:
        self._list.clear()
        for idea in self._model.project.ideas:
            n = _modifier_count(idea)
            label = f"{idea.title or idea.id}\n{idea.id}  ·  {n} modifier{'s' if n != 1 else ''}"
            item = QListWidgetItem(label)
            item.setData(_ID_ROLE, idea.id)
            self._list.addItem(item)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has = self._selected_id() is not None
        self._edit_btn.setEnabled(has)
        self._del_btn.setEnabled(has)

    def _selected_id(self):
        items = self._list.selectedItems()
        return items[0].data(_ID_ROLE) if items else None

    # ----- actions -----
    def _new(self) -> None:
        dlg = IdeaEditorDialog(self._model, parent=self)
        if not dlg.exec():
            return
        idea = dlg.result_idea()
        if not idea.id:
            return
        final = self._model.add_idea(idea)
        self._refresh()
        self._select(final)
        self._model.status_message.emit(f"Created idea {final}.")

    def _edit(self) -> None:
        old_id = self._selected_id()
        if old_id is None:
            return
        idea = next((i for i in self._model.project.ideas if i.id == old_id), None)
        if idea is None:
            return
        dlg = IdeaEditorDialog(self._model, idea=idea, parent=self)
        if not dlg.exec():
            return
        updated = dlg.result_idea()
        if not updated.id:
            return
        final = self._model.update_idea(old_id, updated)
        self._refresh()
        self._select(final)
        self._model.status_message.emit(f"Updated idea {final}.")

    def _delete(self) -> None:
        idea_id = self._selected_id()
        if idea_id is None:
            return
        refs = self._model.idea_reference_count(idea_id)
        msg = f"Delete idea “{idea_id}”?"
        if refs:
            msg += (f"\n\nIt is referenced by {refs} focus reward"
                    f"{'s' if refs != 1 else ''}; those references will be left "
                    "pointing at a missing idea.")
        if QMessageBox.question(self, "Delete idea", msg) != QMessageBox.Yes:
            return
        self._model.delete_idea(idea_id)
        self._refresh()
        self._model.status_message.emit(f"Deleted idea {idea_id}.")

    def _select(self, idea_id: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(_ID_ROLE) == idea_id:
                self._list.setCurrentRow(i)
                return
