"""Reward editor: simple fields + preset picker + per-item dynamic forms + raw lines + preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .no_scroll import NoScrollComboBox as QComboBox
from .no_scroll import NoScrollDoubleSpinBox as QDoubleSpinBox

from core.exporters import export_completion_reward_lines
from core.reward_presets import (
    REWARD_PRESET_GROUPS,
    REWARD_PRESETS,
    create_reward_item,
    get_reward_preset,
)
from core.types import CompletionReward, RewardItem

from .param_widgets import make_param_widget


class _RewardItemCard(QFrame):
    def __init__(self, index: int, item: RewardItem, on_change, on_delete,
                 country_tag: str = "", idea_refs=()) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._index = index
        self._item = item
        self._on_change = on_change
        self._on_delete = on_delete
        self._country_tag = country_tag
        self._idea_refs = list(idea_refs or [])
        preset = get_reward_preset(item.kind)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        title = QLabel(f"<b>{preset.label if preset else item.kind}</b>")
        header.addWidget(title)
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

        # Param form
        form = QFormLayout()
        form.setSpacing(6)
        v.addLayout(form)
        if preset:
            for param in preset.params:
                widget = self._make_widget(param, item.params.get(param.key, param.defaultValue))
                tooltip = param.helpText or ""
                widget.setToolTip(tooltip)
                form.addRow(param.label, widget)

        # Preview (toggled with the inspector's "show script" checkbox)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(80)
        v.addWidget(self._preview)
        self._refresh_preview()

    def set_preview_visible(self, show: bool) -> None:
        self._preview.setVisible(bool(show))

    def _make_widget(self, param, current):
        return make_param_widget(
            param, current, lambda val: self._set_param(param.key, val),
            country_tag=self._country_tag, idea_refs=self._idea_refs)

    def _set_param(self, key: str, value) -> None:
        self._item.params[key] = value
        self._refresh_preview()
        self._on_change()

    def _toggle_enabled(self, checked: bool) -> None:
        self._item.enabled = checked
        self._refresh_preview()
        self._on_change()

    def _refresh_preview(self) -> None:
        from core.reward_presets import build_reward_item_lines
        lines = build_reward_item_lines(self._item)
        self._preview.setPlainText("\n".join(lines) if lines else "(no output)")


class RewardEditor(QWidget):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._focus_id: str = ""
        self._suspend = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # Simple fields
        form = QFormLayout()
        self._pp = self._spin()
        form.addRow("Political Power", self._pp)
        self._stab = self._spin(decimals=3)
        form.addRow("Stability", self._stab)
        self._army = self._spin()
        form.addRow("Army XP", self._army)
        self._air = self._spin()
        form.addRow("Air XP", self._air)
        v.addLayout(form)

        # Add-preset combobox
        h = QHBoxLayout()
        self._preset_combo = QComboBox()
        self._preset_combo.addItem("Add reward…", None)
        for group, presets in REWARD_PRESET_GROUPS:
            self._preset_combo.insertSeparator(self._preset_combo.count())
            self._preset_combo.addItem(f"-- {group} --", None)
            idx = self._preset_combo.count() - 1
            self._preset_combo.model().item(idx).setEnabled(False)
            for preset in presets:
                self._preset_combo.addItem(f"  {preset.label}", preset.kind)
                if group == "Ideas" and preset.kind == "add_idea":
                    self._preset_combo.addItem("  ✎ New Idea…", "__new_idea__")
        self._preset_combo.activated.connect(self._on_add_preset)
        h.addWidget(self._preset_combo, 1)
        v.addLayout(h)

        # Items list
        self._items_box = QVBoxLayout()
        self._items_box.setSpacing(8)
        v.addLayout(self._items_box)

        # Raw lines
        self._raw_label = QLabel("Raw Lines (one HOI4 effect per line)")
        v.addWidget(self._raw_label)
        self._raw = QPlainTextEdit()
        self._raw.setMaximumHeight(70)
        self._raw.textChanged.connect(self._commit_raw)
        v.addWidget(self._raw)

        # Generated preview
        self._preview_label = QLabel("Generated Reward Block")
        v.addWidget(self._preview_label)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(110)
        v.addWidget(self._preview)

        # Raw + generated blocks are toggled together from the inspector; hidden
        # by default to keep things clean.
        self._script_visible = False
        self._apply_script_visibility()

        # Wire simple field commits
        self._pp.valueChanged.connect(lambda val: self._commit_simple("politicalPower", val))
        self._stab.valueChanged.connect(lambda val: self._commit_simple("stability", val))
        self._army.valueChanged.connect(lambda val: self._commit_simple("armyExperience", val))
        self._air.valueChanged.connect(lambda val: self._commit_simple("airExperience", val))

    @staticmethod
    def _spin(decimals: int = 0) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-1e9, 1e9)
        sb.setDecimals(decimals)
        return sb

    def set_focus_id(self, focus_id: str) -> None:
        self._focus_id = focus_id or ""
        self._render()

    def _focus(self):
        return self._model.find_focus(self._focus_id)

    def _reward(self) -> CompletionReward:
        focus = self._focus()
        if not focus:
            return CompletionReward()
        if focus.completionReward is None:
            focus.completionReward = CompletionReward()
        return focus.completionReward

    def _render(self) -> None:
        self._suspend = True
        # Clear items
        while self._items_box.count():
            child = self._items_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        focus = self._focus()
        if not focus:
            self._suspend = False
            return
        reward = focus.completionReward or CompletionReward()
        self._pp.setValue(float(reward.politicalPower or 0))
        self._stab.setValue(float(reward.stability or 0))
        self._army.setValue(float(reward.armyExperience or 0))
        self._air.setValue(float(reward.airExperience or 0))

        tag = self._model.project.countryTag
        idea_refs = [(i.id, f"{i.title or i.id} ({i.id})") for i in self._model.project.ideas]
        for index, item in enumerate(reward.items or []):
            card = _RewardItemCard(index, item, self._on_item_changed,
                                   self._on_item_deleted, country_tag=tag,
                                   idea_refs=idea_refs)
            self._items_box.addWidget(card)

        self._raw.blockSignals(True)
        self._raw.setPlainText("\n".join(reward.rawLines or []))
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
            if isinstance(card, _RewardItemCard):
                card.set_preview_visible(self._script_visible)

    def _commit_simple(self, attr: str, value) -> None:
        if self._suspend:
            return
        focus = self._focus()
        if not focus:
            return
        reward = focus.completionReward or CompletionReward()
        setattr(reward, attr, value if value != 0 else None)
        focus.completionReward = reward
        self._refresh_preview()
        self._model.notify_changed()

    def _commit_raw(self) -> None:
        if self._suspend:
            return
        focus = self._focus()
        if not focus:
            return
        reward = focus.completionReward or CompletionReward()
        text = self._raw.toPlainText()
        lines = [ln for ln in text.split("\n") if ln.strip()]
        reward.rawLines = lines or None
        focus.completionReward = reward
        self._refresh_preview()
        self._model.notify_changed()

    def _on_add_preset(self, idx: int) -> None:
        kind = self._preset_combo.itemData(idx)
        self._preset_combo.setCurrentIndex(0)
        if not kind:
            return
        focus = self._focus()
        if not focus:
            return
        if kind == "__new_idea__":
            self._new_idea(focus)
            return
        reward = focus.completionReward or CompletionReward()
        if reward.items is None:
            reward.items = []
        item_dict = create_reward_item(kind)
        reward.items.append(RewardItem(kind=item_dict["kind"], enabled=item_dict["enabled"], params=item_dict["params"]))
        focus.completionReward = reward
        self._render()
        self._model.notify_changed()

    def _new_idea(self, focus) -> None:
        from .idea_editor import IdeaEditorDialog
        dlg = IdeaEditorDialog(self._model, parent=self)
        if not dlg.exec():
            return
        idea = dlg.result_idea()
        if not idea.id:
            return
        # de-dupe id against existing project ideas
        existing = {i.id for i in self._model.project.ideas}
        base, n = idea.id, 2
        while idea.id in existing:
            idea.id = f"{base}_{n}"
            n += 1
        self._model.project.ideas.append(idea)
        self._model.project.exportSettings.includeIdeas = True
        reward = focus.completionReward or CompletionReward()
        if reward.items is None:
            reward.items = []
        reward.items.append(RewardItem(kind="add_idea", enabled=True, params={"idea": idea.id}))
        focus.completionReward = reward
        self._render()
        self._model.notify_changed()
        self._model.status_message.emit(f"Created idea {idea.id} and added it as a reward.")

    def _on_item_changed(self) -> None:
        self._refresh_preview()
        self._model.notify_changed()

    def _on_item_deleted(self, index: int) -> None:
        focus = self._focus()
        if not focus or not focus.completionReward or not focus.completionReward.items:
            return
        del focus.completionReward.items[index]
        if not focus.completionReward.items:
            focus.completionReward.items = None
        self._render()
        self._model.notify_changed()

    def _refresh_preview(self) -> None:
        focus = self._focus()
        if not focus:
            self._preview.setPlainText("")
            return
        lines = export_completion_reward_lines(focus.completionReward or CompletionReward())
        self._preview.setPlainText("\n".join(lines) if lines else "(empty)")
