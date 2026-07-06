"""LLM tab: prepare markdown context / import edited JSON."""
from __future__ import annotations

import json
import re

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.exporters import export_llm_markdown
from core.serialization import project_from_dict

from . import theme as T
from .project_model import ProjectModel
from .widgets import hint, mono_font, panel_header


class LlmPanel(QWidget):
    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("LLM Round-trip"))
        v.addWidget(hint(
            "Prepare a Markdown/JSON snapshot for an AI agent to edit, then paste "
            "the returned JSON below and import it back into the project."))

        h = QHBoxLayout()
        h.setSpacing(T.SPACE_SM)
        prep_btn = QPushButton("Prepare LLM Context")
        prep_btn.clicked.connect(self._prepare)
        import_btn = QPushButton("Import Edited JSON")
        import_btn.clicked.connect(self._import)
        h.addWidget(prep_btn)
        h.addWidget(import_btn)
        h.addStretch(1)
        v.addLayout(h)

        self._area = QPlainTextEdit()
        self._area.setFont(mono_font(T.TEXT_BODY))
        v.addWidget(self._area, 1)

    def _prepare(self) -> None:
        markdown = export_llm_markdown(self._model.project)
        self._area.setPlainText(markdown)
        QGuiApplication.clipboard().setText(markdown)
        self._model.status_message.emit("LLM project markdown prepared and copied to clipboard.")

    def _import(self) -> None:
        text = self._area.toPlainText()
        # Try to extract a fenced ```json … ``` block first; fall back to whole text.
        match = re.search(r"```json\s*(.+?)```", text, re.DOTALL)
        payload = match.group(1) if match else text
        try:
            data = json.loads(payload)
            project = project_from_dict(data)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", f"Could not parse JSON:\n{exc}")
            return
        # dirty=True: the imported project only exists in memory — it must be
        # flagged unsaved so the close prompt / autosave don't silently drop it.
        self._model.replace_project(project, path=self._model.path, dirty=True)
        self._model.status_message.emit("Imported LLM JSON.")
