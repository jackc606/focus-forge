"""Manage the project's custom events — list, create, edit, delete.

The authoring widget itself is ``EventEditorDialog``; this dialog is the browser
that lets you pick an existing event to edit (or make a new one). Mirrors
``IdeasManagerDialog``.
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
from .event_editor import EventEditorDialog
from .widgets import hint, panel_header

_ID_ROLE = Qt.UserRole


class EventsManagerDialog(QDialog):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Events")
        self.resize(460, 480)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Events"))
        v.addWidget(hint("Custom country/news events you've authored in this project. "
                         "Fire them from a focus reward (Country Event) or another event."))

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
        for event in self._model.project.events:
            opt_n = len(event.options or [])
            refs = self._model.event_reference_count(event.id)
            parts = [f"{opt_n} option{'s' if opt_n != 1 else ''}"]
            if refs:
                parts.append(f"{refs} ref{'s' if refs != 1 else ''}")
            label = f"{event.title or event.id}\n{event.id}  ·  {'  ·  '.join(parts)}"
            item = QListWidgetItem(label)
            item.setData(_ID_ROLE, event.id)
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
        dlg = EventEditorDialog(self._model, parent=self)
        if not dlg.exec():
            return
        event = dlg.result_event()
        if not event.id:
            return
        final = self._model.add_event(event)
        self._refresh()
        self._select(final)
        self._model.status_message.emit(f"Created event {final}.")

    def _edit(self) -> None:
        old_id = self._selected_id()
        if old_id is None:
            return
        event = next((e for e in self._model.project.events if e.id == old_id), None)
        if event is None:
            return
        dlg = EventEditorDialog(self._model, event=event, parent=self)
        if not dlg.exec():
            return
        updated = dlg.result_event()
        if not updated.id:
            return
        final = self._model.update_event(old_id, updated)
        self._refresh()
        self._select(final)
        self._model.status_message.emit(f"Updated event {final}.")

    def _delete(self) -> None:
        event_id = self._selected_id()
        if event_id is None:
            return
        refs = self._model.event_reference_count(event_id)
        msg = f"Delete event “{event_id}”?"
        if refs:
            msg += (f"\n\nIt is referenced by {refs} focus reward"
                    f"{'s' if refs != 1 else ''}; those references will be left "
                    "pointing at a missing event.")
        if QMessageBox.question(self, "Delete event", msg) != QMessageBox.Yes:
            return
        self._model.delete_event(event_id)
        self._refresh()
        self._model.status_message.emit(f"Deleted event {event_id}.")

    def _select(self, event_id: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(_ID_ROLE) == event_id:
                self._list.setCurrentRow(i)
                return
