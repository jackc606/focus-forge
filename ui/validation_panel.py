"""Validation tab: scrollable issue list, click to jump to focus."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from . import theme as T
from .project_model import ProjectModel
from .widgets import panel_header, pill


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
        # Clear
        while self._issues_box.count():
            child = self._issues_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        for issue in issues:
            self._issues_box.addWidget(self._issue_card(issue))

    def _issue_card(self, issue) -> QFrame:
        is_error = issue.severity == "error"
        frame = QFrame()
        frame.setObjectName("issueCardError" if is_error else "issueCardWarning")
        frame.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(frame)
        h.setContentsMargins(T.SPACE_SM, 6, T.SPACE_SM, 6)
        h.setSpacing(T.SPACE_SM)
        symbol = QLabel("×" if is_error else "!")  # render in the UI font (Bahnschrift lacks ✕/⚠)
        symbol.setObjectName("issueSymbolError" if is_error else "issueSymbolWarning")
        symbol.setFixedWidth(16)
        symbol.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        text = QLabel(f"<b>{issue.code}</b>: {issue.message}")
        text.setObjectName("issueTextError" if is_error else "issueTextWarning")
        text.setWordWrap(True)
        h.addWidget(symbol)
        h.addWidget(text, 1)
        focus_id = issue.focusId
        if focus_id:
            frame.mouseReleaseEvent = lambda evt: self._model.set_selection(focus_id)  # type: ignore[attr-defined]
        return frame
