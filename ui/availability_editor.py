"""Availability editor: builds a focus's `available = { }` block from condition
presets + raw lines. Mirrors the reward editor."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
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

from . import theme as T
from .item_card import PresetItemCard
from .param_widgets import make_param_widget


def availability_preview_lines(rule: AvailabilityRule) -> list:
    """The exporter's assembly is the single source of truth — the preview must
    never drift from what actually lands in the focus file."""
    from core.exporters import _availability_inner_lines
    return _availability_inner_lines(rule)


class AvailabilityEditor(QWidget):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._focus_id = ""
        self._suspend = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_SM)

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
        self._items_box.setSpacing(T.SPACE_SM)
        v.addLayout(self._items_box)

        self._raw_label = QLabel("Raw Trigger Lines (one per line)")
        v.addWidget(self._raw_label)
        self._raw = QPlainTextEdit()
        self._raw.setMaximumHeight(T.TEXTAREA_SHORT)
        self._raw.textChanged.connect(self._commit_raw)
        v.addWidget(self._raw)

        self._preview_label = QLabel("Generated available block")
        v.addWidget(self._preview_label)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(T.TEXTAREA_TALL)
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
            card = PresetItemCard(
                index, item, get_availability_preset(item.kind),
                on_change=self._on_item_changed, on_delete=self._on_item_deleted,
                build_lines=build_availability_item_lines, empty_text="(disabled)",
                make_widget=lambda param, current, set_value: make_param_widget(
                    param, current, set_value,
                    country_tag=tag, focus_ids=focus_ids))
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
            if isinstance(card, PresetItemCard):
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
