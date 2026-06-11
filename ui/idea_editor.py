"""Dialog to author a HOI4/MD idea (national spirit): id/title/description, an
idea-icon picker, and modifier rows. Produces an IdeaData."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.reward_presets import format_number
from core.types import IdeaData

from . import theme as T
from .icon_picker import IconPickerDialog
from .icon_provider import provider
from .no_scroll import NoScrollComboBox, NoScrollDoubleSpinBox
from .tech_provider import tech_provider
from .widgets import hint, panel_header, section_header

_MOD_LINE = re.compile(r"([A-Za-z0-9_]+)\s*=\s*(-?[\d.]+)")

# HOI4 idea icons are roughly 65:55 — preview at a small multiple of that ratio.
_ICON_PREVIEW_W, _ICON_PREVIEW_H = 40, 34


def _build_modifier_combo(current: str) -> QComboBox:
    """Editable, searchable combo of every MD/HOI4 idea modifier grouped by
    functional theme. Item text is the BARE modifier name (no indent) so the
    caller's ``currentText()`` stays clean; group headers are disabled rows."""
    cb = NoScrollComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    cb.setMaxVisibleItems(24)
    all_names = []
    for label, names in tech_provider().idea_modifier_groups():
        cb.addItem(f"— {label} —")
        cb.model().item(cb.count() - 1).setEnabled(False)
        for n in names:
            cb.addItem(n)
            all_names.append(n)
    cb.setCurrentText(current)
    if all_names:
        comp = QCompleter(sorted(set(all_names)), cb)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        cb.setCompleter(comp)
    return cb


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


class IdeaEditorDialog(QDialog):
    def __init__(self, model, idea: IdeaData = None, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._editing = idea is not None
        self.setWindowTitle("Edit Idea" if self._editing else "New Idea")
        self.resize(520, 0)
        self._picture = idea.picture if idea else ""
        self._id_edited = self._editing

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Idea / National Spirit"))

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)

        self._title = QLineEdit(idea.title if idea else "")
        self._title.textChanged.connect(self._on_title)
        form.addRow("Title", self._title)

        self._id = QLineEdit(idea.id if idea else "")
        self._id.textEdited.connect(lambda *_: setattr(self, "_id_edited", True))
        form.addRow("ID", self._id)

        self._desc = QPlainTextEdit(idea.description if idea else "")
        self._desc.setMaximumHeight(T.TEXTAREA_MEDIUM)
        form.addRow("Description", self._desc)

        # Icon row
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

        # Modifiers
        v.addWidget(section_header("Modifiers"))
        v.addWidget(hint("Each row becomes a line in the idea's modifier block."))
        self._mods_box = QVBoxLayout()
        self._mods_box.setSpacing(4)
        v.addLayout(self._mods_box)
        add_mod = QPushButton("+ Add modifier")
        add_mod.clicked.connect(lambda: self._add_mod_row("", 0.0))
        v.addWidget(add_mod)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Save Idea")
        self._buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        v.addWidget(self._buttons)

        # seed existing modifiers when editing
        for key, val in self._parse_existing_mods(idea):
            self._add_mod_row(key, val)
        self._refresh_icon()

    # ----- title/id -----
    def _on_title(self, text: str) -> None:
        if not self._id_edited:
            tag = (self._model.project.countryTag or "").strip().upper()
            slug = _slug(text)
            self._id.setText(f"{tag}_{slug}" if tag and slug else slug)

    # ----- icon -----
    def _choose_icon(self) -> None:
        dlg = IconPickerDialog(current=self._picture, parent=self,
                               sprites=provider().idea_sprites(), title="Choose Idea Icon")
        if dlg.exec() and dlg.selected_name():
            self._picture = dlg.selected_name()
            self._refresh_icon()

    def _refresh_icon(self) -> None:
        self._icon_name.setText(self._picture or "(no icon)")
        pm = provider().pixmap(self._picture) if self._picture else None
        if pm is not None and not pm.isNull():
            self._icon_preview.setPixmap(pm.scaled(_ICON_PREVIEW_W, _ICON_PREVIEW_H,
                                                   Qt.KeepAspectRatio,
                                                   Qt.SmoothTransformation))
        else:
            self._icon_preview.clear()

    # ----- modifiers -----
    def _add_mod_row(self, key: str, value) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(T.SPACE_SM)
        combo = _build_modifier_combo(key)
        spin = NoScrollDoubleSpinBox()
        spin.setRange(-1e6, 1e6)
        spin.setDecimals(4)
        spin.setSingleStep(0.05)
        try:
            spin.setValue(float(value))
        except (TypeError, ValueError):
            spin.setValue(0.0)
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

    def _remove_mod_row(self, row) -> None:
        self._mods_box.removeWidget(row)
        row.deleteLater()

    def _mod_rows(self):
        for i in range(self._mods_box.count()):
            w = self._mods_box.itemAt(i).widget()
            if w is not None:
                yield w

    @staticmethod
    def _parse_existing_mods(idea):
        out = []
        if not idea:
            return out
        for line in (idea.modifierRawLines or []):
            s = line.strip()
            if s.startswith("modifier") or s in ("{", "}"):
                continue
            m = _MOD_LINE.match(s)
            if m:
                out.append((m.group(1), m.group(2)))
        return out

    # ----- result -----
    def result_idea(self) -> IdeaData:
        rows = []
        for row in self._mod_rows():
            key = row._combo.currentText().strip()
            if key:
                rows.append((key, row._spin.value()))
        modifier_lines = []
        if rows:
            modifier_lines = ["modifier = {"]
            modifier_lines += [f"\t{k} = {format_number(v)}" for k, v in rows]
            modifier_lines.append("}")
        return IdeaData(
            id=self._id.text().strip(),
            title=self._title.text().strip(),
            description=self._desc.toPlainText().strip(),
            picture=self._picture,
            modifierRawLines=modifier_lines,
        )
