"""Dialogs to author HOI4 / Millennium Dawn decisions and decision categories.

The decision editor exposes structured fields for everything common — category,
icon, political-power cost, timers/cooldowns, mission settings, visible /
available triggers, complete / remove / timeout effects, active modifiers and
AI weighting — and a raw-lines escape hatch for anything else HOI4 supports
(targets, highlight_states, custom_cost_trigger, on_map_modes, …).
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
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
    QVBoxLayout,
    QWidget,
)

from core.reward_presets import format_number
from core.types import (
    AvailabilityRule,
    CompletionReward,
    DecisionCategory,
    DecisionData,
    FocusForgeProject,
)

from . import theme as T
from .country_editor import _scaled_b64_png
from .country_export import _qimage_from_b64
from .icon_picker import IconPickerDialog
from .icon_provider import provider
# Same searchable, grouped MD-modifier combo the idea editor uses.
from .idea_editor import _build_modifier_combo
from .no_scroll import NoScrollComboBox, NoScrollDoubleSpinBox, NoScrollSpinBox
from .preset_list import ConditionListWidget, EffectListWidget
from .tech_provider import tech_provider
from .widgets import hint, panel_header, section_header

_MOD_LINE = re.compile(r"([A-Za-z0-9_]+)\s*=\s*(-?[\d.]+)")
_ICON_PREVIEW_W, _ICON_PREVIEW_H = 38, 38
# HOI4 decision icons are small square images; imported art is scaled to this
# exact size and exported as .dds.
_DECISION_ICON_PX = 100
_IMG_FILTER = "Images (*.png *.tga *.jpg *.jpeg *.bmp *.dds);;All files (*)"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _off_spin(maximum: int, tooltip: str) -> NoScrollSpinBox:
    """Spin whose -1 minimum renders as '(off)' and means 'omit the field' —
    0 stays representable (it's a legal HOI4 value: instant timers)."""
    sb = NoScrollSpinBox()
    sb.setRange(-1, maximum)
    sb.setSpecialValueText("(off)")
    sb.setToolTip(tooltip)
    return sb


def _optional_value(spin) -> "int | None":
    return None if spin.value() == spin.minimum() else int(spin.value())


class DecisionCategoryEditorDialog(QDialog):
    """Author one decisions-panel category: title/id, icon, panel priority,
    visibility conditions, and a raw escape hatch."""

    def __init__(self, model, category: DecisionCategory = None, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._editing = category is not None
        self.setWindowTitle("Edit Decision Category" if self._editing else "New Decision Category")
        self.resize(*T.DIALOG_MD)
        self._icon = (category.icon if category
                      else "GFX_decision_category_generic_political_actions")
        self._id_edited = self._editing

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Decision Category"))
        v.addWidget(hint("A tab in the in-game decisions panel. Only your country "
                         "sees it (the export gates it on your tag)."))

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)

        self._title = QLineEdit(category.title if category else "")
        self._title.textChanged.connect(self._on_title)
        form.addRow("Title", self._title)
        self._id = QLineEdit(category.id if category else "")
        self._id.textEdited.connect(lambda *_: setattr(self, "_id_edited", True))
        form.addRow("ID", self._id)
        self._desc = QPlainTextEdit(category.description if category else "")
        self._desc.setMaximumHeight(T.TEXTAREA_SHORT)
        form.addRow("Description", self._desc)

        icon_row = QWidget()
        ir = QHBoxLayout(icon_row)
        ir.setContentsMargins(0, 0, 0, 0)
        ir.setSpacing(T.SPACE_SM)
        self._icon_preview = QLabel()
        self._icon_preview.setObjectName("iconPreview")
        self._icon_preview.setFixedSize(_ICON_PREVIEW_W, _ICON_PREVIEW_H)
        self._icon_preview.setAlignment(Qt.AlignCenter)
        ir.addWidget(self._icon_preview)
        self._icon_name = QLabel()
        self._icon_name.setObjectName("muted")
        ir.addWidget(self._icon_name, 1)
        choose = QPushButton("Choose icon…")
        choose.clicked.connect(self._choose_icon)
        ir.addWidget(choose)
        form.addRow("Icon", icon_row)

        self._priority = NoScrollSpinBox()
        self._priority.setRange(-1, 9999)
        self._priority.setSpecialValueText("(default)")
        self._priority.setValue(category.priority if (category and category.priority is not None) else -1)
        self._priority.setToolTip("Sort order in the decisions panel — higher sits nearer the top.")
        form.addRow("Panel priority", self._priority)

        v.addWidget(section_header("Visible when (optional)"))
        v.addWidget(hint("Conditions for the whole category tab to show at all."))
        self._visible = ConditionListWidget(
            items=(category.visible.items if (category and category.visible) else None),
            raw_lines=(category.visible.rawLines if (category and category.visible) else None),
            country_tag=model.project.countryTag,
            focus_ids=[f.id for f in model.project.focuses])
        v.addWidget(self._visible)

        v.addWidget(section_header("Raw category fields (optional)"))
        self._raw = QPlainTextEdit("\n".join(category.rawLines if category else []))
        self._raw.setMaximumHeight(T.TEXTAREA_SHORT)
        self._raw.setPlaceholderText("e.g.  visible_when_empty = yes")
        v.addWidget(self._raw)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save Category")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self._refresh_icon()

    def _on_accept(self) -> None:
        """Refuse to close with an empty ID — accepting would silently discard
        the authored category."""
        if not self._id.text().strip():
            QMessageBox.warning(self, "Missing ID",
                                "A category ID is required (e.g. MEX_reforms_category). "
                                "Fill in the ID field before saving.")
            return
        self.accept()

    def _on_title(self, text: str) -> None:
        if not self._id_edited:
            tag = (self._model.project.countryTag or "").strip().upper()
            slug = _slug(text)
            base = f"{tag}_{slug}" if tag and slug else slug
            self._id.setText(f"{base}_category" if base else "")

    def _choose_icon(self) -> None:
        dlg = IconPickerDialog(current=self._icon, parent=self,
                               sprites=provider().decision_category_sprites(),
                               title="Choose Category Icon")
        if dlg.exec() and dlg.selected_name():
            self._icon = dlg.selected_name()
            self._refresh_icon()

    def _refresh_icon(self) -> None:
        self._icon_name.setText(self._icon or "(no icon)")
        pm = provider().pixmap(self._icon) if self._icon else None
        if pm is not None and not pm.isNull():
            self._icon_preview.setPixmap(pm.scaled(
                _ICON_PREVIEW_W, _ICON_PREVIEW_H, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._icon_preview.clear()

    def result_category(self) -> DecisionCategory:
        items = self._visible.items()
        raw = self._visible.raw_lines()
        visible = AvailabilityRule(items=items, rawLines=raw) if (items or raw) else None
        return DecisionCategory(
            id=self._id.text().strip(),
            title=self._title.text().strip(),
            description=self._desc.toPlainText().strip(),
            icon=self._icon,
            priority=_optional_value(self._priority),
            visible=visible,
            rawLines=[ln for ln in self._raw.toPlainText().split("\n") if ln.strip()],
        )


class DecisionEditorDialog(QDialog):
    def __init__(self, model, decision: DecisionData = None, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._editing = decision is not None
        self.setWindowTitle("Edit Decision" if self._editing else "New Decision")
        self.resize(660, 780)
        self._built = False
        self._icon = decision.icon if decision else ""
        self._icon_data = (decision.iconData if decision else "") or ""
        self._id_edited = self._editing

        tag = model.project.countryTag
        self._country_tag = tag
        focus_ids = [f.id for f in model.project.focuses]
        idea_refs = [(i.id, f"{i.title or i.id} ({i.id})") for i in model.project.ideas]
        event_refs = [(e.id, f"{e.title or e.id} ({e.id})") for e in model.project.events]
        from .leader_options import build_leader_refs
        leader_refs = build_leader_refs(model.project)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        root.setSpacing(T.SPACE_MD)
        root.addWidget(panel_header("Decision"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_MD)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ----- identity -----
        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)

        self._title = QLineEdit(decision.title if decision else "")
        self._title.textChanged.connect(self._on_title)
        form.addRow("Title", self._title)
        self._id = QLineEdit(decision.id if decision else "")
        self._id.textChanged.connect(lambda *_: self._refresh_preview())
        self._id.textEdited.connect(lambda *_: setattr(self, "_id_edited", True))
        form.addRow("ID", self._id)
        self._desc = QPlainTextEdit(decision.description if decision else "")
        self._desc.setMaximumHeight(T.TEXTAREA_SHORT)
        form.addRow("Description", self._desc)

        # Category: this project's custom categories + every category the game
        # and MD already define (typable for anything else).
        cat_row = QWidget()
        ch = QHBoxLayout(cat_row)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(T.SPACE_SM)
        self._category = NoScrollComboBox()
        self._category.setEditable(True)
        self._populate_categories(decision.category if decision else "")
        self._category.currentTextChanged.connect(lambda *_: self._refresh_preview())
        ch.addWidget(self._category, 1)
        new_cat = QPushButton("New category…")
        new_cat.clicked.connect(self._new_category)
        ch.addWidget(new_cat)
        form.addRow("Category", cat_row)

        # Icon row: preview + name, then Choose (in-game grid) / Import (custom) / clear.
        icon_holder = QWidget()
        iv = QVBoxLayout(icon_holder)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(T.SPACE_XS)
        icon_row = QWidget()
        ir = QHBoxLayout(icon_row)
        ir.setContentsMargins(0, 0, 0, 0)
        ir.setSpacing(T.SPACE_SM)
        self._icon_preview = QLabel()
        self._icon_preview.setObjectName("iconPreview")
        self._icon_preview.setFixedSize(_ICON_PREVIEW_W, _ICON_PREVIEW_H)
        self._icon_preview.setAlignment(Qt.AlignCenter)
        ir.addWidget(self._icon_preview)
        self._icon_name = QLabel()
        self._icon_name.setObjectName("muted")
        ir.addWidget(self._icon_name, 1)
        choose = QPushButton("Choose icon…")
        choose.setToolTip("Pick an in-game decision icon from a visual grid.")
        choose.clicked.connect(self._choose_icon)
        ir.addWidget(choose)
        imp = QPushButton("Import…")
        imp.setToolTip(
            f"Import your own image as the decision icon. It's scaled to "
            f"{_DECISION_ICON_PX}×{_DECISION_ICON_PX} px and exported as .dds "
            f"(.png/.tga/.dds in).")
        imp.clicked.connect(self._import_icon)
        ir.addWidget(imp)
        self._icon_clear = QPushButton("×")
        self._icon_clear.setObjectName("deleteButton")
        self._icon_clear.setToolTip("Remove the custom imported icon (go back to the named icon).")
        self._icon_clear.setFixedWidth(T.ICON_BUTTON)
        self._icon_clear.clicked.connect(self._clear_custom_icon)
        ir.addWidget(self._icon_clear)
        iv.addWidget(icon_row)
        iv.addWidget(hint(
            f"HOI4 decision icons are small square images. Imported art is scaled "
            f"to {_DECISION_ICON_PX}×{_DECISION_ICON_PX} px and saved as .dds on "
            f"export — use a square source (.png/.tga/.dds) to avoid stretching."))
        form.addRow("Icon", icon_holder)

        # ----- cost / behaviour -----
        v.addWidget(section_header("Cost & behaviour"))
        bform = QFormLayout()
        bform.setSpacing(T.SPACE_SM)
        v.addLayout(bform)

        self._cost = NoScrollDoubleSpinBox()
        self._cost.setRange(-1, 9999)
        self._cost.setDecimals(0)
        self._cost.setSpecialValueText("(omit)")
        if decision is not None:
            self._cost.setValue(float(decision.cost) if decision.cost is not None else -1)
        else:
            self._cost.setValue(25)
        self._cost.setToolTip("Political power the player pays to take the decision. "
                              "(omit) leaves the field out — HOI4 then defaults to 0 PP.")
        self._cost.valueChanged.connect(lambda *_: self._refresh_preview())
        bform.addRow("Cost (PP)", self._cost)

        self._fire_once = QCheckBox("Can only ever be taken once (fire_only_once)")
        self._fire_once.setChecked(decision.fireOnlyOnce if decision else False)
        self._fire_once.toggled.connect(lambda *_: self._refresh_preview())
        bform.addRow(self._fire_once)

        self._ai = NoScrollDoubleSpinBox()
        self._ai.setRange(-1, 9999)
        self._ai.setDecimals(1)
        self._ai.setSpecialValueText("(default)")
        self._ai.setValue(float(decision.aiWillDo) if (decision and decision.aiWillDo is not None) else -1)
        self._ai.setToolTip("ai_will_do base — how eagerly the AI takes this decision.")
        self._ai.valueChanged.connect(lambda *_: self._refresh_preview())
        bform.addRow("AI priority", self._ai)

        self._priority = NoScrollSpinBox()
        self._priority.setRange(-1, 9999)
        self._priority.setSpecialValueText("(default)")
        self._priority.setValue(decision.priority if (decision and decision.priority is not None) else -1)
        self._priority.setToolTip("Sort order within the category — higher sits nearer the top.")
        self._priority.valueChanged.connect(lambda *_: self._refresh_preview())
        bform.addRow("Sort priority", self._priority)

        # ----- timers -----
        v.addWidget(section_header("Timers & missions"))
        tform = QFormLayout()
        tform.setSpacing(T.SPACE_SM)
        v.addLayout(tform)

        self._days_remove = _off_spin(100000, "The decision stays active this many days, "
                                              "then its Remove effect fires.")
        self._days_remove.setValue(decision.daysRemove if (decision and decision.daysRemove is not None) else -1)
        self._days_remove.valueChanged.connect(lambda *_: self._refresh_preview())
        tform.addRow("Active timer (days_remove)", self._days_remove)

        self._days_re_enable = _off_spin(100000, "Cooldown before the decision can be taken again.")
        self._days_re_enable.setValue(decision.daysReEnable if (decision and decision.daysReEnable is not None) else -1)
        self._days_re_enable.valueChanged.connect(lambda *_: self._refresh_preview())
        tform.addRow("Cooldown (days_re_enable)", self._days_re_enable)

        self._mission_timeout = _off_spin(100000, "Turns the decision into a mission with a "
                                                  "countdown; the Timeout effect fires if it expires.")
        self._mission_timeout.setValue(decision.daysMissionTimeout
                                       if (decision and decision.daysMissionTimeout is not None) else -1)
        self._mission_timeout.valueChanged.connect(lambda *_: self._refresh_preview())
        tform.addRow("Mission countdown (days)", self._mission_timeout)

        self._is_good = NoScrollComboBox()
        self._is_good.addItem("(default)", None)
        self._is_good.addItem("yes — good mission (green)", True)
        self._is_good.addItem("no — danger mission (red)", False)
        if decision and decision.isGood is not None:
            self._is_good.setCurrentIndex(1 if decision.isGood else 2)
        self._is_good.currentIndexChanged.connect(lambda *_: self._refresh_preview())
        tform.addRow("Mission tint (is_good)", self._is_good)

        # ----- triggers -----
        v.addWidget(section_header("Visible when (optional)"))
        v.addWidget(hint("Conditions for the decision to APPEAR in the panel."))
        self._visible = ConditionListWidget(
            items=(decision.visible.items if (decision and decision.visible) else None),
            raw_lines=(decision.visible.rawLines if (decision and decision.visible) else None),
            country_tag=tag, focus_ids=focus_ids, on_change=self._refresh_preview)
        v.addWidget(self._visible)

        v.addWidget(section_header("Available when (optional)"))
        v.addWidget(hint("Conditions to actually SELECT it (shown greyed-out otherwise)."))
        self._available = ConditionListWidget(
            items=(decision.available.items if (decision and decision.available) else None),
            raw_lines=(decision.available.rawLines if (decision and decision.available) else None),
            country_tag=tag, focus_ids=focus_ids, on_change=self._refresh_preview)
        v.addWidget(self._available)

        # ----- effects -----
        def _effects(reward) -> EffectListWidget:
            return EffectListWidget(
                items=(reward.items if reward else None),
                raw_lines=(reward.rawLines if reward else None),
                country_tag=tag, idea_refs=idea_refs, event_refs=event_refs,
                leader_refs=leader_refs, on_change=self._refresh_preview)

        v.addWidget(section_header("On select (complete effect)"))
        self._complete = _effects(decision.completeEffect if decision else None)
        v.addWidget(self._complete)

        v.addWidget(section_header("When the timer ends (remove effect)"))
        v.addWidget(hint("Fires after the active timer (days_remove) runs out."))
        self._remove = _effects(decision.removeEffect if decision else None)
        v.addWidget(self._remove)

        v.addWidget(section_header("If the mission expires (timeout effect)"))
        self._timeout = _effects(decision.timeoutEffect if decision else None)
        v.addWidget(self._timeout)

        # ----- active modifiers -----
        v.addWidget(section_header("Modifiers while active (optional)"))
        v.addWidget(hint("Country modifiers applied while the decision's timer is running."))
        self._mods_box = QVBoxLayout()
        self._mods_box.setSpacing(T.SPACE_XS)
        v.addLayout(self._mods_box)
        add_mod = QPushButton("+ Add modifier")
        add_mod.clicked.connect(lambda: self._add_mod_row("", 0.0))
        v.addWidget(add_mod)
        for key, val in self._parse_existing_mods(decision):
            self._add_mod_row(key, val)

        # ----- escape hatch -----
        v.addWidget(section_header("Raw decision fields (optional)"))
        v.addWidget(hint("Anything HOI4 supports that has no field above is exported "
                         "verbatim — e.g. targets, highlight_states, custom_cost_trigger, "
                         "on_map_mode, war_with_on_remove."))
        self._raw = QPlainTextEdit("\n".join(decision.rawLines if decision else []))
        self._raw.setMaximumHeight(T.TEXTAREA_MEDIUM)
        self._raw.textChanged.connect(self._refresh_preview)
        v.addWidget(self._raw)

        # ----- live preview -----
        v.addWidget(section_header("Generated decision"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setObjectName("scriptPreview")
        self._preview.setMinimumHeight(140)
        v.addWidget(self._preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save Decision")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._built = True
        self._refresh_icon()
        self._refresh_preview()

    # ----- categories -----
    def _populate_categories(self, current: str) -> None:
        cb = self._category
        cb.blockSignals(True)
        cb.clear()
        all_ids = []
        custom = [c.id for c in self._model.project.decisionCategories]
        if custom:
            cb.addItem("— Your categories —")
            cb.model().item(cb.count() - 1).setEnabled(False)
            for cid in custom:
                cb.addItem(cid)
                all_ids.append(cid)
        md = tech_provider().md_decision_categories()
        if md:
            cb.addItem("— Existing game/MD categories —")
            cb.model().item(cb.count() - 1).setEnabled(False)
            for cid in md:
                cb.addItem(cid)
                all_ids.append(cid)
        cb.setCurrentText(current)
        if all_ids:
            from PySide6.QtWidgets import QCompleter
            comp = QCompleter(sorted(set(all_ids)), cb)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            cb.setCompleter(comp)
        cb.setToolTip("Pick one of your categories, drop it into an existing MD "
                      "category, or type any category id.")
        cb.blockSignals(False)

    def _new_category(self) -> None:
        dlg = DecisionCategoryEditorDialog(self._model, parent=self)
        if not dlg.exec():
            return
        category = dlg.result_category()
        if not category.id:
            return
        final = self._model.add_decision_category(category)
        self._populate_categories(final)
        self._refresh_preview()

    # ----- title/id/icon -----
    def _on_title(self, text: str) -> None:
        if not self._id_edited:
            tag = (self._model.project.countryTag or "").strip().upper()
            slug = _slug(text)
            self._id.setText(f"{tag}_{slug}" if tag and slug else slug)
        self._refresh_preview()

    def _choose_icon(self) -> None:
        dlg = IconPickerDialog(current=self._icon, parent=self,
                               sprites=provider().decision_icon_sprites(),
                               title="Choose Decision Icon")
        if dlg.exec() and dlg.selected_name():
            self._icon = dlg.selected_name()
            self._icon_data = ""  # a chosen sprite replaces any custom image
            self._refresh_icon()
            self._refresh_preview()

    def _import_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import decision icon — square, scaled to {_DECISION_ICON_PX}×"
            f"{_DECISION_ICON_PX} px (.png/.tga/.dds)",
            "", _IMG_FILTER)
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Import failed",
                                "Couldn't read that image — use a .png, .tga, or .dds.")
            return
        self._icon_data = _scaled_b64_png(img, _DECISION_ICON_PX, _DECISION_ICON_PX)
        self._refresh_icon()
        self._refresh_preview()

    def _clear_custom_icon(self) -> None:
        if not self._icon_data:
            return
        self._icon_data = ""
        self._refresh_icon()
        self._refresh_preview()

    def _refresh_icon(self) -> None:
        self._icon_clear.setVisible(bool(self._icon_data))
        if self._icon_data:
            self._icon_name.setText("(custom imported icon)")
            img = _qimage_from_b64(self._icon_data)
            pm = QPixmap.fromImage(img) if img is not None else None
        else:
            self._icon_name.setText(self._icon or "(no icon)")
            pm = provider().pixmap(self._icon) if self._icon else None
        if pm is not None and not pm.isNull():
            self._icon_preview.setPixmap(pm.scaled(
                _ICON_PREVIEW_W, _ICON_PREVIEW_H, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._icon_preview.clear()

    # ----- modifiers -----
    def _add_mod_row(self, key: str, value) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(T.SPACE_SM)
        combo = _build_modifier_combo(key)
        combo.currentTextChanged.connect(lambda *_: self._refresh_preview())
        spin = NoScrollDoubleSpinBox()
        spin.setRange(-1e6, 1e6)
        spin.setDecimals(4)
        spin.setSingleStep(0.005)
        try:
            spin.setValue(float(value))
        except (TypeError, ValueError):
            spin.setValue(0.0)
        spin.valueChanged.connect(lambda *_: self._refresh_preview())
        x = QPushButton("×")
        x.setObjectName("deleteButton")
        x.setToolTip("Remove modifier")
        x.setFixedWidth(T.ICON_BUTTON)
        h.addWidget(combo, 1)
        h.addWidget(spin)
        h.addWidget(x)
        row._combo = combo  # type: ignore[attr-defined]
        row._spin = spin    # type: ignore[attr-defined]
        x.clicked.connect(lambda: self._remove_mod_row(row))
        self._mods_box.addWidget(row)
        self._refresh_preview()  # signals above connect after the seed values

    def _remove_mod_row(self, row) -> None:
        self._mods_box.removeWidget(row)
        row.deleteLater()
        self._refresh_preview()

    def _mod_rows(self):
        for i in range(self._mods_box.count()):
            w = self._mods_box.itemAt(i).widget()
            if w is not None:
                yield w

    @staticmethod
    def _parse_existing_mods(decision):
        out = []
        if not decision:
            return out
        for line in (decision.modifierRawLines or []):
            s = line.strip()
            if s.startswith("modifier") or s in ("{", "}"):
                continue
            m = _MOD_LINE.match(s)
            if m:
                out.append((m.group(1), m.group(2)))
        return out

    # ----- preview -----
    def _refresh_preview(self, *args) -> None:
        if not self._built:
            return
        from core.exporters import export_decisions
        try:
            proj = FocusForgeProject(
                countryTag=self._country_tag,
                decisions=[self.result_decision()],
            )
            self._preview.setPlainText(export_decisions(proj).strip("\n"))
        except Exception as exc:  # never let a preview error block editing
            self._preview.setPlainText(f"(preview unavailable: {exc})")

    # ----- accept -----
    def _on_accept(self) -> None:
        """Refuse to close with an empty ID — accepting would silently discard
        the authored decision."""
        if not self._id.text().strip():
            QMessageBox.warning(self, "Missing ID",
                                "A decision ID is required (e.g. MEX_land_reform). "
                                "Fill in the ID field before saving.")
            return
        self.accept()

    # ----- result -----
    def result_decision(self) -> DecisionData:
        def _rule(widget):
            items = widget.items()
            raw = widget.raw_lines()
            return AvailabilityRule(items=items, rawLines=raw) if (items or raw) else None

        def _reward(widget):
            items = widget.items()
            raw = widget.raw_lines()
            return CompletionReward(items=items, rawLines=raw) if (items or raw) else None

        mods = []
        for row in self._mod_rows():
            key = row._combo.currentText().strip()
            if key:
                mods.append((key, row._spin.value()))
        modifier_lines = []
        if mods:
            modifier_lines = ["modifier = {"]
            modifier_lines += [f"\t{k} = {format_number(v)}" for k, v in mods]
            modifier_lines.append("}")

        return DecisionData(
            id=self._id.text().strip(),
            title=self._title.text().strip(),
            description=self._desc.toPlainText().strip(),
            category=self._category.currentText().strip().strip("— ").strip(),
            icon=self._icon,
            iconData=self._icon_data,
            cost=(None if self._cost.value() == self._cost.minimum()
                  else float(self._cost.value())),
            fireOnlyOnce=self._fire_once.isChecked(),
            isGood=self._is_good.currentData(),
            daysRemove=_optional_value(self._days_remove),
            daysReEnable=_optional_value(self._days_re_enable),
            daysMissionTimeout=_optional_value(self._mission_timeout),
            aiWillDo=(None if self._ai.value() == self._ai.minimum() else float(self._ai.value())),
            priority=_optional_value(self._priority),
            visible=_rule(self._visible),
            available=_rule(self._available),
            completeEffect=_reward(self._complete),
            removeEffect=_reward(self._remove),
            timeoutEffect=_reward(self._timeout),
            modifierRawLines=modifier_lines,
            rawLines=[ln for ln in self._raw.toPlainText().split("\n") if ln.strip()],
        )
