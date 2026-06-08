"""Main application window."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QWidget,
)

from core.base_tree import apply_base_tree_to_project
from core.focus_import import import_focus_tree
from core.mod_scaffold import (
    DEFAULT_SUPPORTED_VERSION,
    DEFAULT_TAGS,
    MD_DEPENDENCY,
    find_mod_root,
    scaffold_submod,
)
from core.types import FocusForgeProject
from core.version import version_label

from . import theme as T
from .country_editor import CountryEditorDialog
from .country_export import export_country_assets
from .export_panel import ExportPanel
from .help_panel import HelpPanel
from .icon_provider import provider
from .import_tree_dialog import ImportTreeDialog
from .new_submod_dialog import NewSubmodDialog
from .workspace import workspace_dir
from .focuses_list_panel import FocusesListPanel
from .graph_scene import GraphScene
from .graph_view import GraphView
from .agent_bridge import AgentBridge
from .inspector_panel import InspectorPanel
from .llm_panel import LlmPanel
from .project_model import ProjectModel
from .settings_panel import SettingsPanel
from .validation_panel import ValidationPanel
from .widgets import pill

PROJECT_FILTER = "Focus Forge Project (*.focusforge.json);;JSON (*.json);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Focus Forge")
        self.resize(1400, 900)
        self._model = ProjectModel(self)
        self._default_export_dir = None  # set when a submod is created/opened
        self._search_query = ""

        # Toolbar
        self._build_toolbar()

        # Central layout: focuses | graph | tabs
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self._focuses_panel = FocusesListPanel(self._model)
        self._focuses_panel.search_changed.connect(self._on_search)
        splitter.addWidget(self._focuses_panel)

        self._scene = GraphScene(self)
        self._view = GraphView(self._scene)
        splitter.addWidget(self._view)
        self._scene.node_clicked.connect(self._model.set_selection)
        self._scene.node_moved.connect(self._on_node_moved)
        self._scene.link_requested.connect(self._on_link_requested)
        self._scene.create_child_requested.connect(self._on_create_child)
        self._view.create_focus_requested.connect(self._on_create_focus_at)
        self._view.delete_focus_requested.connect(self._model.delete_focus)
        self._view.delete_focuses_requested.connect(self._on_delete_focuses)
        self._view.add_child_requested.connect(self._on_add_child)
        self._view.delete_link_requested.connect(self._on_delete_link)

        self._tabs = QTabWidget()
        self._tabs.setMinimumWidth(420)
        self._tabs.setMaximumWidth(520)
        self._inspector = InspectorPanel(self._model)
        self._validation = ValidationPanel(self._model)
        self._export_panel = ExportPanel(self._model)
        self._llm = LlmPanel(self._model)
        self._settings = SettingsPanel(self._model)
        self._help = HelpPanel()
        self._tabs.addTab(self._inspector, "Inspector")
        self._tabs.addTab(self._validation, "Validation")
        self._tabs.addTab(self._export_panel, "Export")
        self._tabs.addTab(self._llm, "LLM")
        self._tabs.addTab(self._settings, "Settings")
        self._tabs.addTab(self._help, "Help")
        splitter.addWidget(self._tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 800, 440])

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._version_label = QLabel(version_label())
        self._version_label.setObjectName("versionLabel")
        self._status_bar.addWidget(self._version_label)
        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(self._status_label, 1)
        self._pill_error = pill("0 errors", "error")
        self._pill_warn = pill("0 warnings", "warn")
        self._status_bar.addPermanentWidget(self._pill_error)
        self._status_bar.addPermanentWidget(self._pill_warn)
        self._bridge_pill = QLabel("AI Bridge: off")
        self._bridge_pill.setObjectName("bridgePill")
        self._bridge_pill.setAlignment(Qt.AlignCenter)
        self._status_bar.addPermanentWidget(self._bridge_pill)

        # In-process AI bridge (opt-in, loopback-only) that lets an MCP agent edit
        # the live project. Mutations run on this (main) thread → canvas repaints.
        self._settings = QSettings("FocusForge", "FocusForge")
        self._bridge = AgentBridge(self._model, scene=self._scene, parent=self)
        self._bridge.state_changed.connect(self._on_bridge_state)
        self._bridge.client_changed.connect(self._on_bridge_client)
        self._bridge.op_applied.connect(self._status_label.setText)

        # Wire signals
        self._model.project_changed.connect(self._on_project_changed)
        self._model.selection_changed.connect(self._on_selection_changed)
        self._model.validation_changed.connect(self._on_validation_changed)
        self._model.status_message.connect(self._status_label.setText)
        self._model.project_path_changed.connect(self._update_title)
        self._model.dirty_changed.connect(self._update_title)

        # In-game icon provider: seed roots on first run, repaint when they change.
        provider().changed.connect(self._on_icons_changed)
        provider().ensure_default_roots()

        # Initial render
        self._on_project_changed()
        self._on_selection_changed(self._model.selected_id)
        self._on_validation_changed(self._model.issues())
        self._update_title("")
        # Fit to content after the layout settles
        self._view.fit_to_content()

        # Restore the AI-bridge toggle (opt-in; persisted across sessions).
        if self._settings.value("ai_bridge_enabled", False, type=bool):
            self._bridge_action.setChecked(True)  # triggers _toggle_bridge → start

    # ----- toolbar -----
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        new_mod_act = QAction("New Submod", self)
        new_mod_act.triggered.connect(self._new_submod)
        tb.addAction(new_mod_act)

        import_act = QAction("Import Tree", self)
        import_act.triggered.connect(self._import_tree)
        tb.addAction(import_act)

        country_act = QAction("Country", self)
        country_act.triggered.connect(self._edit_country)
        tb.addAction(country_act)

        ideas_act = QAction("Ideas", self)
        ideas_act.triggered.connect(self._manage_ideas)
        tb.addAction(ideas_act)

        events_act = QAction("Events", self)
        events_act.triggered.connect(self._manage_events)
        tb.addAction(events_act)
        tb.addSeparator()

        open_act = QAction("Open", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._open)
        tb.addAction(open_act)

        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence.Save)
        save_act.triggered.connect(self._save)
        tb.addAction(save_act)

        save_as_act = QAction("Save As", self)
        save_as_act.triggered.connect(self._save_as)
        tb.addAction(save_as_act)

        tb.addSeparator()

        add_act = QAction("+ Focus", self)
        add_act.triggered.connect(self._on_add_focus)
        tb.addAction(add_act)

        del_act = QAction("Delete", self)
        del_act.triggered.connect(self._on_delete_focus)
        tb.addAction(del_act)
        self._delete_action = del_act

        fit_act = QAction("Fit View", self)
        fit_act.triggered.connect(lambda: self._view.fit_to_content())
        tb.addAction(fit_act)

        tb.addSeparator()

        export_act = QAction("Export to Mod", self)
        export_act.triggered.connect(self._export_to_mod)
        tb.addAction(export_act)
        export_btn = tb.widgetForAction(export_act)
        if export_btn is not None:
            export_btn.setObjectName("primary")

        export_as_act = QAction("Export As…", self)
        export_as_act.triggered.connect(self._export_as)
        tb.addAction(export_as_act)

        tb.addSeparator()
        self._bridge_action = QAction("AI Bridge", self)
        self._bridge_action.setCheckable(True)
        self._bridge_action.setToolTip(
            "Let a local AI agent (via MCP) edit this project live. Loopback-only; "
            "off by default.")
        self._bridge_action.toggled.connect(self._toggle_bridge)
        tb.addAction(self._bridge_action)

    # ----- handlers -----
    def _open(self) -> None:
        if self._model.path:
            start = str(Path(self._model.path).parent)
        else:
            ws = workspace_dir()
            ws.mkdir(parents=True, exist_ok=True)
            start = str(ws)
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", start, filter=PROJECT_FILTER)
        if not path:
            return
        try:
            self._model.load_from_file(Path(path))
            self._view.fit_to_content()
            self._default_export_dir = self._resolve_mod_dir() or ""
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", str(exc))

    def _save(self) -> bool:
        """Save to the current path (or prompt). Returns True if saved."""
        if self._model.path:
            try:
                self._model.save_to_file(self._model.path)
                return True
            except Exception as exc:
                QMessageBox.warning(self, "Save failed", str(exc))
                return False
        return self._save_as()

    def _save_as(self) -> bool:
        if self._model.path:
            start = str(self._model.path)
        else:
            ws = workspace_dir()
            ws.mkdir(parents=True, exist_ok=True)
            name = self._model.project.countryTag.lower() or "project"
            start = str(ws / f"{name}.focusforge.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", start, filter=PROJECT_FILTER)
        if not path:
            return False
        if not path.endswith((".json", ".focusforge.json")):
            path += ".focusforge.json"
        try:
            self._model.save_to_file(Path(path))
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return False

    def _new_submod(self) -> None:
        dlg = NewSubmodDialog(self)
        if not dlg.exec():
            return
        vals = dlg.values()
        if not vals["folder"] or not vals["mod_root"]:
            QMessageBox.warning(self, "New Submod", "A name and location are required.")
            return

        # The editable project lives in the Focus Forge workspace; the HOI4 mod
        # folder is only materialised on first "Export to Mod".
        mod_target = os.path.join(vals["mod_root"], vals["folder"])
        proj_dir = workspace_dir() / vals["folder"]
        proj_path = proj_dir / f"{vals['folder']}.focusforge.json"
        if proj_path.exists():
            QMessageBox.warning(self, "New Submod",
                                f"A project already exists at:\n{proj_path}")
            return
        try:
            proj_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(self, "New Submod", f"Could not create project folder:\n{exc}")
            return

        project = None
        if vals.get("import_tree"):
            project = self._choose_and_import_tree()
        if project is None:
            project = FocusForgeProject(countryTag=vals["country_tag"])
            apply_base_tree_to_project(project)  # placeholder tree + tag prefixes
            project.projectName = vals["name"]   # restore the real mod name
        # Remember where to publish and how to scaffold it on first export.
        project.exportDir = mod_target
        project.modMeta = {
            "name": vals["name"],
            "tags": vals["tags"],
            "dependencies": vals["dependencies"],
            "supported_version": vals["supported_version"],
        }

        self._model.replace_project(project, path=proj_path)
        self._model.save_to_file(proj_path)
        self._view.fit_to_content()
        self._default_export_dir = mod_target

        if vals["add_icons"]:
            roots = provider().roots()
            if mod_target not in roots:
                provider().set_roots(roots + [mod_target])

        QMessageBox.information(
            self, "Submod created",
            f"Project created in your Focus Forge workspace:\n{proj_dir}\n\n"
            f"When you're ready, \"Export to Mod\" will build it into the HOI4 "
            f"folder and make it appear in the launcher:\n{mod_target}")
        self._model.status_message.emit(f"Created submod project at {proj_dir}")

    def _choose_and_import_tree(self):
        """Open the import picker and return a FocusForgeProject, or None."""
        roots = provider().roots()
        dlg = ImportTreeDialog(roots, self)
        if not dlg.exec() or not dlg.selected_ref():
            return None
        ref = dlg.selected_ref()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return import_focus_tree(ref, roots)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed",
                                f"Could not import '{ref.tree_id}':\n{exc}")
            return None
        finally:
            QGuiApplication.restoreOverrideCursor()

    def _edit_country(self) -> None:
        dlg = CountryEditorDialog(self._model, self)
        dlg.exec()

    def _manage_ideas(self) -> None:
        from .ideas_dialog import IdeasManagerDialog
        IdeasManagerDialog(self._model, self).exec()

    def _manage_events(self) -> None:
        from .events_dialog import EventsManagerDialog
        EventsManagerDialog(self._model, self).exec()

    # ----- AI bridge -----
    def _toggle_bridge(self, on: bool) -> None:
        if on and not self._bridge.start():
            self._bridge_action.setChecked(False)
            QMessageBox.warning(self, "AI Bridge",
                                "Couldn't start the AI bridge (loopback port unavailable).")
            return
        if not on:
            self._bridge.stop()
        self._settings.setValue("ai_bridge_enabled", on)

    def _on_bridge_state(self, listening: bool, port: int) -> None:
        if listening:
            self._set_bridge_pill(f"AI Bridge: on :{port}", active=True)
            self._status_label.setText(f"AI Bridge listening on 127.0.0.1:{port}")
        else:
            self._set_bridge_pill("AI Bridge: off", active=False)

    def _on_bridge_client(self, connected: bool) -> None:
        if not self._bridge.is_listening():
            return
        if connected:
            self._set_bridge_pill("AI Bridge: agent connected", active=True)
        else:
            self._set_bridge_pill(f"AI Bridge: on :{self._bridge.port()}", active=True)

    def _set_bridge_pill(self, text: str, *, active: bool) -> None:
        self._bridge_pill.setText(text)
        self._bridge_pill.setProperty("active", "true" if active else "false")
        self._bridge_pill.style().unpolish(self._bridge_pill)
        self._bridge_pill.style().polish(self._bridge_pill)

    def _import_tree(self) -> None:
        project = self._choose_and_import_tree()
        if project is None:
            return
        self._model.replace_project(project, path=None)
        self._view.fit_to_content()
        self._model.status_message.emit(
            f"Imported {len(project.focuses)} focuses from {project.treeId} — "
            f"Save to keep, or Export into a mod.")

    def _resolve_mod_dir(self):
        """The HOI4 mod folder to build into: the project's remembered exportDir,
        else (legacy projects living in a mod) the ancestor descriptor.mod, else
        this session's default."""
        ed = (self._model.project.exportDir or "").strip()
        if ed:
            return ed
        if self._model.path:
            root = find_mod_root(self._model.path)
            if root:
                return root
        return self._default_export_dir

    def _ensure_mod_scaffolded(self, target: str) -> bool:
        """Materialise the HOI4 mod folder (descriptor + skeleton) if it doesn't
        exist yet, using the project's stored modMeta (falling back to defaults)."""
        if os.path.isfile(os.path.join(target, "descriptor.mod")):
            return True
        meta = self._model.project.modMeta or {}
        name = meta.get("name") or self._model.project.projectName or os.path.basename(target)
        tags = meta.get("tags") or list(DEFAULT_TAGS)
        deps = meta.get("dependencies")
        if deps is None:
            deps = [MD_DEPENDENCY]
        sv = meta.get("supported_version") or DEFAULT_SUPPORTED_VERSION
        try:
            scaffold_submod(os.path.dirname(target), os.path.basename(target), name,
                            tags=tags, dependencies=deps, supported_version=sv)
        except Exception as exc:
            QMessageBox.warning(self, "Export to Mod",
                                f"Could not create the mod folder:\n{exc}")
            return False
        roots = provider().roots()
        if target not in roots:
            provider().set_roots(roots + [target])
        self._model.status_message.emit(f"Created mod folder {target}")
        return True

    def _export_to_mod(self) -> None:
        target = self._resolve_mod_dir()
        if not target:
            QMessageBox.information(
                self, "Export to Mod",
                "I don't know which mod to build into yet. Create it with "
                "\"New Submod\", or use Export As… to pick a destination.")
            self._export_as()
            return
        if not self._ensure_mod_scaffolded(target):
            return
        self._default_export_dir = target
        if self._do_export(Path(target)):
            self._model.status_message.emit(f"Exported to mod: {target}")

    def _export_as(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose Export Directory", self._default_export_dir or "")
        if not directory:
            return
        self._default_export_dir = directory
        self._do_export(Path(directory))

    def _do_export(self, directory: Path) -> bool:
        from core.validation import get_blocking_issues
        blocking = get_blocking_issues(self._model.project)
        if blocking:
            shown = "\n".join(f"  • {i.message}" for i in blocking[:8])
            more = f"\n  …and {len(blocking) - 8} more" if len(blocking) > 8 else ""
            n = len(blocking)
            ans = QMessageBox.question(
                self,
                "Validation errors",
                f"This project has {n} error{'s' if n != 1 else ''} that may produce a "
                f"broken mod:\n\n{shown}{more}\n\nExport anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return False
        try:
            self._model.export_to_directory(directory)
            # Binary country assets (flag TGAs / custom portrait DDS) aren't text.
            if self._model.project.exportSettings.includeCountry and self._model.project.country:
                export_country_assets(self._model.project, str(directory))
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return False

    def _on_add_focus(self) -> None:
        new_id = self._model.add_focus()
        self._scene.reconcile(self._model.project, new_id)
        self._view.centerOn(self._scene._nodes[new_id])

    def _on_delete_focus(self) -> None:
        sel = self._model.selected_id
        if not sel:
            return
        self._model.delete_focus(sel)

    def _on_delete_focuses(self, ids) -> None:
        ids = list(ids or [])
        if not ids:
            return
        self._model.delete_focuses(ids)
        self._model.status_message.emit(
            f"Deleted {len(ids)} focus{'es' if len(ids) != 1 else ''}")

    def _on_node_moved(self, focus_id: str, gx: int, gy: int) -> None:
        from core.types import FocusPosition
        self._model.update_focus(focus_id, position=FocusPosition(x=gx, y=gy))

    def _on_link_requested(self, source_id: str, target_id: str) -> None:
        msg = self._model.add_prerequisite(target_id, source_id)
        if msg:
            self._model.status_message.emit(msg)

    def _create_focus_at_scene(self, scene_pos, prerequisites=None) -> str:
        """Snap a scene position to the focus grid (node centred on the point)
        and create a new focus there."""
        from ui.focus_node_item import GRID_X, GRID_Y, NODE_H, NODE_W
        gx = round((scene_pos.x() - NODE_W / 2) / GRID_X)
        gy = round((scene_pos.y() - NODE_H / 2) / GRID_Y)
        return self._model.add_focus_at(gx, gy, prerequisites=prerequisites)

    def _on_create_child(self, source_id: str, drop_pos) -> None:
        new_id = self._create_focus_at_scene(drop_pos, prerequisites=[source_id])
        self._model.status_message.emit(f"Created {new_id} linked from {source_id}")

    def _on_create_focus_at(self, scene_pos) -> None:
        new_id = self._create_focus_at_scene(scene_pos)
        self._model.status_message.emit(f"Created {new_id}")

    def _on_add_child(self, parent_id: str) -> None:
        parent = self._model.find_focus(parent_id)
        if not parent:
            return
        gx, gy = self._free_cell_below(parent)
        new_id = self._model.add_focus_at(gx, gy, prerequisites=[parent_id])
        self._model.status_message.emit(f"Created {new_id} under {parent_id}")

    def _free_cell_below(self, parent) -> tuple:
        """A free grid cell on the row below the parent, nearest its column."""
        occupied = {(int(f.position.x), int(f.position.y)) for f in self._model.project.focuses}
        px, py = int(parent.position.x), int(parent.position.y) + 1
        if (px, py) not in occupied:
            return (px, py)
        for d in range(1, 16):
            for cx in (px - d, px + d):
                if (cx, py) not in occupied:
                    return (cx, py)
        return (px, py)

    def _on_delete_link(self, source_id: str, target_id: str, kind: str) -> None:
        if kind == "mutex":
            msg = self._model.remove_mutex(source_id, target_id)
        else:
            msg = self._model.remove_prerequisite(target_id, source_id)
        if msg:
            self._model.status_message.emit(msg)

    def _on_project_changed(self) -> None:
        self._scene.reconcile(self._model.project, self._model.selected_id)
        self._delete_action.setEnabled(bool(self._model.selected_id))
        self._apply_search_highlight()  # re-apply after nodes are rebuilt

    def _on_search(self, query: str) -> None:
        self._search_query = (query or "").strip()
        self._apply_search_highlight()

    def _apply_search_highlight(self) -> None:
        q = self._search_query.lower()
        if not q:
            self._scene.set_search_matches(None)
            return
        ids = {f.id for f in self._model.project.focuses
               if q in f.id.lower() or q in (f.title or "").lower()
               or q in (f.description or "").lower()}
        self._scene.set_search_matches(ids)
        self._model.status_message.emit(f"{len(ids)} focus match(es) for “{self._search_query}”")

    def _on_selection_changed(self, focus_id: str) -> None:
        self._scene.select_node(focus_id)
        self._delete_action.setEnabled(bool(focus_id))

    def _on_icons_changed(self) -> None:
        self._scene.update()

    def _on_validation_changed(self, issues: list) -> None:
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        self._pill_error.setText(f"{errors} error{'s' if errors != 1 else ''}")
        self._pill_error.setObjectName("pillError" if errors else "pillNeutral")
        self._pill_warn.setText(f"{warnings} warning{'s' if warnings != 1 else ''}")
        self._pill_warn.setObjectName("pillWarn" if warnings else "pillNeutral")
        # Re-polish so the object-name-driven QSS reapplies.
        for w in (self._pill_error, self._pill_warn):
            w.style().unpolish(w)
            w.style().polish(w)

    def _update_title(self, *_args) -> None:
        path = str(self._model.path) if self._model.path else ""
        star = "*" if self._model.is_dirty() else ""
        suffix = f" — {path}" if path else " — (unsaved project)"
        self.setWindowTitle(f"Focus Forge{star}{suffix}")

    def closeEvent(self, event) -> None:
        if not self._model.is_dirty():
            self._finish_close(event)
            return
        resp = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Save them before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if resp == QMessageBox.Save:
            self._finish_close(event) if self._save() else event.ignore()
        elif resp == QMessageBox.Discard:
            self._finish_close(event)
        else:
            event.ignore()

    def _finish_close(self, event) -> None:
        self._bridge.stop()  # release the port + remove the discovery file
        event.accept()
