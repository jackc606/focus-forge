"""Reusable preset-list widgets: a preset picker + dynamic item cards + a raw
escape-hatch textarea, operating on a plain list of ``RewardItem`` plus raw lines.

Unlike ``RewardEditor`` / ``AvailabilityEditor`` (which are bound to a focus and
push every change straight into the model), these are decoupled — they own a local
draft list and fire an ``on_change`` callback so a host dialog can refresh a
preview and persist on its own terms. The event editor composes them for option
effects, option triggers, and the event-level fire trigger. The item cards are
the same ``PresetItemCard`` the focus editors use.
"""
from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from core.availability_presets import (
    AVAILABILITY_PRESET_GROUPS,
    build_availability_item_lines,
    create_availability_item,
    get_availability_preset,
)
from core.reward_presets import (
    REWARD_PRESET_GROUPS,
    build_reward_item_lines,
    create_reward_item,
    get_reward_preset,
)
from core.types import RewardItem

from . import theme as T
from .item_card import PresetItemCard
from .no_scroll import NoScrollComboBox as QComboBox
from .param_widgets import make_param_widget


class _PresetListBase(QWidget):
    _ADD_LABEL = "Add…"
    _RAW_PLACEHOLDER = "Raw lines (one per line)"

    def __init__(self, items=None, raw_lines=None, *, on_change=None, parent=None) -> None:
        super().__init__(parent)
        self._items = list(items or [])
        self._raw = list(raw_lines or [])
        self._on_change = on_change

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_SM)

        self._combo = QComboBox()
        self._combo.addItem(self._ADD_LABEL, None)
        for group, presets in self._groups():
            self._combo.insertSeparator(self._combo.count())
            self._combo.addItem(f"-- {group} --", None)
            self._combo.model().item(self._combo.count() - 1).setEnabled(False)
            for preset in presets:
                self._combo.addItem(f"  {preset.label}", preset.kind)
        self._combo.activated.connect(self._on_add)
        v.addWidget(self._combo)

        self._items_box = QVBoxLayout()
        self._items_box.setSpacing(T.SPACE_SM)
        v.addLayout(self._items_box)

        self._raw_edit = QPlainTextEdit()
        self._raw_edit.setMaximumHeight(T.TEXTAREA_SHORT)
        self._raw_edit.setPlaceholderText(self._RAW_PLACEHOLDER)
        self._raw_edit.setPlainText("\n".join(self._raw))
        self._raw_edit.textChanged.connect(self._commit_raw)
        v.addWidget(self._raw_edit)

        self._render()

    # ----- subclass hooks -----
    def _groups(self):
        raise NotImplementedError

    def _create(self, kind):
        raise NotImplementedError

    def _make_card(self, index, item):
        raise NotImplementedError

    # ----- data out -----
    def items(self):
        return list(self._items) if self._items else None

    def raw_lines(self):
        return list(self._raw) if self._raw else None

    # ----- internals -----
    def _changed(self) -> None:
        if self._on_change:
            self._on_change()

    def _render(self) -> None:
        while self._items_box.count():
            child = self._items_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        for index, item in enumerate(self._items):
            card = self._make_card(index, item)
            if hasattr(card, "set_preview_visible"):
                card.set_preview_visible(True)
            self._items_box.addWidget(card)

    def _on_add(self, idx: int) -> None:
        kind = self._combo.itemData(idx)
        self._combo.setCurrentIndex(0)
        if not kind:
            return
        d = self._create(kind)
        self._items.append(RewardItem(kind=d["kind"], enabled=d["enabled"], params=d["params"]))
        self._render()
        self._changed()

    def _on_item_changed(self) -> None:
        self._changed()

    def _on_item_deleted(self, index: int) -> None:
        if 0 <= index < len(self._items):
            del self._items[index]
            self._render()
            self._changed()

    def _commit_raw(self) -> None:
        self._raw = [ln for ln in self._raw_edit.toPlainText().split("\n") if ln.strip()]
        self._changed()


class EffectListWidget(_PresetListBase):
    """Structured effect picker (reuses the focus *reward* presets)."""

    _ADD_LABEL = "Add effect…"
    _RAW_PLACEHOLDER = "Raw effect lines (one HOI4 effect per line)"

    def __init__(self, items=None, raw_lines=None, *, country_tag: str = "",
                 idea_refs=(), event_refs=(), leader_refs=(), on_change=None, parent=None) -> None:
        self._country_tag = country_tag
        self._idea_refs = list(idea_refs or [])
        self._event_refs = list(event_refs or [])
        self._leader_refs = list(leader_refs or [])
        super().__init__(items, raw_lines, on_change=on_change, parent=parent)

    def _groups(self):
        return REWARD_PRESET_GROUPS

    def _create(self, kind):
        return create_reward_item(kind)

    def _make_card(self, index, item):
        return PresetItemCard(
            index, item, get_reward_preset(item.kind),
            on_change=self._on_item_changed, on_delete=self._on_item_deleted,
            build_lines=build_reward_item_lines, empty_text="(no output)",
            make_widget=lambda param, current, set_value: make_param_widget(
                param, current, set_value, country_tag=self._country_tag,
                idea_refs=self._idea_refs, event_refs=self._event_refs,
                leader_refs=self._leader_refs))


class ConditionListWidget(_PresetListBase):
    """Structured trigger picker (reuses the focus *availability* presets)."""

    _ADD_LABEL = "Add condition…"
    _RAW_PLACEHOLDER = "Raw trigger lines (one per line)"

    def __init__(self, items=None, raw_lines=None, *, country_tag: str = "",
                 focus_ids=(), on_change=None, parent=None) -> None:
        self._country_tag = country_tag
        self._focus_ids = list(focus_ids or [])
        super().__init__(items, raw_lines, on_change=on_change, parent=parent)

    def _groups(self):
        return AVAILABILITY_PRESET_GROUPS

    def _create(self, kind):
        return create_availability_item(kind)

    def _make_card(self, index, item):
        return PresetItemCard(
            index, item, get_availability_preset(item.kind),
            on_change=self._on_item_changed, on_delete=self._on_item_deleted,
            build_lines=build_availability_item_lines, empty_text="(disabled)",
            make_widget=lambda param, current, set_value: make_param_widget(
                param, current, set_value, country_tag=self._country_tag,
                focus_ids=self._focus_ids))
