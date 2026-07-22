"""Settings tab: project metadata, country tag picker, base tree button."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.base_tree import apply_base_tree_to_project
from core.version import version_label

from . import theme as T
from .country_tag_picker import CountryTagPicker
from .no_scroll import NoScrollComboBox, NoScrollSpinBox
from .icon_provider import autodetect_roots, provider
from .project_model import ProjectModel
from .widgets import hint, panel_header, section_header


_AUTOSAVE_OPTIONS = [
    (0, "Off"),
    (1, "Every 1 minute"),
    (2, "Every 2 minutes"),
    (5, "Every 5 minutes"),
    (10, "Every 10 minutes"),
    (15, "Every 15 minutes"),
]


class SettingsPanel(QWidget):
    # Emitted (with the interval in minutes, 0 = off) when the user changes the
    # autosave setting, so the main window can reconfigure its timer.
    autosave_changed = Signal(int)
    # Emitted when the user clicks "Check for Updates" — the main window owns
    # the update worker and dialog, so it runs the check and reports back.
    check_updates_requested = Signal()

    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._suspend = False
        self._app_settings = QSettings("FocusForge", "FocusForge")

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Settings"))

        # ----- Project -----
        v.addWidget(section_header("Project"))
        project_form = QFormLayout()
        project_form.setSpacing(T.SPACE_SM)
        v.addLayout(project_form)

        self._project_name = QLineEdit()
        project_form.addRow("Project Name", self._project_name)

        self._country_tag = CountryTagPicker()
        project_form.addRow("Country Tag", self._country_tag)

        self._tree_id = QLineEdit()
        project_form.addRow("Tree ID", self._tree_id)

        # ----- Export -----
        v.addWidget(section_header("Export"))
        export_form = QFormLayout()
        export_form.setSpacing(T.SPACE_SM)
        v.addLayout(export_form)

        self._mod_prefix = QLineEdit()
        export_form.addRow("Mod Prefix", self._mod_prefix)

        self._focus_file = QLineEdit()
        export_form.addRow("Focus File Name", self._focus_file)

        self._loc_prefix = QLineEdit()
        export_form.addRow("Localization Prefix", self._loc_prefix)

        cfp_box = QHBoxLayout()
        self._cfp_x = NoScrollSpinBox()
        self._cfp_x.setRange(0, 999999)
        self._cfp_y = NoScrollSpinBox()
        self._cfp_y.setRange(0, 999999)
        cfp_box.addWidget(QLabel("x"))
        cfp_box.addWidget(self._cfp_x)
        cfp_box.addWidget(QLabel("y"))
        cfp_box.addWidget(self._cfp_y)
        cfp_box.addStretch(1)
        cfp_holder = QWidget()
        cfp_holder.setLayout(cfp_box)
        export_form.addRow("Continuous Focus Position", cfp_holder)

        self._include_ideas = QCheckBox("Include ideas in export")
        export_form.addRow(self._include_ideas)
        self._include_events = QCheckBox("Include events in export")
        export_form.addRow(self._include_events)
        self._include_decisions = QCheckBox("Include decisions in export")
        export_form.addRow(self._include_decisions)

        # ----- Autosave -----
        v.addWidget(section_header("Autosave"))
        autosave_form = QFormLayout()
        autosave_form.setSpacing(T.SPACE_SM)
        v.addLayout(autosave_form)
        self._autosave = NoScrollComboBox()
        for minutes, label in _AUTOSAVE_OPTIONS:
            self._autosave.addItem(label, minutes)
        current = self._app_settings.value("autosave_minutes", 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        idx = self._autosave.findData(current)
        self._autosave.setCurrentIndex(idx if idx >= 0 else 0)
        self._autosave.currentIndexChanged.connect(self._on_autosave_changed)
        autosave_form.addRow("Save every", self._autosave)
        v.addWidget(hint(
            "Automatically saves the open project to its .focusforge.json on the chosen "
            "interval — but only after it has been saved once (so it has a file). New, "
            "never-saved projects are left alone."))

        # ----- Updates -----
        v.addWidget(section_header("Updates"))
        upd_row = QHBoxLayout()
        upd_row.setSpacing(T.SPACE_SM)
        b_update = QPushButton("Check for Updates")
        b_update.clicked.connect(self.check_updates_requested.emit)
        upd_row.addWidget(b_update)
        upd_row.addStretch(1)
        v.addLayout(upd_row)
        v.addWidget(hint(
            f"You're running Focus Forge {version_label()}. New versions are "
            f"also checked for automatically at startup."))

        # ----- Starter Tree -----
        v.addWidget(section_header("Starter Tree"))
        action = QFrame()
        action.setFrameShape(QFrame.StyledPanel)
        a = QVBoxLayout(action)
        a.setContentsMargins(T.SPACE_MD, T.SPACE_MD, T.SPACE_MD, T.SPACE_MD)
        a.setSpacing(T.SPACE_SM)
        a.addWidget(hint("Generate a connected placeholder tree from the current country tag."))
        btn = QPushButton("Create Base Tree")
        btn.setObjectName("primary")
        btn.clicked.connect(self._on_create_base_tree)
        a.addWidget(btn)
        v.addWidget(action)

        # ----- In-game Icons -----
        v.addWidget(section_header("In-game Icons"))
        v.addWidget(hint(
            "Add your HOI4 install + mod folders to preview real focus icons on "
            "the canvas. Later entries override earlier ones (mod load order)."))
        self._icon_roots = QListWidget()
        self._icon_roots.setMaximumHeight(96)
        v.addWidget(self._icon_roots)
        icon_btns = QHBoxLayout()
        icon_btns.setSpacing(T.SPACE_SM)
        b_auto = QPushButton("Auto-detect")
        b_auto.clicked.connect(self._icons_autodetect)
        b_add = QPushButton("Add Folder…")
        b_add.clicked.connect(self._icons_add)
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(self._icons_remove)
        icon_btns.addWidget(b_auto)
        icon_btns.addWidget(b_add)
        icon_btns.addWidget(b_rm)
        icon_btns.addStretch(1)
        v.addLayout(icon_btns)
        self._icon_status = hint("")
        v.addWidget(self._icon_status)
        self._reload_icon_roots()

        # ----- Diagnostics -----
        v.addWidget(section_header("Diagnostics"))
        v.addWidget(hint(
            "Something misbehaving? Copy a diagnostic report — app and project "
            "facts plus the recent event log, ready to paste into Discord or a "
            "bug report. No file contents are included."))
        diag_btns = QHBoxLayout()
        diag_btns.setSpacing(T.SPACE_SM)
        b_diag = QPushButton("Copy Diagnostic Report")
        b_diag.clicked.connect(self._copy_diagnostics)
        b_logs = QPushButton("Open Log Folder")
        b_logs.clicked.connect(self._open_log_folder)
        diag_btns.addWidget(b_diag)
        diag_btns.addWidget(b_logs)
        diag_btns.addStretch(1)
        v.addLayout(diag_btns)

        v.addStretch(1)

        # Wire commits
        self._project_name.editingFinished.connect(lambda: self._commit("projectName", self._project_name.text()))
        self._tree_id.editingFinished.connect(lambda: self._commit("treeId", self._tree_id.text()))
        self._country_tag.tag_chosen.connect(lambda tag: self._commit("countryTag", tag))
        self._mod_prefix.editingFinished.connect(lambda: self._commit_export("modPrefix", self._mod_prefix.text()))
        self._focus_file.editingFinished.connect(lambda: self._commit_export("focusFileName", self._focus_file.text()))
        self._loc_prefix.editingFinished.connect(lambda: self._commit_export("localisationPrefix", self._loc_prefix.text()))
        self._cfp_x.valueChanged.connect(self._commit_cfp)
        self._cfp_y.valueChanged.connect(self._commit_cfp)
        self._include_ideas.toggled.connect(lambda v: self._commit_export("includeIdeas", v))
        self._include_events.toggled.connect(lambda v: self._commit_export("includeEvents", v))
        self._include_decisions.toggled.connect(lambda v: self._commit_export("includeDecisions", v))

        self._model.project_changed.connect(self.refresh)
        self.refresh()

    # ----- diagnostics -----
    def _copy_diagnostics(self) -> None:
        from PySide6.QtWidgets import QApplication

        from core.applog import build_report
        from .icon_provider import provider as icon_provider

        p = self._model.project
        issues = self._model.issues()
        errors = sum(1 for i in issues if i.severity == "error")
        info = {
            "app": version_label(),
            "project": f"{p.projectName or '(unnamed)'} [{p.countryTag}]",
            "path": str(self._model.path or "(unsaved)"),
            "content": (f"{len(p.focuses)} focuses, {len(p.ideas)} ideas, "
                        f"{len(p.events)} events, {len(p.decisions)} decisions"),
            "export dir": p.exportDir or "(not set)",
            "icon roots": "; ".join(icon_provider().roots()) or "(none)",
            "validation": f"{errors} errors, {len(issues) - errors} warnings",
            "unsaved changes": "yes" if self._model.is_dirty() else "no",
        }
        QApplication.clipboard().setText(build_report(info))
        self._model.status_message.emit("Diagnostic report copied to clipboard.")

    def _open_log_folder(self) -> None:
        import os

        from core.applog import LOG_DIR
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(LOG_DIR))  # noqa: S606 - local folder open
        except OSError as exc:
            QMessageBox.warning(self, "Open Log Folder",
                                f"Couldn't open the log folder:\n{exc}")

    def refresh(self) -> None:
        p = self._model.project
        self._suspend = True
        self._project_name.setText(p.projectName)
        self._country_tag.set_tag(p.countryTag)
        self._tree_id.setText(p.treeId)
        self._mod_prefix.setText(p.exportSettings.modPrefix)
        self._focus_file.setText(p.exportSettings.focusFileName)
        self._loc_prefix.setText(p.exportSettings.localisationPrefix)
        self._cfp_x.setValue(int(p.continuousFocusPosition.x))
        self._cfp_y.setValue(int(p.continuousFocusPosition.y))
        self._include_ideas.setChecked(p.exportSettings.includeIdeas)
        self._include_events.setChecked(p.exportSettings.includeEvents)
        self._include_decisions.setChecked(p.exportSettings.includeDecisions)
        self._suspend = False

    def _commit(self, attr: str, value) -> None:
        if self._suspend:
            return
        self._model.update_project_meta(**{attr: value})

    def _commit_export(self, attr: str, value) -> None:
        if self._suspend:
            return
        self._model.update_export_settings(**{attr: value})

    def _on_autosave_changed(self) -> None:
        minutes = int(self._autosave.currentData() or 0)
        self._app_settings.setValue("autosave_minutes", minutes)
        self.autosave_changed.emit(minutes)

    def _commit_cfp(self) -> None:
        if self._suspend:
            return
        from core.types import FocusPosition
        self._model.update_project_meta(
            continuousFocusPosition=FocusPosition(x=self._cfp_x.value(), y=self._cfp_y.value())
        )

    # ----- in-game icon roots -----
    def _reload_icon_roots(self) -> None:
        self._icon_roots.clear()
        self._icon_roots.addItems(provider().roots())
        self._update_icon_status()

    def _update_icon_status(self, force_index: bool = False) -> None:
        roots = provider().roots()
        if not roots:
            self._icon_status.setText("No folders configured — icons show as abbreviations.")
            return
        if not force_index and not provider().is_indexed():
            # Don't build the (large) index just to show a number — it loads
            # lazily on first canvas paint.
            self._icon_status.setText(f"{len(roots)} folder(s) configured — icons load on first use.")
            return
        n = provider().sprite_count()
        if n:
            self._icon_status.setText(f"{n:,} sprites indexed from {len(roots)} folder(s).")
        else:
            self._icon_status.setText("No sprites found — check the folders point at HOI4/mod roots.")

    def _commit_icon_roots(self) -> None:
        roots = [self._icon_roots.item(i).text() for i in range(self._icon_roots.count())]
        provider().set_roots(roots)
        self._update_icon_status(force_index=True)

    def _icons_autodetect(self) -> None:
        merged = list(provider().roots())
        for r in autodetect_roots():
            if r not in merged:
                merged.append(r)
        provider().set_roots(merged)
        self._icon_roots.clear()
        self._icon_roots.addItems(provider().roots())
        self._update_icon_status(force_index=True)

    def _icons_add(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add HOI4 / mod folder")
        if path:
            self._icon_roots.addItem(path)
            self._commit_icon_roots()

    def _icons_remove(self) -> None:
        for item in self._icon_roots.selectedItems():
            self._icon_roots.takeItem(self._icon_roots.row(item))
        self._commit_icon_roots()

    def _on_create_base_tree(self) -> None:
        if self._model.project.focuses:
            ans = QMessageBox.question(
                self,
                "Replace focuses?",
                "This replaces all existing focuses with a generated placeholder tree. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        apply_base_tree_to_project(self._model.project)
        if self._model.project.focuses:
            self._model.set_selection(self._model.project.focuses[0].id)
        self._model.notify_changed()
        self._model.status_message.emit(f"Created placeholder base tree for {self._model.project.countryTag}.")
