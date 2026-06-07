"""Searchable country tag picker — 498 entries, scrollable popup."""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, QStringListModel, Qt, Signal
from PySide6.QtWidgets import QCompleter, QLineEdit

from core.country_tags import MD_COUNTRY_TAGS


class CountryTagPicker(QLineEdit):
    tag_chosen = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Search tag or country name…")
        items = [f"{e.tag} - {e.name}" for e in MD_COUNTRY_TAGS]
        self._model = QStringListModel(items)
        completer = QCompleter(self._model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setMaxVisibleItems(15)
        self.setCompleter(completer)
        completer.activated.connect(self._on_completer_activated)
        self.editingFinished.connect(self._on_editing_finished)

    def set_tag(self, tag: str) -> None:
        for entry in MD_COUNTRY_TAGS:
            if entry.tag == tag:
                self.setText(f"{entry.tag} - {entry.name}")
                return
        self.setText(tag)

    def _on_completer_activated(self, text: str) -> None:
        tag = text.split(" - ", 1)[0].strip().upper()
        self.tag_chosen.emit(tag)
        self.setText(text)

    def _on_editing_finished(self) -> None:
        text = self.text().strip()
        if not text:
            return
        # Match exact tag or "TAG - Name"
        candidate = text.split(" - ", 1)[0].strip().upper()
        for entry in MD_COUNTRY_TAGS:
            if entry.tag == candidate:
                self.setText(f"{entry.tag} - {entry.name}")
                self.tag_chosen.emit(entry.tag)
                return
        # Free-form: emit whatever they typed (uppercased, alnum-stripped)
        cleaned = "".join(ch for ch in candidate if ch.isalnum())[:3]
        if cleaned:
            self.tag_chosen.emit(cleaned)
            self.setText(cleaned)
