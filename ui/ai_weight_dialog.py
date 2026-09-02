"""Dialog to author a focus's ``ai_will_do``: the base weight plus conditional
``modifier = { factor/add … trigger }`` blocks.

Every real Millennium Dawn focus carries these — they are what makes an AI
country walk its tree in a sensible order (historical openings first, the
non-historical side of a fork never, war paths only when war support is high).
The triggers reuse the availability condition presets, so the same cards and
raw-line box the user knows from the Availability editor appear here.

The dialog edits copies and writes back on OK only, as one undo step.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.exporters import ai_will_do_lines
from core.types import AiModifier, AvailabilityRule, FocusNodeData

from . import theme as T
from .no_scroll import NoScrollComboBox
from .preset_list import ConditionListWidget
from .widgets import hint, panel_header, section_header

# Common shapes, offered as one-click starting points.
_TEMPLATES = [
    ("Never take this (factor 0)", 0.0, "factor", [], []),
    ("Only after a date…", 0.0, "factor", [], ["NOT = { date > 2006.1.1 }"]),
    ("Prefer early (×5 before a date)", 5.0, "factor", [], ["date < 2003.1.1"]),
    ("Skip while at war", 0.0, "factor", [{"kind": "at_war", "params": {}}], []),
    ("Only with a country flag", 0.0, "factor",
     [{"kind": "lacks_country_flag", "params": {"flag": "MY_FLAG"}}], []),
    ("Only under a government", 0.0, "factor",
     [{"kind": "government", "params": {"ideology": "democratic"}}], []),
]


class _ModifierRow(QFrame):
    """One modifier: weight kind + value, then its trigger (condition list)."""

    def __init__(self, mod: AiModifier, *, country_tag: str, focus_ids, on_change, on_delete,
                 parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._on_change = on_change
        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_SM)
        v.setSpacing(T.SPACE_SM)

        top = QHBoxLayout()
        top.setSpacing(T.SPACE_SM)
        self._kind = NoScrollComboBox()
        self._kind.addItem("factor ×", "factor")
        self._kind.addItem("add +", "add")
        self._value = QDoubleSpinBox()
        self._value.setRange(-9999, 9999)
        self._value.setDecimals(2)
        if mod.factor is not None:
            self._kind.setCurrentIndex(0)
            self._value.setValue(float(mod.factor))
        elif mod.add is not None:
            self._kind.setCurrentIndex(1)
            self._value.setValue(float(mod.add))
        else:
            self._value.setValue(1.0)
        self._kind.setToolTip("factor multiplies the running weight (0 = never); add shifts it.")
        top.addWidget(QLabel("Weight"))
        top.addWidget(self._kind)
        top.addWidget(self._value)
        top.addStretch(1)
        rm = QPushButton("Remove")
        rm.clicked.connect(lambda: on_delete(self))
        top.addWidget(rm)
        v.addLayout(top)

        v.addWidget(QLabel("When (trigger):"))
        trig = mod.trigger
        self._conditions = ConditionListWidget(
            items=(trig.items if trig else None),
            raw_lines=(trig.rawLines if trig else None),
            country_tag=country_tag, focus_ids=focus_ids, on_change=on_change)
        v.addWidget(self._conditions)
        self._kind.currentIndexChanged.connect(lambda *_: on_change())
        self._value.valueChanged.connect(lambda *_: on_change())

    def to_modifier(self) -> AiModifier:
        items = self._conditions.items()
        raw = self._conditions.raw_lines()
        trigger = AvailabilityRule(items=items, rawLines=raw) if (items or raw) else None
        value = float(self._value.value())
        if self._kind.currentData() == "add":
            return AiModifier(factor=None, add=value, trigger=trigger)
        return AiModifier(factor=value, add=None, trigger=trigger)


class AiWeightDialog(QDialog):
    def __init__(self, focus: FocusNodeData, *, country_tag: str = "", focus_ids=(),
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"AI weight — {focus.id}")
        self.resize(640, 720)
        self._country_tag = country_tag
        self._focus_ids = list(focus_ids or [])
        self._rows: list = []

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("AI Weight (ai_will_do)"))
        v.addWidget(hint(
            "How eagerly an AI country picks this focus. The base is the starting "
            "weight (10 = HOI4 default, 0 = never). Each modifier multiplies (factor) "
            "or shifts (add) that weight while its trigger holds — this is how real "
            "MD trees steer the AI down the historical path."))

        base_row = QHBoxLayout()
        base_row.setSpacing(T.SPACE_SM)
        base_row.addWidget(QLabel("Base weight"))
        self._base = QDoubleSpinBox()
        self._base.setRange(0, 9999)
        self._base.setDecimals(1)
        self._base.setValue(10.0 if focus.aiWillDo is None else float(focus.aiWillDo))
        self._base.valueChanged.connect(lambda *_: self._refresh_preview())
        base_row.addWidget(self._base)
        base_row.addStretch(1)
        v.addLayout(base_row)

        v.addWidget(section_header("MODIFIERS"))
        add_row = QHBoxLayout()
        add_row.setSpacing(T.SPACE_SM)
        self._template = NoScrollComboBox()
        self._template.addItem("Add modifier…", None)
        self._template.addItem("Blank modifier", "blank")
        for i, (label, *_rest) in enumerate(_TEMPLATES):
            self._template.addItem(label, i)
        self._template.activated.connect(self._on_add_template)
        add_row.addWidget(self._template, 1)
        v.addLayout(add_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self._rows_box = QVBoxLayout(holder)
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(T.SPACE_SM)
        self._rows_box.addStretch(1)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

        v.addWidget(QLabel("Generated ai_will_do block"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(T.TEXTAREA_TALL)
        v.addWidget(self._preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        for mod in copy.deepcopy(list(focus.aiModifiers or [])):
            self._add_row(mod)
        self._refresh_preview()

    # ----- rows -----
    def _add_row(self, mod: AiModifier) -> None:
        row = _ModifierRow(mod, country_tag=self._country_tag, focus_ids=self._focus_ids,
                           on_change=self._refresh_preview, on_delete=self._remove_row)
        self._rows.append(row)
        self._rows_box.insertWidget(self._rows_box.count() - 1, row)
        self._refresh_preview()

    def _remove_row(self, row: _ModifierRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
        row.hide()
        row.setParent(None)
        row.deleteLater()
        self._refresh_preview()

    def _on_add_template(self, idx: int) -> None:
        data = self._template.itemData(idx)
        self._template.setCurrentIndex(0)
        if data is None:
            return
        if data == "blank":
            self._add_row(AiModifier(factor=1.0))
            return
        _label, value, kind, items, raw = _TEMPLATES[int(data)]
        from core.types import RewardItem
        trigger = AvailabilityRule(
            items=[RewardItem(kind=i["kind"], params=dict(i["params"]), enabled=True) for i in items] or None,
            rawLines=list(raw) or None) if (items or raw) else None
        self._add_row(AiModifier(factor=value if kind == "factor" else None,
                                 add=value if kind == "add" else None, trigger=trigger))

    # ----- data out -----
    def base(self):
        """None when left at the HOI4 default (10), so untouched focuses keep
        exporting byte-identically."""
        val = float(self._base.value())
        return None if val == 10 else val

    def modifiers(self):
        mods = [r.to_modifier() for r in self._rows]
        return mods or None

    def _refresh_preview(self) -> None:
        probe = FocusNodeData(id="x", aiWillDo=self.base(), aiModifiers=self.modifiers())
        self._preview.setPlainText("\n".join(ai_will_do_lines(probe)))
