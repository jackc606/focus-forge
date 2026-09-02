"""Main application window."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.base_tree import apply_base_tree_to_project
from core.md_edition import edition as md_edition, set_active_edition
from core.reward_script import structure_all_rewards
from core.focus_import import find_focus_trees, import_focus_tree
from core.mod_scaffold import (
    DEFAULT_TAGS,
    default_mod_root,
    find_mod_root,
    is_hoi4_mod_root,
    read_descriptor_name,
    retarget_descriptor,
    sanitize_folder,
    scaffold_submod,
)
from core.types import FocusForgeProject
from core.sample_project import make_blank_project, make_sample_project
from core.version import __version__, version_label

from . import theme as T
from .country_editor import CountryEditorDialog
from .country_tags_live import install_country_tag_hooks
from .country_export import (
    export_country_assets,
    export_decision_assets,
    export_event_assets,
    export_focus_icon_assets,
)
from .export_panel import ExportPanel
from .help_panel import HelpPanel
from .icon_provider import provider
from .import_tree_dialog import ImportTreeDialog
from .new_submod_dialog import NewSubmodDialog
from .workspace import workspace_dir
from .focuses_list_panel import FocusesListPanel
from .focus_node_item import FocusNodeItem
from .graph_scene import GraphScene
from .graph_view import GraphView
from .stats_panel import StatsPanel
from .agent_bridge import AgentBridge
from .inspector_panel import InspectorPanel
from .llm_panel import LlmPanel
from .project_model import ProjectModel
from .settings_panel import SettingsPanel
from .update_worker import UpdateCheckWorker, run_in_thread
from .validation_panel import ValidationPanel
from .widgets import ClickableLabel, pill

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
        self._view.add_shortcut_requested.connect(self._on_add_shortcut)
        self._view.delete_link_requested.connect(self._on_delete_link)
        self._view.group_prereq_requested.connect(self._on_group_prereq)
        self._view.ungroup_prereq_requested.connect(self._on_ungroup_prereq)
        self._view.paste_requested.connect(self._paste_at_scene)

        # Canvas-only clipboard shortcuts (widget context: they never steal
        # Ctrl+C/V from text fields elsewhere in the app).
        for seq, handler in ((QKeySequence.Copy, self._copy_selection),
                             (QKeySequence.Paste, self._paste_clipboard),
                             (QKeySequence("Ctrl+D"), self._duplicate_selection)):
            sc = QShortcut(seq, self._view, activated=handler)
            sc.setContext(Qt.WidgetWithChildrenShortcut)

        self._tabs = QTabWidget()
        self._tabs.setMinimumWidth(420)
        self._tabs.setMaximumWidth(520)
        self._inspector = InspectorPanel(self._model)
        self._validation = ValidationPanel(self._model)
        self._stats_panel = StatsPanel(self._model)
        self._export_panel = ExportPanel(self._model)
        self._llm = LlmPanel(self._model)
        self._settings_panel = SettingsPanel(self._model)
        self._help = HelpPanel()
        self._tabs.addTab(self._inspector, "Inspector")
        self._tabs.addTab(self._validation, "Validation")
        self._tabs.addTab(self._stats_panel, "Stats")
        self._tabs.addTab(self._export_panel, "Export")
        self._tabs.addTab(self._llm, "LLM")
        self._tabs.addTab(self._settings_panel, "Settings")
        self._tabs.addTab(self._help, "Help")
        splitter.addWidget(self._tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        # The inspector column must never silently collapse to zero width — a
        # squeezed first layout (small launch window) used to leave it invisible
        # until the user found the splitter handle by accident.
        splitter.setCollapsible(2, False)
        splitter.setSizes([280, 800, 440])

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._version_label = ClickableLabel(version_label())
        self._version_label.setObjectName("versionLabel")
        self._version_label.setToolTip("What's new — click to open the dev log")
        self._version_label.clicked.connect(self._show_devlog)
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
        # Unobtrusive "update available" notice — hidden until a check finds
        # one; clicking reopens the update dialog (covers skip / dismissal).
        self._update_pill = ClickableLabel("")
        self._update_pill.setObjectName("updatePill")
        self._update_pill.setAlignment(Qt.AlignCenter)
        self._update_pill.setToolTip("A new version is available — click for details")
        self._update_pill.clicked.connect(self._open_update_dialog)
        self._update_pill.hide()
        self._status_bar.addPermanentWidget(self._update_pill)

        # In-process AI bridge (opt-in, loopback-only) that lets an MCP agent edit
        # the live project. Mutations run on this (main) thread → canvas repaints.
        self._settings = QSettings("FocusForge", "FocusForge")
        self._bridge = AgentBridge(self._model, scene=self._scene, parent=self)
        self._bridge.state_changed.connect(self._on_bridge_state)
        self._bridge.client_changed.connect(self._on_bridge_client)
        self._bridge.op_applied.connect(self._status_label.setText)

        # Autosave: a timer that writes the open project on the configured interval.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._settings_panel.autosave_changed.connect(self._apply_autosave)
        self._apply_autosave(self._settings.value("autosave_minutes", 0))

        # Auto-update: a silent check shortly after startup, plus a manual
        # "Check for Updates" button in the Settings tab.
        self._update_worker = None
        self._update_thread = None
        self._update_info = None
        self._update_check_manual = False
        self._settings_panel.check_updates_requested.connect(
            lambda: self._check_for_updates(manual=True))
        QTimer.singleShot(3000, self._check_for_updates)

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
        # Country-tag lists follow the configured roots (MD main vs beta differ);
        # also lets the AI bridge serve live tags before any picker exists.
        install_country_tag_hooks()
        # Warm the sprite index and the game-data providers (tech, states,
        # traits, MD politics) off-thread so the first canvas paint and the
        # first dropdown open don't scan the game files on the UI thread.
        provider().warm_index_async()
        from .provider_warmup import warm_game_data_async
        warm_game_data_async(self._model.project.countryTag)

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
        """The command bar: labeled banks of buttons (PROJECT / CONTENT /
        CANVAS) with one green Export CTA on the right, instead of 18 flat
        actions in a row. Rare and destructive commands live behind "…" so the
        bar fits any sane window width."""
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(T.SPACE_XS, 2, T.SPACE_XS, 0)
        row.setSpacing(T.SPACE_MD)

        def act(text, slot, tooltip="", shortcut=None):
            a = QAction(text, self)
            if tooltip:
                a.setToolTip(tooltip)
            if shortcut:
                a.setShortcut(shortcut)
                # The action must belong to a widget for its shortcut to fire —
                # QToolButton.setDefaultAction alone doesn't register it.
                self.addAction(a)
            a.triggered.connect(slot)
            return a

        def btn(action, object_name=""):
            b = QToolButton()
            b.setDefaultAction(action)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setFocusPolicy(Qt.NoFocus)
            if object_name:
                b.setObjectName(object_name)
            return b

        def bank(caption, widgets):
            holder = QWidget()
            v = QVBoxLayout(holder)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(1)
            h = QHBoxLayout()
            h.setSpacing(T.SPACE_XS)
            for w in widgets:
                h.addWidget(w)
            v.addLayout(h)
            cap = QLabel(caption)
            cap.setObjectName("bankLabel")
            cap.setAlignment(Qt.AlignHCenter)
            v.addWidget(cap)
            row.addWidget(holder)

        def bank_divider():
            line = QFrame()
            line.setObjectName("bankDivider")
            line.setFrameShape(QFrame.VLine)
            line.setFixedWidth(1)
            row.addWidget(line)

        # PROJECT
        new_mod_act = act("New Submod", self._new_submod)
        open_act = act("Open", self._open, shortcut=QKeySequence.Open)
        save_act = act("Save", self._save, shortcut=QKeySequence.Save)
        bank("PROJECT", [btn(new_mod_act), btn(open_act), btn(save_act)])
        bank_divider()

        # CONTENT — the non-focus-tree parts of the mod.
        country_act = act("Country", self._edit_country)
        ideas_act = act("Ideas", self._manage_ideas)
        events_act = act("Events", self._manage_events)
        decisions_act = act("Decisions", self._manage_decisions)
        bank("CONTENT", [btn(country_act), btn(ideas_act),
                         btn(events_act), btn(decisions_act)])
        bank_divider()

        # CANVAS — buttons always operate on the PROJECT (clicking one doesn't
        # move keyboard focus, so a focused text field must not hijack them);
        # the QShortcuts below keep the text-field guard.
        undo_act = act("Undo", self._undo_project, tooltip="Undo the last change (Ctrl+Z)")
        redo_act = act("Redo", self._redo_project, tooltip="Redo (Ctrl+Y)")
        add_act = act("+ Focus", self._on_add_focus)
        del_act = act("Delete", self._on_delete_focus)
        self._delete_action = del_act
        fit_act = act("Fit View", lambda: self._view.fit_to_content())
        bank("CANVAS", [btn(undo_act), btn(redo_act), btn(add_act),
                        btn(del_act), btn(fit_act)])

        QShortcut(QKeySequence.Undo, self, activated=self._undo)
        QShortcut(QKeySequence.Redo, self, activated=self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self._redo)

        row.addStretch(1)

        # MORE — rare, secondary, and destructive commands.
        import_act = act("Import Tree…", self._import_tree)
        save_as_act = act("Save As…", self._save_as)
        export_as_act = act("Export As…", self._export_as)
        shortcuts_act = act("Shortcuts…", self._manage_shortcuts)
        structure_act = act(
            "Structure Raw Scripts…", self._structure_all_rewards,
            tooltip="Convert every focus's raw reward AND availability script "
                    "into editable cards, where fully recognized. One undo "
                    "restores everything.")
        self._bridge_action = QAction("AI Bridge", self)
        self._bridge_action.setCheckable(True)
        self._bridge_action.setToolTip(
            "Let a local AI agent (via MCP) edit this project live. Loopback-only; "
            "off by default.")
        self._bridge_action.toggled.connect(self._toggle_bridge)
        clear_act = act("Clear Focuses", self._on_clear_focuses,
                        tooltip="Remove every focus from this project (asks first).")
        scan_log_act = act("Scan HOI4 error.log", self._scan_error_log,
                           tooltip="After launching the game with this mod: show the error.log "
                                   "lines about it, mapped back to your focuses.")
        more_menu = QMenu(self)
        for a in (import_act, save_as_act, export_as_act, structure_act,
                  shortcuts_act):
            more_menu.addAction(a)
        more_menu.addSeparator()
        more_menu.addAction(scan_log_act)
        more_menu.addSeparator()
        more_menu.addAction(self._bridge_action)
        more_menu.addSeparator()
        more_menu.addAction(clear_act)
        more_btn = QToolButton()
        more_btn.setText("…")
        more_btn.setToolTip("Import, Save As, Export As, Shortcuts, AI Bridge, Clear")
        more_btn.setMenu(more_menu)
        more_btn.setPopupMode(QToolButton.InstantPopup)
        more_btn.setFocusPolicy(Qt.NoFocus)
        bank("MORE", [more_btn])
        bank_divider()

        # EXPORT — the one green CTA.
        export_act = act("Export to Mod", self._export_to_mod)
        bank("EXPORT", [btn(export_act, "primary")])

        tb.addWidget(bar)

    # ----- pending-edit flush + unsaved-changes guard -----
    @staticmethod
    def _flush_focused_editor() -> None:
        """Commit any in-progress edit in the focused text/spin editor. Those
        widgets write to the model on editingFinished, which only fires when
        they lose focus — so Save/Export/autosave must flush them first or the
        snapshot misses the value still sitting in the widget. Focus is given
        back afterwards so an autosave mid-typing doesn't steal the caret."""
        w = QApplication.focusWidget()
        if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            w.clearFocus()  # fires editingFinished synchronously → model commit
            w.setFocus()

    def _confirm_discard_changes(self) -> bool:
        """Guard for every action that replaces or closes the current project
        (open / import / new submod / sample / close). Returns True when it is
        safe to proceed: no unsaved changes, or the user chose Discard, or
        chose Save and the save succeeded. Cancel (including a cancelled
        Save-As) returns False and the caller must abort the action."""
        self._flush_focused_editor()  # a pending field edit is unsaved work too
        if not self._model.is_dirty():
            return True
        resp = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if resp == QMessageBox.Save:
            return self._save()
        return resp == QMessageBox.Discard

    # ----- undo / redo / clipboard -----
    @staticmethod
    def _focused_text_widget(for_redo: bool = False):
        """The focused text widget IF it should consume the undo/redo keystroke:
        editable, with steps left in its own history. Read-only previews and
        exhausted fields fall through to project undo."""
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit):
            if not w.isReadOnly() and (w.isRedoAvailable() if for_redo else w.isUndoAvailable()):
                return w
        elif isinstance(w, (QPlainTextEdit, QTextEdit)):
            doc = w.document()
            if not w.isReadOnly() and (doc.isRedoAvailable() if for_redo else doc.isUndoAvailable()):
                return w
        return None

    def _undo(self) -> None:
        # A focused text field keeps its own character-level undo.
        w = self._focused_text_widget()
        if w is not None:
            w.undo()
            return
        self._undo_project()

    def _redo(self) -> None:
        w = self._focused_text_widget(for_redo=True)
        if w is not None:
            w.redo()
            return
        self._redo_project()

    def _undo_project(self) -> None:
        self._model.status_message.emit(
            "Undid last change." if self._model.undo() else "Nothing to undo.")

    def _redo_project(self) -> None:
        self._model.status_message.emit(
            "Redid change." if self._model.redo() else "Nothing to redo.")

    def _selected_focus_ids(self) -> list:
        return [it.focus_id for it in self._scene.selectedItems()
                if isinstance(it, FocusNodeItem)]

    def _copy_selection(self) -> None:
        ids = self._selected_focus_ids()
        if not ids:
            self._model.status_message.emit("Nothing selected to copy.")
            return
        payload = self._model.copy_payload(ids)
        QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False))
        self._model.status_message.emit(
            f"Copied {len(ids)} focus{'es' if len(ids) != 1 else ''}.")

    def _paste_clipboard(self) -> None:
        # Ctrl+V → paste under the cursor (or the visible centre if it's off-view).
        self._paste_at_scene(self._view.paste_anchor_scene())

    def _paste_at_scene(self, scene_pos) -> None:
        try:
            payload = json.loads(QApplication.clipboard().text() or "")
        except ValueError:
            payload = None
        if not (isinstance(payload, dict) and payload.get("focuses")):
            self._model.status_message.emit("Clipboard has no copied focuses.")
            return
        at = self._view.scene_to_grid(scene_pos) if scene_pos is not None else None
        new_ids = self._model.paste_focuses(payload, at=at)
        self._model.status_message.emit(
            f"Pasted {len(new_ids)} focus{'es' if len(new_ids) != 1 else ''}.")

    def _duplicate_selection(self) -> None:
        ids = self._selected_focus_ids()
        if not ids:
            self._model.status_message.emit("Nothing selected to duplicate.")
            return
        new_ids = self._model.duplicate_focuses(ids)
        self._model.status_message.emit(
            f"Duplicated {len(new_ids)} focus{'es' if len(new_ids) != 1 else ''}.")

    # ----- handlers -----
    def _open(self) -> None:
        if not self._confirm_discard_changes():
            return
        if self._model.path:
            start = str(Path(self._model.path).parent)
        else:
            ws = workspace_dir()
            ws.mkdir(parents=True, exist_ok=True)
            start = str(ws)
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", start, filter=PROJECT_FILTER)
        if not path:
            return
        self._open_path(Path(path))

    def _open_path(self, path: Path) -> None:
        try:
            self._model.load_from_file(path)
            self._view.fit_to_content()
            self._default_export_dir = self._resolve_mod_dir() or ""
            self._push_recent(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", str(exc))

    # ----- startup launcher + recent projects -----
    _RECENT_MAX = 8

    def _recent_projects(self) -> list:
        """Recently opened/saved project paths that still exist (most recent first)."""
        raw = self._settings.value("recent_projects", []) or []
        if isinstance(raw, str):
            raw = [raw]
        out = []
        for p in raw:
            try:
                if p and Path(p).is_file():
                    out.append(str(p))
            except OSError:
                continue
        return out

    def _push_recent(self, path) -> None:
        p = str(path)
        keep = [x for x in self._recent_projects()
                if os.path.normpath(x) != os.path.normpath(p)]
        keep.insert(0, p)
        self._settings.setValue("recent_projects", keep[: self._RECENT_MAX])

    def load_blank(self) -> None:
        """Show an empty project (used behind the startup launcher)."""
        self._model.replace_project(make_blank_project(), path=None)
        self._default_export_dir = None

    def _load_sample(self) -> None:
        if not self._confirm_discard_changes():
            return
        self._model.replace_project(make_sample_project(), path=None)
        self._view.fit_to_content()

    def show_welcome(self) -> None:
        """Open the startup launcher and route to the chosen action. The blank
        project stays if the user closes it without choosing."""
        from .welcome_dialog import WelcomeDialog
        dlg = WelcomeDialog(recent=self._recent_projects(), parent=self)
        dlg.exec()
        if dlg.choice == "new":
            self._new_submod()
        elif dlg.choice == "open":
            self._open()
        elif dlg.choice == "sample":
            self._load_sample()
        elif dlg.choice == "recent" and dlg.recent_path:
            if self._confirm_discard_changes():
                self._open_path(Path(dlg.recent_path))

    # ----- autosave -----
    def _apply_autosave(self, minutes) -> None:
        """(Re)configure the autosave timer; 0 minutes turns it off."""
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 0
        self._autosave_timer.stop()
        if minutes > 0:
            self._autosave_timer.setInterval(minutes * 60_000)
            self._autosave_timer.start()

    def _autosave_tick(self) -> None:
        self._flush_focused_editor()
        # Only autosave a project that already has a file and unsaved changes.
        if not self._model.path or not self._model.is_dirty():
            return
        try:
            self._model.save_to_file(self._model.path)
            self._push_recent(self._model.path)
            self._status_label.setText("Autosaved.")
        except Exception as exc:
            self._status_label.setText(f"Autosave failed: {exc}")

    def _save(self) -> bool:
        """Save to the current path (or prompt). Returns True if saved."""
        self._flush_focused_editor()
        if self._model.path:
            try:
                self._model.save_to_file(self._model.path)
                self._push_recent(self._model.path)
                return True
            except Exception as exc:
                QMessageBox.warning(self, "Save failed", str(exc))
                return False
        return self._save_as()

    def _save_as(self) -> bool:
        self._flush_focused_editor()
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
            self._push_recent(Path(path))
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return False

    def _new_submod(self) -> None:
        if not self._confirm_discard_changes():
            return
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

        # By default, seed the new submod with the country's existing MD focus tree
        # so the player can build on what's already there; "Start blank" opts out.
        project = None
        imported = False
        # Read game data from the edition this submod targets, so the imported
        # tree (and every dropdown afterwards) comes from the right MD.
        self._apply_md_edition_to_roots(vals.get("md_edition") or "main")
        if not vals.get("start_blank"):
            project = self._import_md_tree_for_tag(vals["country_tag"])
            imported = project is not None
        if project is None:
            project = FocusForgeProject(countryTag=vals["country_tag"])
            apply_base_tree_to_project(project, roots=provider().roots())  # placeholder tree + tag prefixes
        project.projectName = vals["name"]       # the real mod name
        project.countryTag = vals["country_tag"]
        project.mdEdition = vals.get("md_edition") or "main"
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
        self._push_recent(proj_path)
        self._view.fit_to_content()
        self._default_export_dir = mod_target

        if vals["add_icons"]:
            roots = provider().roots()
            if mod_target not in roots:
                provider().set_roots(roots + [mod_target])

        if imported:
            tree_note = (f"Imported {vals['country_tag']}'s Millennium Dawn focus tree "
                         f"({len(project.focuses)} focuses) — edit freely.")
        elif not vals.get("start_blank"):
            tree_note = (f"No dedicated Millennium Dawn tree was found for "
                         f"{vals['country_tag']}, so the project starts from a blank "
                         f"placeholder tree.")
        else:
            tree_note = "Started from a blank placeholder tree."
        QMessageBox.information(
            self, "Submod created",
            f"Project created in your Focus Forge workspace:\n{proj_dir}\n\n"
            f"{tree_note}\n\n"
            f"When you're ready, \"Export to Mod\" will build it into the HOI4 "
            f"folder and make it appear in the launcher:\n{mod_target}")
        self._model.status_message.emit(f"Created submod project at {proj_dir}")

    def _import_md_tree_for_tag(self, tag: str):
        """Auto-import the chosen country's Millennium Dawn focus tree (no picker).
        Returns a FocusForgeProject, or None if no dedicated MD tree exists for the
        tag (the caller then falls back to a blank placeholder tree)."""
        clean = "".join(ch for ch in (tag or "").upper() if ch.isalnum())[:3]
        if not clean:
            return None
        roots = provider().roots()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            refs = [r for r in find_focus_trees(roots) if r.tag == clean]
            if not refs:
                return None
            ref = max(refs, key=lambda r: r.focus_count)  # the country's main tree
            return import_focus_tree(ref, roots)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed",
                                f"Couldn't import the MD focus tree for {clean}:\n{exc}")
            return None
        finally:
            QGuiApplication.restoreOverrideCursor()

    def _choose_and_import_tree(self):
        """Open the import picker and return a FocusForgeProject, or None."""
        roots = provider().roots()
        dlg = ImportTreeDialog(roots, self)
        if not dlg.exec() or not dlg.selected_ref():
            return None
        ref = dlg.selected_ref()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            project = import_focus_tree(ref, roots)
            # Ad-hoc folder import: register the mod's folder(s) as transient icon
            # roots so its custom focus icons render (not persisted to Settings).
            if ref.roots:
                provider().add_extra_roots(ref.roots)
            return project
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

    def _manage_decisions(self) -> None:
        from .decisions_dialog import DecisionsManagerDialog
        DecisionsManagerDialog(self._model, self).exec()

    def _manage_shortcuts(self) -> None:
        from .shortcuts_dialog import ShortcutsManagerDialog
        ShortcutsManagerDialog(self._model, self).exec()

    def _on_add_shortcut(self, focus_id: str) -> None:
        """Node context menu → author a tree shortcut targeting this focus."""
        from .shortcut_editor import ShortcutEditorDialog
        dlg = ShortcutEditorDialog(self._model, target_default=focus_id, parent=self)
        if dlg.exec():
            self._model.add_shortcut(dlg.result_shortcut())
            self._model.status_message.emit(f"Added tree shortcut to {focus_id}.")

    def _show_devlog(self) -> None:
        from .devlog_dialog import DevLogDialog
        DevLogDialog(self).exec()

    # ----- auto-update -----
    def _check_for_updates(self, manual: bool = False) -> None:
        """Kick off a background release check. Silent unless ``manual``
        (the Settings button), which reports every outcome visibly."""
        if self._update_thread is not None:
            if manual:
                self._status_label.setText("Already checking for updates…")
            return
        self._update_check_manual = manual
        worker = UpdateCheckWorker(__version__)
        worker.update_available.connect(self._on_update_available)
        worker.no_update.connect(self._on_no_update)
        worker.failed.connect(self._on_update_check_failed)
        worker.finished.connect(self._on_update_check_done)
        self._update_worker = worker  # keep a ref until finished (GC guard)
        self._update_thread = run_in_thread(worker, self)

    def _on_update_check_done(self) -> None:
        self._update_worker = None
        self._update_thread = None

    def _on_update_available(self, info) -> None:
        self._update_info = info
        self._update_pill.setText(f"↑ v{info.version} available")
        self._update_pill.show()
        skipped = str(self._settings.value("update/skip_version", "") or "")
        if not self._update_check_manual and skipped == info.version:
            return  # user skipped this version — status-bar notice only
        self._open_update_dialog()

    def _on_no_update(self) -> None:
        if self._update_check_manual:
            QMessageBox.information(self, "Check for updates",
                                    f"You're up to date (v{__version__}).")

    def _on_update_check_failed(self, message: str) -> None:
        if self._update_check_manual:
            QMessageBox.warning(self, "Check for updates",
                                f"Couldn't check for updates:\n{message}")

    def _open_update_dialog(self) -> None:
        if self._update_info is None:
            return
        from .update_dialog import UpdateDialog
        # request_close=self.close → the dialog asks THIS window to close via
        # its normal closeEvent (unsaved-changes prompt included) before it
        # launches the installer; a cancelled close cancels the install.
        dlg = UpdateDialog(self._update_info, __version__,
                           request_close=self.close, parent=self)
        dlg.exec()
        if dlg.skip_requested():
            self._settings.setValue("update/skip_version", self._update_info.version)

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
        if not self._confirm_discard_changes():
            return
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
        else (legacy projects living in a mod) the ancestor descriptor.mod.

        Deliberately NOT the session default: that belongs to whichever project
        exported last, and falling back to it once built an opened project
        straight over a different mod's folder."""
        ed = (self._model.project.exportDir or "").strip()
        if ed:
            return ed
        if self._model.path:
            root = find_mod_root(self._model.path)
            if root:
                return root
        return None

    def _ensure_mod_scaffolded(self, target: str) -> bool:
        """Materialise the HOI4 mod folder (descriptor + skeleton) if it doesn't
        exist yet, using the project's stored modMeta (falling back to defaults)."""
        if os.path.isfile(os.path.join(target, "descriptor.mod")):
            # An existing mod folder keeps its descriptor — unless it still
            # declares the OTHER Millennium Dawn edition (the project was
            # converted in Settings after its first export).
            try:
                changed = retarget_descriptor(target, getattr(self._model.project, "mdEdition", "main"))
            except OSError as exc:
                changed = []
                self._model.status_message.emit(f"Could not update descriptor.mod: {exc}")
            if changed:
                ed = md_edition(getattr(self._model.project, "mdEdition", "main"))
                self._model.status_message.emit(
                    f"Updated {len(changed)} descriptor file(s) to depend on {ed.dependency} "
                    f"({ed.supported_version}).")
            return True
        meta = self._model.project.modMeta or {}
        name = meta.get("name") or self._model.project.projectName or os.path.basename(target)
        tags = meta.get("tags") or list(DEFAULT_TAGS)
        target_ed = md_edition(getattr(self._model.project, "mdEdition", "main"))
        deps = meta.get("dependencies")
        if deps is None:
            deps = [target_ed.dependency]
        sv = meta.get("supported_version") or target_ed.supported_version
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

    def _structure_all_rewards(self) -> None:
        """Project-wide raw-script conversion (rewards AND availability/bypass
        triggers): one undo step, one summary — instead of visiting focuses
        one by one in the editors."""
        from core.condition_script import structure_all_conditions
        self._flush_focused_editor()
        reward_candidates = sum(
            1 for f in self._model.project.focuses
            if f.completionReward and (f.completionReward.rawLines or []))
        trigger_candidates = sum(
            1 for f in self._model.project.focuses
            for rule in (f.available, getattr(f, "bypass", None))
            if rule is not None and (rule.rawLines or []))
        if not reward_candidates and not trigger_candidates:
            QMessageBox.information(self, "Structure Raw Scripts",
                                    "No focuses have raw reward or trigger script.")
            return
        with self._model.batch():
            r_conv, effects, r_skip = structure_all_rewards(self._model.project)
            c_conv, conditions, c_skip = structure_all_conditions(self._model.project)
        from core.applog import logger
        logger().info(
            "structure-raw: rewards %d/%d (%d effects), triggers %d/%d (%d conditions)",
            r_conv, reward_candidates, effects,
            c_conv, trigger_candidates, conditions)
        parts = []
        if reward_candidates:
            parts.append(f"Rewards: {r_conv} of {reward_candidates} focuses "
                         f"structured ({effects} effect"
                         f"{'s' if effects != 1 else ''}).")
        if trigger_candidates:
            parts.append(f"Triggers: {c_conv} of {trigger_candidates} "
                         f"availability/bypass blocks structured "
                         f"({conditions} condition"
                         f"{'s' if conditions != 1 else ''}).")
        skipped = sorted(set(r_skip) | set(c_skip))
        if skipped:
            shown = ", ".join(skipped[:5])
            more = f" (+{len(skipped) - 5} more)" if len(skipped) > 5 else ""
            parts.append(
                f"{len(skipped)} focus{'es' if len(skipped) != 1 else ''} kept "
                f"some raw script — unrecognized or partially recognized "
                f"(conversion is all-or-nothing per block, so script order is "
                f"preserved): {shown}{more}")
        if r_conv or c_conv:
            parts.append("One undo restores everything.")
        QMessageBox.information(self, "Structure Raw Scripts", "\n\n".join(parts))

    def _export_to_mod(self) -> None:
        self._flush_focused_editor()
        target = self._resolve_mod_dir()
        if not target:
            QMessageBox.information(
                self, "Export to Mod",
                "I don't know which mod to build into yet. Create it with "
                "\"New Submod\", or use Export As… to pick a destination.")
            self._export_as()
            return
        if not self._confirm_mod_identity(target):
            return
        if not self._ensure_mod_scaffolded(target):
            return
        self._default_export_dir = target
        if self._do_export(Path(target)):
            self._remember_export_dir(target)
            self._model.status_message.emit(f"Exported to mod: {target}")
            self._smoke_report(target)

    # ----- pre-flight / post-flight checks on the exported mod -----
    def _smoke_report(self, target: str) -> None:
        """Parse every file that was just written with the app's own script
        reader and apply the load-time rules the game enforces. Silent when
        clean (the status bar already says 'Exported'); a dialog otherwise."""
        from core.export_check import smoke_check
        from core.exporters import export_project_files
        try:
            issues = smoke_check(export_project_files(self._model.project))
        except Exception as exc:  # never let a checker failure look like an export failure
            self._model.status_message.emit(f"Smoke check skipped: {exc}")
            return
        if not issues:
            self._model.status_message.emit(
                f"Exported to mod: {target} — smoke check passed (every file parses, all localised).")
            return
        errors = [i for i in issues if i.severity == "error"]
        lines = [f"[{i.severity}] {i.message}" for i in issues[:25]]
        more = f"\n… and {len(issues) - 25} more" if len(issues) > 25 else ""
        QMessageBox.warning(
            self, "Smoke check",
            f"The mod was written, but the exported files have {len(errors)} error(s) and "
            f"{len(issues) - len(errors)} warning(s) the game would trip on:\n\n"
            + "\n".join(lines) + more)

    def _scan_error_log(self) -> None:
        """Read HOI4's error.log after the user has launched the game and show
        only the lines about this mod, each mapped back to its focus."""
        from core.export_check import default_error_log, format_hits, log_is_stale, scan_error_log
        from core.exporters import export_project_files
        path = default_error_log()
        if not os.path.isfile(path):
            QMessageBox.information(
                self, "Scan HOI4 error.log",
                f"No error.log found at:\n{path}\n\nLaunch Hearts of Iron IV with the mod enabled "
                f"once, quit, and run this again.")
            return
        mod_dir = self._resolve_mod_dir() or ""
        files = export_project_files(self._model.project)
        hits = scan_error_log(files, self._model.project, path, mod_dir=mod_dir)
        note = ""
        if log_is_stale(path, mod_dir):
            note = ("\n\nNote: the mod folder was exported AFTER this log was written — launch the "
                    "game again for a fresh log; line references below may point at old lines.")
        if not hits:
            QMessageBox.information(
                self, "Scan HOI4 error.log",
                f"No lines in error.log mention this mod. {os.path.basename(path)} last written "
                f"{_mtime_label(path)}.{note}")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Scan HOI4 error.log")
        box.setIcon(QMessageBox.Warning)
        focus_hits = [h for h in hits if h.focusId]
        box.setText(f"{len(hits)} line(s) in error.log mention this mod"
                    + (f"; {len(focus_hits)} map to a focus." if focus_hits else ".") + note)
        box.setDetailedText(format_hits(hits))
        box.setStandardButtons(QMessageBox.Ok)
        if focus_hits:
            jump = box.addButton("Select first focus", QMessageBox.ActionRole)
            box.exec()
            if box.clickedButton() is jump:
                self._model.set_selection(focus_hits[0].focusId)
        else:
            box.exec()

    def _confirm_mod_identity(self, target: str) -> bool:
        """Refuse-to-surprise guard: if ``target`` already holds a mod whose
        descriptor name doesn't look like this project, make the user say so
        explicitly before anything is overwritten."""
        existing = read_descriptor_name(target)
        if not existing:
            return True
        meta = self._model.project.modMeta or {}
        ours = (meta.get("name") or self._model.project.projectName or "").strip()
        if not ours or existing.strip().lower() == ours.lower():
            return True
        from core.applog import logger
        logger().info("export identity mismatch at %s: folder=%r project=%r",
                      target, existing, ours)
        ans = QMessageBox.warning(
            self, "Export to Mod",
            f"The folder\n{target}\nalready contains the mod \"{existing}\", "
            f"but this project is \"{ours}\".\n\nExporting would write this "
            f"project's files into that mod. Choose \"Pick Another Folder…\" "
            f"to export somewhere else.",
            QMessageBox.Yes | QMessageBox.Open | QMessageBox.Cancel,
            QMessageBox.Cancel)
        if ans == QMessageBox.Open:
            self._export_as()
            return False
        return ans == QMessageBox.Yes

    def _remember_export_dir(self, target: str) -> None:
        """Persist the export destination on the project itself so reopening it
        later (or on another machine) never inherits a different mod's folder."""
        if (self._model.project.exportDir or "").strip() != target:
            self._model.update_project_meta(exportDir=target)

    def _export_as(self) -> None:
        self._flush_focused_editor()
        directory = QFileDialog.getExistingDirectory(
            self, "Choose Export Directory",
            self._default_export_dir or default_mod_root())
        if not directory:
            return
        directory = self._prepare_export_destination(directory)
        if not directory:
            return
        self._default_export_dir = directory
        if self._do_export(Path(directory)):
            self._remember_export_dir(directory)
            self._model.status_message.emit(f"Exported to: {directory}")

    def _prepare_export_destination(self, directory: str):
        """Turn a picked directory into a real mod destination.

        Picking the HOI4 mods root itself (the classic mistake — game files
        splat bare next to the *.mod entries and the launcher shows nothing)
        offers to create a named mod folder inside it. Any other folder with no
        descriptor.mod offers to scaffold one so HOI4 can actually see the mod.
        Returns the (possibly new) directory, or None to cancel."""
        meta = self._model.project.modMeta or {}
        mod_name = (meta.get("name") or self._model.project.projectName or "").strip()
        if is_hoi4_mod_root(directory):
            from PySide6.QtWidgets import QInputDialog
            folder, ok = QInputDialog.getText(
                self, "Create Mod Folder",
                "That's the HOI4 mods folder itself — exporting game files "
                "straight into it makes a mod the launcher can't see.\n\n"
                "Create this mod folder inside it instead:",
                text=sanitize_folder(mod_name) or "my_submod")
            if not ok or not folder.strip():
                return None
            target = os.path.join(directory, sanitize_folder(folder))
            if not self._ensure_mod_scaffolded(target):
                return None
            return target
        if not os.path.isfile(os.path.join(directory, "descriptor.mod")):
            ans = QMessageBox.question(
                self, "Export As",
                f"{directory}\nisn't a HOI4 mod folder yet (no descriptor.mod).\n\n"
                f"Create the mod files here so the launcher can see it?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if ans == QMessageBox.Cancel:
                return None
            if ans == QMessageBox.Yes and not self._ensure_mod_scaffolded(directory):
                return None
        return directory

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
            # Custom focus-icon DDS (the focus tree is always exported).
            export_focus_icon_assets(self._model.project, str(directory))
            # Binary country assets (flag TGAs / custom portrait DDS) aren't text.
            if self._model.project.exportSettings.includeCountry and self._model.project.country:
                export_country_assets(self._model.project, str(directory))
            # Custom event-picture DDS (events are their own export section).
            if self._model.project.exportSettings.includeEvents and self._model.project.events:
                export_event_assets(self._model.project, str(directory))
            # Custom decision-icon DDS (decisions are their own export section).
            if self._model.project.exportSettings.includeDecisions and self._model.project.decisions:
                export_decision_assets(self._model.project, str(directory))
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

    def _on_clear_focuses(self) -> None:
        n = len(self._model.project.focuses)
        if n == 0:
            self._model.status_message.emit("No focuses to clear.")
            return
        ans = QMessageBox.warning(
            self, "Clear all focuses",
            f"This removes all {n} focus{'es' if n != 1 else ''} from this "
            f"project (ideas, events and country data are kept).\n\nYou can undo "
            f"this with Ctrl+Z. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self._model.delete_focuses([f.id for f in self._model.project.focuses])
        self._model.status_message.emit(f"Cleared {n} focuses")

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
        return self._model.free_cell_below(parent.id)

    def _on_delete_link(self, source_id: str, target_id: str, kind: str) -> None:
        if kind == "mutex":
            msg = self._model.remove_mutex(source_id, target_id)
        else:
            msg = self._model.remove_prerequisite(target_id, source_id)
        if msg:
            self._model.status_message.emit(msg)

    def _on_group_prereq(self, source_id: str, target_id: str) -> None:
        msg = self._model.group_prerequisite(target_id, source_id)
        if msg:
            self._model.status_message.emit(msg)

    def _on_ungroup_prereq(self, source_id: str, target_id: str) -> None:
        msg = self._model.ungroup_prerequisite(target_id, source_id)
        if msg:
            self._model.status_message.emit(msg)

    # ----- Millennium Dawn edition (main release vs beta) -----
    _last_md_edition_key = None

    def _apply_md_edition_to_roots(self, key: str) -> None:
        """Point the game-data roots at the MD edition ``key`` if they aren't
        already (no-op when that edition isn't installed — the user is told
        once in the status bar and can fix the folders in Settings)."""
        ok, msg = provider().switch_md_edition(key)
        if not ok or "now reads" in msg:
            self._model.status_message.emit(msg)

    def _sync_md_edition(self) -> None:
        """Keep three things in step with the open project's target edition:
        the preset builders (so previews/exports emit the right helper names),
        the game-data roots (so dropdowns, parties and imports come from the
        right MD), and the Settings combo. Only acts when the key changes."""
        key = getattr(self._model.project, "mdEdition", "main") or "main"
        if key == self._last_md_edition_key:
            return
        self._last_md_edition_key = key
        set_active_edition(key)
        self._apply_md_edition_to_roots(key)

    def _on_project_changed(self) -> None:
        self._sync_md_edition()
        self._scene.reconcile(self._model.project, self._model.selected_id)
        self._delete_action.setEnabled(bool(self._model.selected_id))
        self._apply_search_highlight()  # re-apply after nodes are rebuilt
        # Pre-decode this project's focus icons off-thread so a big imported tree
        # doesn't freeze on its first paint (no-op once they're all cached).
        provider().warm_focus_icons_async([f.icon for f in self._model.project.focuses])

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
        if self._confirm_discard_changes():
            self._finish_close(event)
        else:
            event.ignore()

    def _finish_close(self, event) -> None:
        self._bridge.stop()  # release the port + remove the discovery file
        event.accept()


def _mtime_label(path: str) -> str:
    """'today 17:57' / '2026-09-01 22:10' for a file's last write, for log notes."""
    import datetime
    try:
        ts = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return "at an unknown time"
    if ts.date() == datetime.date.today():
        return f"today at {ts:%H:%M}"
    return f"{ts:%Y-%m-%d %H:%M}"
