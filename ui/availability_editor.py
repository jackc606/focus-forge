"""Availability editor: builds a focus's `available = { }` block from condition
presets + raw lines. Mirrors the reward editor."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .no_scroll import NoScrollComboBox as QComboBox

from core.availability_presets import (
    AVAILABILITY_PRESET_GROUPS,
    build_availability_item_lines,
    create_availability_item,
    get_availability_preset,
)
from core.types import AvailabilityRule, RewardItem

from .param_widgets import make_param_widget


def availability_preview_lines(rule: AvailabilityRule) -> list:
    lines: list = []
    if rule is None:
        return lines
    for c in (rule.completedFocuses or []):
        lines.append(f"has_completed_focus = {c}")
    for f in (rule.flagsRequired or []):
        lines.append(f"has_country_flag = {f}")
    for f in (rule.flagsBlocked or []):
        lines.append(f"NOT = {{ has_country_flag = {f} }}")
    for item in (rule.items or []):
        lines.extend(build_availability_item_lines(item))
    for raw in (rule.rawLines or []):
        lines.append(raw)
    return lines


class _AvailabilityItemCard(QFrame):
    def __init__(self, index, item, on_change, on_delete, *, country_tag, focus_ids) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._index = index
        self._item = item
        self._on_change = on_change
        self._on_delete = on_delete
        preset = get_availability_preset(item.kind)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>{preset.label if preset else item.kind}</b>"))
        header.addStretch(1)
        self._enabled_chk = QCheckBox("enabled")
        self._enabled_chk.setChecked(item.enabled is not False)
        self._enabled_chk.toggled.connect(self._toggle_enabled)
        header.addWidget(self._enabled_chk)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(lambda: self._on_delete(self._index))
        header.addWidget(del_btn)
        v.addLayout(header)

        if preset and preset.description:
            desc = QLabel(preset.description)
            desc.setObjectName("muted")
            desc.setWordWrap(True)
            v.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(6)
        v.addLayout(form)
        if preset:
            for param in preset.params:
                widget = make_param_widget(
                    param, item.params.get(param.key, param.defaultValue),
                    lambda val, k=param.key: self._set_param(k, val),
                    country_tag=country_tag, focus_ids=focus_ids)
                widget.setToolTip(param.helpText or "")
                form.addRow(param.label, widget)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(64)
        v.addWidget(self._preview)
        self._refresh_preview()

    def set_preview_visible(self, show: bool) -> None:
        self._preview.setVisible(bool(show))

    def _set_param(self, key, value) -> None:
        self._item.params[key] = value
        self._refresh_preview()
        self._on_change()

    def _toggle_enabled(self, checked) -> None:
        self._item.enabled = checked
        self._refresh_preview()
        self._on_change()

    def _refresh_preview(self) -> None:
        lines = build_availability_item_lines(self._item)
        self._preview.setPlainText("\n".join(lines) if lines else "(disabled)")


class AvailabilityEditor(QWidget):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._focus_id = ""
        self._suspend = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self._combo = QComboBox()
        self._combo.addItem("Add condition…", None)
        for group, presets in AVAILABILITY_PRESET_GROUPS:
            self._combo.insertSeparator(self._combo.count())
            self._combo.addItem(f"-- {group} --", None)
            self._combo.model().item(self._combo.count() - 1).setEnabled(False)
            for preset in presets:
                self._combo.addItem(f"  {preset.label}", preset.kind)
        self._combo.activated.connect(self._on_add_preset)
        v.addWidget(self._combo)

        self._items_box = QVBoxLayout()
        self._items_box.setSpacing(8)
        v.addLayout(self._items_box)

        self._raw_label = QLabel("Raw Trigger Lines (one per line)")
        v.addWidget(self._raw_label)
        self._raw = QPlainTextEdit()
        self._raw.setMaximumHeight(64)
        self._raw.textChanged.connect(self._commit_raw)
        v.addWidget(self._raw)

        self._preview_label = QLabel("Generated available block")
        v.addWidget(self._preview_label)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(110)
        v.addWidget(self._preview)

        # Toggled together with the reward editor from the inspector; hidden by default.
        self._script_visible = False
        self._apply_script_visibility()

    def set_focus_id(self, focus_id: str) -> None:
        self._focus_id = focus_id or ""
        self._render()

    def _focus(self):
        return self._model.find_focus(self._focus_id)

    def _avail(self) -> AvailabilityRule:
        focus = self._focus()
        if focus.available is None:
            focus.available = AvailabilityRule()
        return focus.available

    def _render(self) -> None:
        self._suspend = True
        while self._items_box.count():
            child = self._items_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        focus = self._focus()
        if not focus:
            self._suspend = False
            return
        rule = focus.available or AvailabilityRule()
        focus_ids = [f.id for f in self._model.project.focuses if f.id != self._focus_id]
        tag = self._model.project.countryTag
        for index, item in enumerate(rule.items or []):
            card = _AvailabilityItemCard(index, item, self._on_item_changed,
                                         self._on_item_deleted,
                                         country_tag=tag, focus_ids=focus_ids)
            self._items_box.addWidget(card)
        self._raw.blockSignals(True)
        self._raw.setPlainText("\n".join(rule.rawLines or []))
        self._raw.blockSignals(False)
        self._refresh_preview()
        self._apply_script_visibility()  # new cards follow the toggle
        self._suspend = False

    # ----- raw/preview visibility (driven by the inspector checkbox) -----
    def set_script_visible(self, show: bool) -> None:
        self._script_visible = bool(show)
        self._apply_script_visibility()

    def _apply_script_visibility(self) -> None:
        for w in (self._raw_label, self._raw, self._preview_label, self._preview):
            w.setVisible(self._script_visible)
        for i in range(self._items_box.count()):
            card = self._items_box.itemAt(i).widget()
            if isinstance(card, _AvailabilityItemCard):
                card.set_preview_visible(self._script_visible)

    def _on_add_preset(self, idx: int) -> None:
        kind = self._combo.itemData(idx)
        if not kind or not self._focus():
            self._combo.setCurrentIndex(0)
            return
        rule = self._avail()
        if rule.items is None:
            rule.items = []
        d = create_availability_item(kind)
        rule.items.append(RewardItem(kind=d["kind"], enabled=d["enabled"], params=d["params"]))
        self._combo.setCurrentIndex(0)
        self._render()
        self._model.notify_changed()

    def _on_item_changed(self) -> None:
        self._refresh_preview()
        self._model.notify_changed()

    def _on_item_deleted(self, index: int) -> None:
        focus = self._focus()
        if not focus or not focus.available or not focus.available.items:
            return
        del focus.available.items[index]
        if not focus.available.items:
            focus.available.items = None
        self._render()
        self._model.notify_changed()

    def _commit_raw(self) -> None:
        if self._suspend:
            return
        focus = self._focus()
        if not focus:
            return
        rule = self._avail()
        lines = [ln for ln in self._raw.toPlainText().split("\n") if ln.strip()]
        rule.rawLines = lines or None
        self._refresh_preview()
        self._model.notify_changed()

    def _refresh_preview(self) -> None:
        focus = self._focus()
        lines = availability_preview_lines(focus.available) if focus else []
        if lines:
            body = "\n".join(f"\t{ln}" for ln in lines)
            self._preview.setPlainText("available = {\n" + body + "\n}")
        else:
            self._preview.setPlainText("(none)")
