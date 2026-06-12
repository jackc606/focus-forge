"""Export preview: combobox of files + monospace preview."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from core.exporters import export_project_files

from . import theme as T
from .no_scroll import NoScrollComboBox
from .project_model import ProjectModel
from .widgets import mono_font, panel_header, section_header


class ExportPanel(QWidget):
    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Export"))
        v.addWidget(section_header("Output file"))

        self._combo = NoScrollComboBox()
        self._combo.setToolTip("Generated file to preview below")
        self._combo.currentIndexChanged.connect(self._render_selected)
        v.addWidget(self._combo)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(mono_font(T.TEXT_BODY))
        v.addWidget(self._preview, 1)

        self._files: list = []
        # Re-exporting the whole project is the single most expensive listener
        # on project_changed — only do it when this tab is actually visible,
        # debounced so edit bursts cost one export.
        self._stale = True
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self.refresh)
        self._model.project_changed.connect(self._on_project_changed)

    def _on_project_changed(self) -> None:
        self._stale = True
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self) -> None:
        self._stale = False
        self._files = export_project_files(self._model.project)
        self._combo.blockSignals(True)
        self._combo.clear()
        for f in self._files:
            label = f.relativePath + (" (BOM)" if f.bom else "")
            self._combo.addItem(label, f.relativePath)
        self._combo.blockSignals(False)
        self._combo.setCurrentIndex(0 if self._files else -1)
        self._render_selected()

    def _render_selected(self) -> None:
        idx = self._combo.currentIndex()
        if idx < 0 or idx >= len(self._files):
            self._preview.setPlainText("")
            return
        self._preview.setPlainText(self._files[idx].content)
