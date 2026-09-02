"""Export preview: combobox of files + monospace preview."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

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

        # ----- Pre-flight / post-flight -----
        v.addWidget(section_header("Does it load?"))
        checks = QHBoxLayout()
        checks.setSpacing(T.SPACE_SM)
        self._smoke_btn = QPushButton("Smoke check")
        self._smoke_btn.setToolTip(
            "Parse every generated file with the app's own script reader and apply the "
            "rules the game enforces at load (balanced braces, focus/event structure, "
            "localisation headers + BOM, every focus and event localised).")
        self._smoke_btn.clicked.connect(self._run_smoke_check)
        checks.addWidget(self._smoke_btn)
        self._log_btn = QPushButton("Scan HOI4 error.log")
        self._log_btn.setToolTip(
            "After launching the game with this mod enabled: show the error.log lines "
            "that mention it, mapped back to the focus they come from.")
        self._log_btn.clicked.connect(self._run_log_scan)
        checks.addWidget(self._log_btn)
        checks.addStretch(1)
        v.addLayout(checks)
        self._check_out = QPlainTextEdit()
        self._check_out.setReadOnly(True)
        self._check_out.setFont(mono_font(T.TEXT_BODY))
        self._check_out.setMaximumHeight(T.TEXTAREA_TALL)
        self._check_out.setPlaceholderText("Results appear here.")
        v.addWidget(self._check_out)

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

    # ----- pre-flight / post-flight -----
    def _run_smoke_check(self) -> None:
        from core.export_check import smoke_check
        if self._stale or not self._files:
            self.refresh()
        issues = smoke_check(self._files)
        if not issues:
            self._check_out.setPlainText(
                f"Smoke check passed: {len(self._files)} file(s) parse cleanly and every focus, "
                f"idea and event is localised.")
            return
        errors = sum(1 for i in issues if i.severity == "error")
        lines = [f"Smoke check: {errors} error(s), {len(issues) - errors} warning(s).", ""]
        lines += [f"[{i.severity}] {i.message}" for i in issues]
        self._check_out.setPlainText("\n".join(lines))

    def _run_log_scan(self) -> None:
        import os
        from core.export_check import default_error_log, format_hits, log_is_stale, scan_error_log
        from core.mod_scaffold import find_mod_root
        path = default_error_log()
        if not os.path.isfile(path):
            self._check_out.setPlainText(
                f"No error.log at {path}\nLaunch Hearts of Iron IV with the mod enabled once, quit, "
                f"then scan again.")
            return
        if self._stale or not self._files:
            self.refresh()
        project = self._model.project
        mod_dir = (project.exportDir or "").strip() or (find_mod_root(self._model.path) or "")
        hits = scan_error_log(self._files, project, path, mod_dir=mod_dir)
        head = [f"{len(hits)} line(s) in error.log mention this mod."]
        if log_is_stale(path, mod_dir):
            head.append("Note: the mod was exported after this log was written — launch again for a "
                        "fresh log; line references may be stale.")
        self._check_out.setPlainText("\n".join(head) + "\n\n" + format_hits(hits))
