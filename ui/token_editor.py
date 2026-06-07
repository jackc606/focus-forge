"""Comma-separated token list backed by a QLineEdit + QCompleter."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCompleter, QLineEdit


class TokenEditor(QLineEdit):
    tokens_changed = Signal(list)  # list[str]

    def __init__(self, suggestions: list = None, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self._suggestions: list = list(suggestions or [])
        if self._suggestions:
            completer = QCompleter(self._suggestions, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.setCompleter(completer)
        self.editingFinished.connect(self._emit_change)

    def set_tokens(self, tokens: list) -> None:
        text = ", ".join(tokens or [])
        if self.text() != text:
            self.blockSignals(True)
            self.setText(text)
            self.blockSignals(False)

    def tokens(self) -> list:
        return [t.strip() for t in self.text().split(",") if t.strip()]

    def update_suggestions(self, suggestions: list) -> None:
        self._suggestions = list(suggestions or [])
        completer = QCompleter(self._suggestions, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompleter(completer)

    def _emit_change(self) -> None:
        self.tokens_changed.emit(self.tokens())
