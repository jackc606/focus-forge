"""Right-tab: per-focus inspector. v1 covers id/title/desc/icon/position/cost/filters/prereqs/mutex/raw rewards."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import QImage, QPixmap

from .no_scroll import NoScrollComboBox as QComboBox
from .no_scroll import NoScrollDoubleSpinBox as QDoubleSpinBox
from .no_scroll import NoScrollSpinBox as QSpinBox

from core.presets import MD_FOCUS_FILTERS, MD_ICON_PRESETS
from core.types import CompletionReward, FocusPosition, normalize_prereq_groups

from . import theme as T
from .availability_editor import AvailabilityEditor
from .chip_selector import ChipSelector
from .country_editor import _IMG_FILTER, _scaled_b64_png
from .country_export import _qimage_from_b64
from .icon_picker import IconPickerDialog
from .icon_provider import provider
from .project_model import ProjectModel
from .reward_editor import RewardEditor
from .widgets import BracketFrame, divider, panel_header, section_header

# In-game focus icon size (all base/MD focus icons are 100×88).
_FOCUS_ICON_W, _FOCUS_ICON_H = 100, 88


class InspectorPanel(QWidget):
    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._suspend = False
        # When True, the focus id tracks the title (auto tag_slug). Flips off the
        # moment the user hand-edits the id, or when an id no longer looks auto.
        self._id_auto = False
        self._issues_cache = None  # last validation_changed payload

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # fit width, never scroll sideways
        outer.addWidget(scroll)

        self._holder = QWidget()
        scroll.setWidget(self._holder)
        v = QVBoxLayout(self._holder)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Inspector"))

        self._empty_label = QLabel(
            "No focus selected.\nClick a node on the canvas, or pick one from "
            "the Focuses list.")
        self._empty_label.setObjectName("muted")
        self._empty_label.setWordWrap(True)  # don't force a wide minimum on the panel
        v.addWidget(self._empty_label)

        self._form_group = QWidget()
        v.addWidget(self._form_group)
        fg = QVBoxLayout(self._form_group)
        fg.setContentsMargins(0, 0, 0, 0)
        fg.setSpacing(T.SPACE_MD)

        # ----- Dossier card: the selected focus as an in-game style plate -----
        # Icon in the canvas-node bracket frame, title + id edited in place,
        # and a quiet mono meta row (position · cost in days · AI weight).
        card = QFrame()
        card.setObjectName("dossierCard")
        ch = QHBoxLayout(card)
        ch.setContentsMargins(T.SPACE_MD, T.SPACE_MD, T.SPACE_MD, T.SPACE_MD)
        ch.setSpacing(T.SPACE_MD)

        self._icon_preview = QLabel()
        self._icon_preview.setFixedSize(56, 49)
        self._icon_preview.setAlignment(Qt.AlignCenter)
        self._icon_preview.setObjectName("dossierIcon")
        ch.addWidget(BracketFrame(self._icon_preview), 0, Qt.AlignTop)

        ident = QVBoxLayout()
        ident.setSpacing(2)
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("identityTitle")
        self._title_edit.setPlaceholderText("Untitled focus")
        self._title_edit.setToolTip("Focus title as the player sees it. Edit in place.")
        ident.addWidget(self._title_edit)
        self._id_edit = QLineEdit()
        self._id_edit.setObjectName("identityId")
        self._id_edit.setPlaceholderText("focus_id")
        self._id_edit.setToolTip(
            "Focus id — renames rewrite every reference (prerequisites, mutex, "
            "availability) project-wide.")
        ident.addWidget(self._id_edit)
        meta = QHBoxLayout()
        meta.setSpacing(T.SPACE_XS)
        self._meta_pos = QLabel()
        self._meta_pos.setObjectName("metaChip")
        self._meta_pos.setToolTip("Grid position (x, y)")
        self._meta_cost = QLabel()
        self._meta_cost.setObjectName("metaChip")
        self._meta_cost.setToolTip("Focus cost — 1 cost = 7 in-game days")
        self._meta_ai = QLabel()
        self._meta_ai.setObjectName("metaChip")
        self._meta_ai.setToolTip("AI priority (ai_will_do) — shown when not the default 10")
        meta.addWidget(self._meta_pos)
        meta.addWidget(self._meta_cost)
        meta.addWidget(self._meta_ai)
        meta.addStretch(1)
        ident.addSpacing(2)
        ident.addLayout(meta)
        ch.addLayout(ident, 1)
        # Validation health for THIS focus: green dot = clean, amber = warnings,
        # red = errors; the tooltip lists the actual messages.
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._status_dot.setObjectName("statusDotOk")
        ch.addWidget(self._status_dot, 0, Qt.AlignTop)
        fg.addWidget(card)

        def _section(title: str) -> QFormLayout:
            fg.addWidget(divider())
            fg.addWidget(section_header(title))
            holder = QWidget()
            form = QFormLayout(holder)
            form.setContentsMargins(0, 0, 0, 0)
            form.setLabelAlignment(Qt.AlignRight)
            form.setSpacing(8)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            fg.addWidget(holder)
            return form

        # ----- Presentation -----
        form = _section("PRESENTATION")
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setMinimumHeight(70)
        self._desc_edit.setPlaceholderText("What the player reads — two or three sentences.")
        form.addRow("Description", self._desc_edit)

        # Icon: name row + action row stacked — side by side they force the form
        # wider than the panel and every field gets clipped (the inspector never
        # scrolls sideways). The preview lives in the dossier card above.
        self._icon_edit = QComboBox()
        self._icon_edit.setEditable(True)
        self._icon_edit.addItems(MD_ICON_PRESETS)
        icon_row = QWidget()
        ic = QVBoxLayout(icon_row)
        ic.setContentsMargins(0, 0, 0, 0)
        ic.setSpacing(6)
        ic.addWidget(self._icon_edit)
        ib = QHBoxLayout()
        ib.setSpacing(6)
        self._icon_browse = QPushButton("Browse…")
        self._icon_browse.setToolTip("Choose an in-game focus icon from a visual grid.")
        self._icon_browse.clicked.connect(self._open_icon_picker)
        ib.addWidget(self._icon_browse)
        self._icon_import = QPushButton("Import…")
        self._icon_import.setToolTip(
            f"Import a custom focus icon. HOI4 focus icons are {_FOCUS_ICON_W}×"
            f"{_FOCUS_ICON_H} px, exported as .dds (.png/.tga/.dds in).")
        self._icon_import.clicked.connect(self._import_icon)
        ib.addWidget(self._icon_import)
        self._icon_clear = QPushButton("×")
        self._icon_clear.setObjectName("deleteButton")
        self._icon_clear.setToolTip("Remove the custom imported icon (go back to the named icon)")
        self._icon_clear.setFixedWidth(28)
        self._icon_clear.clicked.connect(self._clear_custom_icon)
        ib.addWidget(self._icon_clear)
        ib.addStretch(1)
        ic.addLayout(ib)
        form.addRow("Icon", icon_row)

        # ----- Placement & pacing -----
        form = _section("PLACEMENT & PACING")
        pos_holder = QWidget()
        ph = QHBoxLayout(pos_holder)
        ph.setContentsMargins(0, 0, 0, 0)
        self._pos_x = QSpinBox()
        self._pos_x.setRange(-9999, 9999)
        self._pos_y = QSpinBox()
        self._pos_y.setRange(-9999, 9999)
        ph.addWidget(QLabel("x"))
        ph.addWidget(self._pos_x)
        ph.addWidget(QLabel("y"))
        ph.addWidget(self._pos_y)
        ph.addStretch(1)
        form.addRow("Position", pos_holder)

        cost_holder = QWidget()
        cl = QHBoxLayout(cost_holder)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(T.SPACE_SM)
        self._cost_edit = QDoubleSpinBox()
        self._cost_edit.setRange(0, 9999)
        self._cost_edit.setDecimals(2)
        cl.addWidget(self._cost_edit)
        self._cost_days = QLabel()
        self._cost_days.setObjectName("hint")
        cl.addWidget(self._cost_days)
        cl.addStretch(1)
        form.addRow("Cost", cost_holder)

        self._ai_priority = QDoubleSpinBox()
        self._ai_priority.setRange(0, 9999)
        self._ai_priority.setDecimals(1)
        self._ai_priority.setToolTip(
            "ai_will_do base — how strongly the AI prioritizes this focus. 10 is "
            "the default; higher means picked sooner, 0 makes the AI avoid it.")
        form.addRow("AI Priority", self._ai_priority)

        # ----- Graph links -----
        form = _section("GRAPH LINKS")
        self._filters = ChipSelector(MD_FOCUS_FILTERS, "add filter…")
        form.addRow("Filters", self._filters)

        self._prereqs = ChipSelector(placeholder="add prerequisite focus…")
        self._prereqs.setToolTip(
            "Each chip is a required (AND) prerequisite. A chip with | is an OR "
            "group — any one of those focuses unlocks this one. Type e.g. "
            "TAG_a | TAG_b to create a group.")
        form.addRow("Prerequisites", self._prereqs)

        self._mutex = ChipSelector(placeholder="add mutually-exclusive focus…")
        form.addRow("Mutually Exclusive", self._mutex)

        # Toggle for the raw-lines inputs + generated script previews in both
        # editors below — hidden by default to keep the inspector clean.
        # "&&" — a single "&" is a Qt mnemonic and renders as an underline.
        self._show_script = QCheckBox("Show raw script && generated blocks")
        v.addWidget(self._show_script)

        def _counted_header(title: str):
            """Section header with a right-aligned muted count summary."""
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(section_header(title))
            row.addStretch(1)
            count = QLabel()
            count.setObjectName("hint")
            row.addWidget(count)
            return row, count

        # Availability (when can it be taken) — same section language as above,
        # no nested group boxes.
        self._avail_divider = divider()
        v.addWidget(self._avail_divider)
        self._avail_group = QWidget()
        ag = QVBoxLayout(self._avail_group)
        ag.setContentsMargins(0, 0, 0, 0)
        ag.setSpacing(T.SPACE_SM)
        header_row, self._avail_count = _counted_header("AVAILABILITY")
        ag.addLayout(header_row)
        self._avail_editor = AvailabilityEditor(model)
        ag.addWidget(self._avail_editor)
        v.addWidget(self._avail_group)

        # Reward editor
        self._reward_divider = divider()
        v.addWidget(self._reward_divider)
        self._reward_group = QWidget()
        rg = QVBoxLayout(self._reward_group)
        rg.setContentsMargins(0, 0, 0, 0)
        rg.setSpacing(T.SPACE_SM)
        header_row, self._reward_count = _counted_header("COMPLETION REWARD")
        rg.addLayout(header_row)
        self._reward_editor = RewardEditor(model)
        rg.addWidget(self._reward_editor)
        v.addWidget(self._reward_group)
        v.addStretch(1)

        # Wire signals
        self._id_edit.editingFinished.connect(self._commit_id)
        # A manual id edit detaches the id from the title (textEdited fires only on
        # user input, not on our programmatic setText).
        self._id_edit.textEdited.connect(lambda *_: setattr(self, "_id_auto", False))
        self._title_edit.textChanged.connect(self._on_title_text)
        self._title_edit.editingFinished.connect(self._commit_title)
        self._desc_edit.textChanged.connect(self._commit_description)
        self._icon_edit.currentTextChanged.connect(self._on_icon_text)
        self._pos_x.valueChanged.connect(self._commit_position)
        self._pos_y.valueChanged.connect(self._commit_position)
        self._cost_edit.valueChanged.connect(self._on_cost_changed)
        # 10 is HOI4's effective default — store None so untouched focuses
        # serialize and export byte-identically to before this field existed.
        self._ai_priority.valueChanged.connect(self._on_ai_changed)
        self._filters.tokens_changed.connect(lambda v: self._commit("filters", v))
        self._prereqs.tokens_changed.connect(self._commit_prereqs)
        self._mutex.tokens_changed.connect(lambda v: self._commit("mutuallyExclusive", v))

        self._model.selection_changed.connect(self._on_selection)
        self._model.project_changed.connect(self._refresh_suggestions)
        self._model.validation_changed.connect(self._on_validation_issues)
        provider().changed.connect(self._refresh_icon_preview)

        # Restore the script-visibility preference and apply it to both editors.
        self._settings = QSettings("FocusForge", "FocusForge")
        show_script = self._settings.value("inspector_show_script", False, type=bool)
        self._show_script.setChecked(show_script)
        self._reward_editor.set_script_visible(show_script)
        self._avail_editor.set_script_visible(show_script)
        self._show_script.toggled.connect(self._on_toggle_script)

        self._refresh_suggestions()
        self._on_selection(self._model.selected_id)

    def _on_toggle_script(self, show: bool) -> None:
        self._settings.setValue("inspector_show_script", bool(show))
        self._reward_editor.set_script_visible(show)
        self._avail_editor.set_script_visible(show)

    def _refresh_suggestions(self) -> None:
        # Only refresh the prereq/mutex dropdown suggestions on project change.
        # Do NOT re-render the reward/availability editors here — they re-render
        # on selection change, and re-rendering on every project_changed (which
        # their own edits emit) destroys the card/dropdown mid-interaction.
        sel = self._model.selected_id
        ids = [f.id for f in self._model.project.focuses]
        self._prereqs.update_suggestions([i for i in ids if i != sel])
        self._mutex.update_suggestions([i for i in ids if i != sel])
        # Section counts are cheap (they read one focus) and safe to refresh on
        # every project change — they never re-render the editors themselves.
        # The status dot is NOT refreshed here: it needs full-project validation,
        # so it rides the model's debounced validation_changed signal instead
        # (running it per project_changed made every drag grid-step revalidate
        # the whole tree).
        if sel and self._model.find_focus(sel):
            self._refresh_counts()

    def _on_selection(self, focus_id: str) -> None:
        focus = self._model.find_focus(focus_id)
        if not focus:
            self._form_group.setVisible(False)
            self._show_script.setVisible(False)
            self._reward_group.setVisible(False)
            self._reward_divider.setVisible(False)
            self._avail_group.setVisible(False)
            self._avail_divider.setVisible(False)
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)
        self._form_group.setVisible(True)
        self._show_script.setVisible(True)
        self._reward_group.setVisible(True)
        self._reward_divider.setVisible(True)
        self._avail_group.setVisible(True)
        self._avail_divider.setVisible(True)

        self._suspend = True
        # The id follows the title while it still looks machine-made: either the
        # "…new_focus_NNN" placeholder, or exactly the slug the auto-generator
        # would produce from the current title (so re-titling an existing focus
        # keeps its id in sync). A hand-crafted id — anything that doesn't match
        # its own title's slug — never gets touched.
        self._id_auto = (self._is_auto_focus_id(focus.id)
                         or (bool(focus.id)
                             and focus.id == self._auto_id_from_title(focus.title)))
        self._id_edit.setText(focus.id)
        self._title_edit.setText(focus.title)
        if self._desc_edit.toPlainText() != focus.description:
            self._desc_edit.setPlainText(focus.description)
        self._icon_edit.setCurrentText(focus.icon)
        self._pos_x.setValue(int(focus.position.x))
        self._pos_y.setValue(int(focus.position.y))
        self._cost_edit.setValue(float(focus.cost))
        self._ai_priority.setValue(10.0 if getattr(focus, "aiWillDo", None) is None
                                   else float(focus.aiWillDo))
        self._filters.set_tokens(focus.filters)
        self._prereqs.set_tokens(self._prereq_display_tokens(focus.prerequisites))
        self._mutex.set_tokens(focus.mutuallyExclusive)
        others = [f.id for f in self._model.project.focuses if f.id != focus.id]
        self._prereqs.update_suggestions(others)
        self._mutex.update_suggestions(others)
        self._suspend = False
        self._reward_editor.set_focus_id(focus.id)
        self._avail_editor.set_focus_id(focus.id)
        self._refresh_icon_preview()
        self._refresh_meta()
        self._refresh_status()
        self._refresh_counts()

    # ----- dossier meta row -----
    def _refresh_meta(self) -> None:
        """Mirror position / cost / AI weight into the dossier card's mono chips
        (cost also shown as in-game days: 1 cost = 7 days)."""
        focus = self._model.find_focus(self._model.selected_id)
        if not focus:
            return
        self._meta_pos.setText(f"({focus.position.x}, {focus.position.y})")
        cost = float(focus.cost)
        days = int(round(cost * 7))
        self._meta_cost.setText(f"{cost:g} cost · {days}d")
        self._cost_days.setText(f"≈ {days} in-game days")
        ai = getattr(focus, "aiWillDo", None)
        self._meta_ai.setVisible(ai is not None)
        if ai is not None:
            self._meta_ai.setText(f"AI {float(ai):g}")

    def _on_cost_changed(self, value: float) -> None:
        self._commit("cost", value)
        self._refresh_meta()

    def _on_ai_changed(self, value: float) -> None:
        self._commit("aiWillDo", None if value == 10 else value)
        self._refresh_meta()

    # ----- validation status dot -----
    def _on_validation_issues(self, issues: list) -> None:
        """Debounced full-project validation results from the model — cache
        them so the dot never triggers a validation pass of its own."""
        self._issues_cache = list(issues)
        if self._model.selected_id:
            self._refresh_status()

    def _refresh_status(self) -> None:
        fid = self._model.selected_id
        if not fid or not self._model.find_focus(fid):
            return
        if self._issues_cache is None:  # first selection before any debounce fired
            self._issues_cache = self._model.issues()
        mine = [i for i in self._issues_cache if i.focusId == fid]
        errors = [i for i in mine if i.severity == "error"]
        warnings = [i for i in mine if i.severity != "error"]
        name = ("statusDotError" if errors
                else "statusDotWarn" if warnings else "statusDotOk")
        if self._status_dot.objectName() != name:
            self._status_dot.setObjectName(name)
            # Re-polish so the QSS keyed on the new object name applies.
            self._status_dot.style().unpolish(self._status_dot)
            self._status_dot.style().polish(self._status_dot)
        shown = errors + warnings
        tip = "\n".join(i.message for i in shown[:6])
        if len(shown) > 6:
            tip += f"\n…and {len(shown) - 6} more"
        self._status_dot.setToolTip(tip or "No validation issues for this focus.")

    # ----- section count summaries -----
    @staticmethod
    def _top_level_statements(lines) -> int:
        """Statements at brace-depth 0 in flattened raw lines — a rough but
        stable 'how many things does this do' count."""
        depth = 0
        n = 0
        for ln in lines or []:
            s = ln.strip()
            if not s:
                continue
            if depth == 0 and not s.startswith("}"):
                n += 1
            depth = max(0, depth + s.count("{") - s.count("}"))
        return n

    def _refresh_counts(self) -> None:
        focus = self._model.find_focus(self._model.selected_id)
        if not focus:
            return
        reward = focus.completionReward
        items = [i for i in (getattr(reward, "items", None) or [])
                 if getattr(i, "enabled", True)]
        raw = getattr(reward, "rawLines", None) or []
        effects = len(items) + self._top_level_statements(raw)
        events = sum(1 for ln in raw
                     if "=" in ln and ("country_event" in ln or "news_event" in ln))
        events += sum(1 for i in items
                      if getattr(i, "kind", "") in ("country_event", "news_event"))
        parts = [f"{effects} effect{'s' if effects != 1 else ''}"]
        if events:
            parts.append(f"{events} event{'s' if events != 1 else ''}")
        self._reward_count.setText(" · ".join(parts) if effects else "none")

        rule = focus.available
        if rule is None:
            self._avail_count.setText("always")
        else:
            n = (len(rule.completedFocuses or []) + len(rule.flagsRequired or [])
                 + len(rule.flagsBlocked or []) + len(rule.items or [])
                 + self._top_level_statements(rule.rawLines))
            self._avail_count.setText(
                f"{n} condition{'s' if n != 1 else ''}" if n else "always")

    def _on_icon_text(self, value: str) -> None:
        self._commit("icon", value)
        self._refresh_icon_preview()

    def _refresh_icon_preview(self) -> None:
        focus = self._model.find_focus(self._model.selected_id)
        custom = getattr(focus, "iconData", "") if focus else ""
        self._icon_clear.setVisible(bool(custom))
        pm = None
        if custom:
            img = _qimage_from_b64(custom)
            pm = QPixmap.fromImage(img) if img is not None else None
            self._icon_preview.setToolTip(
                "Custom imported icon — overrides the icon name on export.")
        else:
            pm = provider().pixmap(self._icon_edit.currentText())
            self._icon_preview.setToolTip("")
        if pm is not None and not pm.isNull():
            self._icon_preview.setPixmap(pm.scaled(
                56, 49, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._icon_preview.clear()

    def _open_icon_picker(self) -> None:
        dlg = IconPickerDialog(current=self._icon_edit.currentText(), parent=self)
        if dlg.exec() and dlg.selected_name():
            self._commit("iconData", "")  # picking a sprite drops the custom image
            self._icon_edit.setCurrentText(dlg.selected_name())
            self._refresh_icon_preview()

    def _import_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import focus icon — {_FOCUS_ICON_W}×{_FOCUS_ICON_H} px "
            f"(.png/.tga/.dds)",
            "", _IMG_FILTER)
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Import failed",
                                "Couldn't read that image — use a .png, .tga, or .dds.")
            return
        # Auto-scale to the standard HOI4 focus-icon size (100×88) so the export
        # is always the correct dimensions.
        self._commit("iconData", _scaled_b64_png(img, _FOCUS_ICON_W, _FOCUS_ICON_H))
        self._refresh_icon_preview()

    def _clear_custom_icon(self) -> None:
        self._commit("iconData", "")
        self._refresh_icon_preview()

    def _commit(self, field: str, value) -> None:
        if self._suspend:
            return
        sel = self._model.selected_id
        if not sel:
            return
        self._model.update_focus(sel, **{field: value})

    # ----- OR-group-aware prerequisite chips -----
    # One chip per prerequisites ELEMENT: a plain id stays one chip; an OR group
    # renders as its members joined with " | " (any one suffices). Round-tripping
    # whole elements — instead of flattened ids — is what keeps a group intact
    # when an unrelated chip is added or removed.
    @staticmethod
    def _prereq_display_tokens(prerequisites) -> list:
        out = []
        for element in (prerequisites or []):
            if isinstance(element, (list, tuple)):
                ids = [p for p in element if isinstance(p, str) and p.strip()]
                if ids:
                    out.append(" | ".join(ids))
            elif isinstance(element, str) and element.strip():
                out.append(element)
        return out

    @staticmethod
    def _parse_prereq_tokens(tokens) -> list:
        """Chip tokens → canonical prerequisites. A token containing ``|`` is an
        OR group (split, strip, drop blanks; one survivor = plain id)."""
        parsed = []
        for token in (tokens or []):
            token = str(token)
            if "|" in token:
                members = [p.strip() for p in token.split("|") if p.strip()]
                if len(members) > 1:
                    parsed.append(members)
                elif members:
                    parsed.append(members[0])
            elif token.strip():
                parsed.append(token.strip())
        return normalize_prereq_groups(parsed)

    def _commit_prereqs(self, tokens) -> None:
        self._commit("prerequisites", self._parse_prereq_tokens(tokens))

    def _commit_description(self) -> None:
        self._commit("description", self._desc_edit.toPlainText())

    def _commit_position(self) -> None:
        if self._suspend:
            return
        sel = self._model.selected_id
        if not sel:
            return
        self._model.update_focus(sel, position=FocusPosition(x=self._pos_x.value(), y=self._pos_y.value()))
        self._refresh_meta()

    # ----- title → auto id -----
    def _on_title_text(self, text: str) -> None:
        """Live-preview the auto id while the title is typed. The model commit
        happens on editingFinished (``_commit_title``)."""
        if self._suspend or not self._id_auto:
            return
        base = self._auto_id_from_title(text)
        if base:
            self._id_edit.setText(self._unique_focus_id(base, ignore=self._model.selected_id))

    def _commit_title(self) -> None:
        if self._suspend:
            return
        sel = self._model.selected_id
        focus = self._model.find_focus(sel)
        if not focus:
            return
        new_title = self._title_edit.text()
        title_changed = new_title != focus.title
        self._model.update_focus(sel, title=new_title)
        if self._id_auto and title_changed:
            base = self._auto_id_from_title(new_title)
            if base:
                self._rename_focus_id(sel, self._unique_focus_id(base, ignore=sel))

    def _auto_id_from_title(self, title: str) -> str:
        """``<TAG>_<slug>`` from a title (HOI4 convention), e.g. 'Industrial Plan'
        → 'MEX_industrial_plan'. Empty when there's nothing to slug."""
        tag = re.sub(r"[^A-Za-z0-9]", "", self._model.project.countryTag or "").upper()
        slug = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
        if tag and slug:
            return f"{tag}_{slug}"
        return slug

    @staticmethod
    def _is_auto_focus_id(focus_id: str) -> bool:
        """True for the placeholder ids new focuses get (``…new_focus_NNN``)."""
        return bool(re.match(r"^(?:[A-Za-z0-9]+_)?new_focus_\d+$", focus_id or ""))

    def _unique_focus_id(self, base: str, ignore: str = "") -> str:
        existing = {f.id for f in self._model.project.focuses if f.id != ignore}
        if base and base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def _commit_id(self) -> None:
        if self._suspend:
            return
        self._rename_focus_id(self._model.selected_id, self._id_edit.text().strip())

    def _rename_focus_id(self, old_id: str, new_id: str) -> None:
        """Rename a focus + rewrite references. Delegates to the model so the GUI
        and the AI bridge share one implementation."""
        self._model.rename_focus(old_id, new_id)
