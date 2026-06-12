"""Left sidebar: focus list + warnings summary."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme as T
from .project_model import ProjectModel
from .widgets import divider, issue_card, section_header


class FocusesListPanel(QWidget):
    search_changed = Signal(str)

    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._query = ""
        self.setMinimumWidth(260)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SPACE_MD, T.SPACE_MD, T.SPACE_MD, T.SPACE_MD)
        layout.setSpacing(T.SPACE_MD)

        # Search box (filters this list + highlights the canvas)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search focuses…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_text)
        layout.addWidget(self._search)

        # Focuses section
        layout.addWidget(section_header("Focuses"))
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_clicked)
        layout.addWidget(self._list, 3)

        layout.addWidget(divider())

        # Warnings section
        layout.addWidget(section_header("Warnings"))
        self._warnings_box = QVBoxLayout()
        self._warnings_box.setSpacing(T.SPACE_SM)
        warn_holder = QWidget()
        warn_holder.setLayout(self._warnings_box)
        warn_holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout.addWidget(warn_holder, 2)

        # Debounced rebuild: a burst of edits (typing a title) coalesces into
        # one list rebuild instead of one per keystroke.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self.refresh)
        self._model.project_changed.connect(self._refresh_timer.start)
        self._model.selection_changed.connect(self._sync_selection)
        self._model.validation_changed.connect(self._refresh_warnings)
        self.refresh()
        self._refresh_warnings(self._model.issues())

    def _on_search_text(self, text: str) -> None:
        self._query = text.strip().lower()
        self._apply_filter()
        self.search_changed.emit(text.strip())

    def _apply_filter(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(bool(self._query) and self._query not in item.text().lower())

    def refresh(self) -> None:
        scroll = self._list.verticalScrollBar().value()
        self._list.blockSignals(True)
        self._list.clear()
        for f in self._model.project.focuses:
            item = QListWidgetItem(f"{f.title}\n{f.id}")
            item.setData(Qt.UserRole, f.id)
            self._list.addItem(item)
            if f.id == self._model.selected_id:
                item.setSelected(True)
        self._list.blockSignals(False)
        self._apply_filter()
        self._list.verticalScrollBar().setValue(scroll)

    def _sync_selection(self, focus_id: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setSelected(item.data(Qt.UserRole) == focus_id)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self._model.set_selection(item.data(Qt.UserRole))

    def _refresh_warnings(self, issues: list) -> None:
        # clear
        while self._warnings_box.count():
            child = self._warnings_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        if not issues:
            placeholder = QLabel("No validation issues.")
            placeholder.setObjectName("muted")
            self._warnings_box.addWidget(placeholder)
            self._warnings_box.addStretch(1)
            return
        for issue in issues[:6]:
            self._warnings_box.addWidget(issue_card(issue.severity, issue.message))
        if len(issues) > 6:
            more = QLabel(f"+{len(issues) - 6} more …")
            more.setObjectName("muted")
            self._warnings_box.addWidget(more)
        self._warnings_box.addStretch(1)
