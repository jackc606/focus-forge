"""Right-tab: per-focus inspector. v1 covers id/title/desc/icon/position/cost/filters/prereqs/mutex/raw rewards."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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
from core.types import CompletionReward, FocusPosition

from . import theme as T
from .availability_editor import AvailabilityEditor
from .chip_selector import ChipSelector
from .country_editor import _IMG_FILTER, _scaled_b64_png
from .country_export import _qimage_from_b64
from .icon_picker import IconPickerDialog
from .icon_provider import provider
from .project_model import ProjectModel
from .reward_editor import RewardEditor
from .widgets import divider, panel_header

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

        self._empty_label = QLabel("Select a focus on the canvas or in the focuses list.")
        self._empty_label.setObjectName("muted")
        self._empty_label.setWordWrap(True)  # don't force a wide minimum on the panel
        v.addWidget(self._empty_label)

        self._form_group = QWidget()
        v.addWidget(self._form_group)
        form = QFormLayout(self._form_group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._id_edit = QLineEdit()
        form.addRow("ID", self._id_edit)
        self._title_edit = QLineEdit()
        form.addRow("Title", self._title_edit)
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setMinimumHeight(70)
        form.addRow("Description", self._desc_edit)

        # Icon: preview + name on the first line, the action buttons on a second
        # line — side by side they force the form wider than the panel and every
        # field gets clipped (the inspector never scrolls sideways).
        self._icon_edit = QComboBox()
        self._icon_edit.setEditable(True)
        self._icon_edit.addItems(MD_ICON_PRESETS)
        icon_row = QWidget()
        ic = QVBoxLayout(icon_row)
        ic.setContentsMargins(0, 0, 0, 0)
        ic.setSpacing(6)
        ir = QHBoxLayout()
        ir.setSpacing(6)
        self._icon_preview = QLabel()
        self._icon_preview.setFixedSize(40, 34)
        self._icon_preview.setAlignment(Qt.AlignCenter)
        self._icon_preview.setObjectName("iconPreview")
        ir.addWidget(self._icon_preview)
        ir.addWidget(self._icon_edit, 1)
        ic.addLayout(ir)
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

        self._cost_edit = QDoubleSpinBox()
        self._cost_edit.setRange(0, 9999)
        self._cost_edit.setDecimals(2)
        form.addRow("Cost", self._cost_edit)

        self._filters = ChipSelector(MD_FOCUS_FILTERS, "add filter…")
        form.addRow("Filters", self._filters)

        self._prereqs = ChipSelector(placeholder="add prerequisite focus…")
        form.addRow("Prerequisites", self._prereqs)

        self._mutex = ChipSelector(placeholder="add mutually-exclusive focus…")
        form.addRow("Mutually Exclusive", self._mutex)

        # Toggle for the raw-lines inputs + generated script previews in both
        # editors below — hidden by default to keep the inspector clean.
        # "&&" — a single "&" is a Qt mnemonic and renders as an underline.
        self._show_script = QCheckBox("Show raw script && generated blocks")
        v.addWidget(self._show_script)

        # Availability (when can it be taken)
        self._avail_divider = divider()
        v.addWidget(self._avail_divider)
        self._avail_group = QGroupBox("Availability")
        ag = QVBoxLayout(self._avail_group)
        self._avail_editor = AvailabilityEditor(model)
        ag.addWidget(self._avail_editor)
        v.addWidget(self._avail_group)

        # Reward editor
        self._reward_divider = divider()
        v.addWidget(self._reward_divider)
        self._reward_group = QGroupBox("Completion Reward")
        rg = QVBoxLayout(self._reward_group)
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
        self._cost_edit.valueChanged.connect(lambda v: self._commit("cost", v))
        self._filters.tokens_changed.connect(lambda v: self._commit("filters", v))
        self._prereqs.tokens_changed.connect(lambda v: self._commit("prerequisites", v))
        self._mutex.tokens_changed.connect(lambda v: self._commit("mutuallyExclusive", v))

        self._model.selection_changed.connect(self._on_selection)
        self._model.project_changed.connect(self._refresh_suggestions)
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
        # A freshly-added focus (still "…new_focus_NNN") has its id follow the title
        # until the user names it or hand-edits the id.
        self._id_auto = self._is_auto_focus_id(focus.id)
        self._id_edit.setText(focus.id)
        self._title_edit.setText(focus.title)
        if self._desc_edit.toPlainText() != focus.description:
            self._desc_edit.setPlainText(focus.description)
        self._icon_edit.setCurrentText(focus.icon)
        self._pos_x.setValue(int(focus.position.x))
        self._pos_y.setValue(int(focus.position.y))
        self._cost_edit.setValue(float(focus.cost))
        self._filters.set_tokens(focus.filters)
        self._prereqs.set_tokens(focus.prerequisites)
        self._mutex.set_tokens(focus.mutuallyExclusive)
        others = [f.id for f in self._model.project.focuses if f.id != focus.id]
        self._prereqs.update_suggestions(others)
        self._mutex.update_suggestions(others)
        self._suspend = False
        self._reward_editor.set_focus_id(focus.id)
        self._avail_editor.set_focus_id(focus.id)
        self._refresh_icon_preview()

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
                40, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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

    def _commit_description(self) -> None:
        self._commit("description", self._desc_edit.toPlainText())

    def _commit_position(self) -> None:
        if self._suspend:
            return
        sel = self._model.selected_id
        if not sel:
            return
        self._model.update_focus(sel, position=FocusPosition(x=self._pos_x.value(), y=self._pos_y.value()))

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
