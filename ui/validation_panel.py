"""Validation tab: scrollable issue list, click to jump to focus."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from . import theme as T
from .project_model import ProjectModel
from .widgets import hint, issue_card, panel_header, pill


class ValidationPanel(QWidget):
    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        self._holder = QWidget()
        scroll.setWidget(self._holder)
        self._box = QVBoxLayout(self._holder)
        self._box.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        self._box.setSpacing(T.SPACE_MD)

        self._box.addWidget(panel_header("Validation"))

        self._summary_row = QHBoxLayout()
        self._summary_row.setSpacing(T.SPACE_SM)
        self._summary_row.addStretch(1)
        self._box.addLayout(self._summary_row)

        self._empty = hint("No validation issues — the project exports cleanly.")
        self._box.addWidget(self._empty)

        self._issues_box = QVBoxLayout()
        self._issues_box.setSpacing(T.SPACE_SM)
        self._box.addLayout(self._issues_box)
        self._box.addStretch(1)

        self._model.validation_changed.connect(self.refresh)
        self.refresh(self._model.issues())

    def _set_summary(self, errors: int, warnings: int) -> None:
        # Clear the row
        while self._summary_row.count():
            child = self._summary_row.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        if errors == 0 and warnings == 0:
            self._summary_row.addWidget(pill("Export-ready", "ok"))
        else:
            self._summary_row.addWidget(pill(f"{errors} error{'s' if errors != 1 else ''}", "error"))
            self._summary_row.addWidget(pill(f"{warnings} warning{'s' if warnings != 1 else ''}", "warn"))
        self._summary_row.addStretch(1)

    def refresh(self, issues: list) -> None:
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        self._set_summary(errors, warnings)
        self._empty.setVisible(not issues)
        # Clear
        while self._issues_box.count():
            child = self._issues_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        for issue in issues:
            on_click = None
            if issue.focusId:
                on_click = lambda fid=issue.focusId: self._model.set_selection(fid)
            self._issues_box.addWidget(issue_card(
                issue.severity, f"<b>{issue.code}</b>: {issue.message}",
                on_click=on_click))
