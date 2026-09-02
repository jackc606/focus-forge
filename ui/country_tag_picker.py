"""Searchable country tag picker — scrollable popup over the live MD tag list.

Items come from the configured game roots (MD main vs beta differ), so the
list is rebuilt when ``roots_changed`` fires, keeping the chosen tag."""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, QStringListModel, Qt, Signal
from PySide6.QtWidgets import QCompleter, QLineEdit

from .country_tags_live import current_country_tags


def clean_country_tag_text(text: str) -> str:
    candidate = (text or "").split(" - ", 1)[0].strip().upper()
    return "".join(ch for ch in candidate if ch.isalnum())[:3]


class CountryTagPicker(QLineEdit):
    tag_chosen = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Search tag or country name…")
        self._entries = list(current_country_tags())
        self._model = QStringListModel(self._items())
        completer = QCompleter(self._model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setMaxVisibleItems(15)
        self.setCompleter(completer)
        completer.activated.connect(self._on_completer_activated)
        self.editingFinished.connect(self._on_editing_finished)
        # Imported lazily by country_tags_live too; a bound-method slot on a
        # QObject receiver is auto-disconnected when this widget is destroyed.
        from .icon_provider import provider
        provider().roots_changed.connect(self._refresh_entries)

    def _items(self) -> list:
        return [f"{e.tag} - {e.name}" for e in self._entries]

    def _refresh_entries(self) -> None:
        """Roots changed (e.g. user switched MD main -> beta): rebuild the
        completer items but keep whatever tag is currently chosen — a tag the
        new list lacks simply shows bare, exactly like a free-form entry."""
        current = self.current_tag()
        self._entries = list(current_country_tags())
        self._model.setStringList(self._items())
        if current:
            self.set_tag(current)

    def set_tag(self, tag: str) -> None:
        for entry in self._entries:
            if entry.tag == tag:
                self.setText(f"{entry.tag} - {entry.name}")
                return
        self.setText(tag)

    def current_tag(self) -> str:
        return clean_country_tag_text(self.text())

    def _on_completer_activated(self, text: str) -> None:
        tag = clean_country_tag_text(text)
        self.tag_chosen.emit(tag)
        self.setText(text)

    def _on_editing_finished(self) -> None:
        text = self.text().strip()
        if not text:
            return
        # Match exact tag or "TAG - Name"
        candidate = clean_country_tag_text(text)
        for entry in self._entries:
            if entry.tag == candidate:
                self.setText(f"{entry.tag} - {entry.name}")
                self.tag_chosen.emit(entry.tag)
                return
        # Free-form: emit whatever they typed (uppercased, alnum-stripped)
        cleaned = candidate
        if cleaned:
            self.tag_chosen.emit(cleaned)
            self.setText(cleaned)
