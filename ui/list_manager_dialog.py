"""Shared list-browser dialog: project entities with New / Edit / Delete / Close.

``IdeasManagerDialog`` and ``EventsManagerDialog`` are thin subclasses — they
supply labels and the model calls via the hook methods; all scaffolding (list,
button row, selection sync, double-click-to-edit, empty state) lives here.
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
from .widgets import hint, panel_header

_ID_ROLE = Qt.UserRole


class ListManagerDialog(QDialog):
    _kind = "item"  # noun used in prompts and status messages
    _ref_noun = "focus reward"  # where _reference_count() references come from
    _empty_text = "Nothing here yet — click New… to create one."

    def __init__(self, model, *, window_title: str, header: str,
                 hint_text: str, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle(window_title)
        self.resize(*T.DIALOG_SM)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header(header))
        v.addWidget(hint(hint_text))

        self._list = QListWidget()
        # activated covers both double-click and the platform edit key (Enter on
        # Windows), so keyboard users can open the editor from the list.
        self._list.itemActivated.connect(lambda *_: self._edit())
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        v.addWidget(self._list, 1)

        self._empty = hint(self._empty_text)
        self._empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self._empty)

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
        for btn in self._extra_buttons():
            row.addWidget(btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

        self._refresh()

    # ----- hooks for subclasses -----
    def _extra_buttons(self) -> list:
        """Extra QPushButtons inserted after Delete (e.g. 'Categories…')."""
        return []

    def _items(self):
        """The project's entities, each with an ``.id``."""
        raise NotImplementedError

    def _item_label(self, entity) -> str:
        raise NotImplementedError

    def _edit_entity(self, existing=None):
        """Open the editor (blank when ``existing`` is None); return the
        resulting entity, or None if the user cancelled."""
        raise NotImplementedError

    def _model_add(self, entity) -> str:
        raise NotImplementedError

    def _model_update(self, old_id: str, entity) -> str:
        raise NotImplementedError

    def _model_delete(self, entity_id: str) -> None:
        raise NotImplementedError

    def _reference_count(self, entity_id: str) -> int:
        return 0

    # ----- scaffolding -----
    def _refresh(self) -> None:
        self._list.clear()
        for entity in self._items():
            item = QListWidgetItem(self._item_label(entity))
            item.setData(_ID_ROLE, entity.id)
            self._list.addItem(item)
        self._empty.setVisible(self._list.count() == 0)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has = self._selected_id() is not None
        self._edit_btn.setEnabled(has)
        self._del_btn.setEnabled(has)

    def _selected_id(self):
        items = self._list.selectedItems()
        return items[0].data(_ID_ROLE) if items else None

    def _select(self, entity_id: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(_ID_ROLE) == entity_id:
                self._list.setCurrentRow(i)
                return

    # ----- actions -----
    def _new(self) -> None:
        entity = self._edit_entity(None)
        if entity is None or not entity.id:
            return
        final = self._model_add(entity)
        self._refresh()
        self._select(final)
        self._model.status_message.emit(f"Created {self._kind} {final}.")

    def _edit(self) -> None:
        old_id = self._selected_id()
        if old_id is None:
            return
        existing = next((e for e in self._items() if e.id == old_id), None)
        if existing is None:
            return
        entity = self._edit_entity(existing)
        if entity is None or not entity.id:
            return
        final = self._model_update(old_id, entity)
        self._refresh()
        self._select(final)
        self._model.status_message.emit(f"Updated {self._kind} {final}.")

    def _delete(self) -> None:
        entity_id = self._selected_id()
        if entity_id is None:
            return
        refs = self._reference_count(entity_id)
        msg = f"Delete {self._kind} “{entity_id}”?"
        if refs:
            msg += (f"\n\nIt is referenced by {refs} {self._ref_noun}"
                    f"{'s' if refs != 1 else ''}; those references will be left "
                    f"pointing at a missing {self._kind}.")
        if QMessageBox.question(self, f"Delete {self._kind}", msg) != QMessageBox.Yes:
            return
        self._model_delete(entity_id)
        self._refresh()
        self._model.status_message.emit(f"Deleted {self._kind} {entity_id}.")
