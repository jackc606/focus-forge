"""Export preview: combobox of files + monospace preview, headed by the
"does this replace or duplicate a Millennium Dawn tree?" status line."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from core.exporters import export_project_files, focus_file_basename
from core.tree_index import BASE_MOD_NAME, current_index, find_collisions

from . import theme as T
from .no_scroll import NoScrollComboBox
from .project_model import ProjectModel
from .widgets import mono_font, panel_header, section_header


def _configured_roots() -> list:
    """The game/MD roots from Settings (a seam tests point at a temp root)."""
    try:
        from .icon_provider import provider
        return list(provider().roots())
    except Exception:
        return []


class ExportPanel(QWidget):
    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Export"))

        # Replace / duplicate / new status against the base mod's trees. The
        # one line that would have told the Nigeria user their export was
        # about to load twice.
        status_row = QHBoxLayout()
        status_row.setSpacing(T.SPACE_SM)
        self._status = QLabel("")
        self._status.setObjectName("pillNeutral")
        self._status.setWordWrap(True)
        status_row.addWidget(self._status, 1)
        self._fix_btn = QPushButton("Fix")
        self._fix_btn.setObjectName("primary")
        self._fix_btn.setToolTip("Rename the export file so your tree replaces "
                                 f"{BASE_MOD_NAME}'s, or prefix every focus id instead.")
        self._fix_btn.clicked.connect(self._run_fix)
        self._fix_btn.setVisible(False)
        status_row.addWidget(self._fix_btn)
        v.addLayout(status_row)
        self._status_kind = ""

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
        # The status line is cheap (cached index) and must follow validation
        # too: that is when the background base-tree index lands.
        self._model.validation_changed.connect(lambda _issues: self._refresh_status())
        self._refresh_status()

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
        self._refresh_status()
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

    # ----- replace / duplicate status -----
    def _set_status(self, text: str, kind: str) -> None:
        """kind: 'ok' | 'error' | 'neutral' — restyled only when it changes."""
        self._status.setText(text)
        self._fix_btn.setVisible(kind == "error")
        if kind != self._status_kind:
            self._status_kind = kind
            self._status.setObjectName({"ok": "pillOk", "error": "pillError"}.get(kind, "pillNeutral"))
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)

    def collision_report(self):
        """The project's CollisionReport against the configured roots, or None
        while there are no roots / the index is still building (never blocks)."""
        roots = _configured_roots()
        if not roots:
            return None
        index = current_index(lambda: roots, block=False)
        if index is None:
            return None
        return find_collisions(self._model.project, index)

    def _refresh_status(self) -> None:
        roots = _configured_roots()
        export = focus_file_basename(self._model.project.exportSettings)
        if not roots:
            self._set_status(f"New tree ({export})  (MD folder not configured — can't check)",
                             "neutral")
            return
        report = self.collision_report()
        if report is None:
            self._set_status(f"New tree ({export})  (checking {BASE_MOD_NAME}'s trees…)", "neutral")
            return
        if report.is_problem:
            base = report.suggested_basename or ""
            self._set_status(f"Would duplicate MD's {base} — click Fix", "error")
        elif report.replaces:
            self._set_status(f"Replaces {BASE_MOD_NAME}'s {report.replaces} ✓", "ok")
        else:
            self._set_status(f"New tree ({export})", "neutral")

    def _run_fix(self) -> None:
        from .export_preflight import run_export_preflight
        run_export_preflight(self, self._model, _configured_roots())
        self._refresh_status()

    # ----- pre-flight / post-flight -----
    def _run_smoke_check(self) -> None:
        from core.export_check import smoke_check
        if self._stale or not self._files:
            self.refresh()
        issues = smoke_check(self._files, known_loc=self._model.known_tooltip_loc())
        if not issues:
            self._check_out.setPlainText(
                f"Smoke check passed: {len(self._files)} file(s) parse cleanly and every focus, "
                f"idea, event and tooltip is localised.")
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
