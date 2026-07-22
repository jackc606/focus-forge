"""Reward editor: simple fields + preset picker + per-item dynamic forms + raw lines + preview."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
    build_reward_item_lines,
    create_reward_item,
    get_reward_preset,
)
from core.reward_script import parse_reward_lines, structure_completion_reward
from core.types import CompletionReward, RewardItem

from . import theme as T
from .item_card import PresetItemCard
from .param_widgets import make_param_widget
from .widgets import add_combo_item


class RewardEditor(QWidget):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._focus_id: str = ""
        self._suspend = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_SM)

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
                add_combo_item(self._preset_combo, f"  {preset.label}",
                               preset.kind, preset.description)
                if group == "Ideas" and preset.kind == "add_idea":
                    add_combo_item(self._preset_combo, "  ✎ New Idea…", "__new_idea__",
                                   "Author a brand-new national spirit and grant it "
                                   "from this focus in one step.")
        self._preset_combo.activated.connect(self._on_add_preset)
        h.addWidget(self._preset_combo, 1)
        v.addLayout(h)

        # Items list
        self._items_box = QVBoxLayout()
        self._items_box.setSpacing(T.SPACE_SM)
        v.addLayout(self._items_box)

        # Raw lines
        self._raw_label = QLabel("Raw Lines (one HOI4 effect per line)")
        v.addWidget(self._raw_label)
        self._raw = QPlainTextEdit()
        self._raw.setMaximumHeight(T.TEXTAREA_SHORT)
        self._raw.textChanged.connect(self._commit_raw)
        v.addWidget(self._raw)
        self._convert_btn = QPushButton("Structure raw script")
        self._convert_btn.setToolTip(
            "Convert this focus's raw script into editable reward cards. "
            "All-or-nothing: it only converts when every effect is recognized "
            "and rebuilds to the same script (key order/whitespace may be "
            "tidied), so the exported mod stays identical. Undo restores the "
            "raw form.")
        self._convert_btn.clicked.connect(self._convert_raw)
        v.addWidget(self._convert_btn)

        # Generated preview
        self._preview_label = QLabel("Generated Reward Block")
        v.addWidget(self._preview_label)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(T.TEXTAREA_TALL)
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
        # Clear items — hide BEFORE deleteLater or the old cards keep painting
        # at their stale geometry for a frame, overlapping their replacements.
        while self._items_box.count():
            child = self._items_box.takeAt(0)
            w = child.widget()
            if w:
                w.hide()
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
        event_refs = [(e.id, f"{e.title or e.id} ({e.id})") for e in self._model.project.events]
        from .leader_options import build_leader_refs
        leader_refs = build_leader_refs(self._model.project)
        for index, item in enumerate(reward.items or []):
            card = PresetItemCard(
                index, item, get_reward_preset(item.kind),
                on_change=self._on_item_changed, on_delete=self._on_item_deleted,
                build_lines=build_reward_item_lines, empty_text="(no output)",
                make_widget=lambda param, current, set_value: make_param_widget(
                    param, current, set_value, country_tag=tag,
                    idea_refs=idea_refs, event_refs=event_refs,
                    leader_refs=leader_refs))
            self._items_box.addWidget(card)

        self._raw.blockSignals(True)
        self._raw.setPlainText("\n".join(reward.rawLines or []))
        self._raw.blockSignals(False)
        self._convert_btn.setVisible(bool(reward.rawLines))

        self._refresh_preview()
        self._apply_script_visibility()  # new cards follow the toggle
        self._suspend = False

    # ----- raw script → structured items -----
    def _convert_raw(self) -> None:
        """Lift this focus's raw script into structured item cards — but only
        when EVERY effect parses and round-trips, so the exported script stays
        game-identical and no line silently changes meaning."""
        focus = self._focus()
        if not focus or not focus.completionReward:
            return
        reward = focus.completionReward
        raw = list(reward.rawLines or [])
        if not raw:
            return
        parsed, remainder = parse_reward_lines(raw)
        if remainder or not parsed:
            recognized = len(parsed)
            QMessageBox.information(
                self, "Structure raw script",
                f"Recognized {recognized} effect{'s' if recognized != 1 else ''}, "
                f"but not the whole script — nothing was changed.\n\n"
                f"Conversion is all-or-nothing so the raw script's exact order "
                f"is preserved. First unrecognized line:\n"
                f"  {remainder[0].strip() if remainder else '(none)'}")
            return
        n = structure_completion_reward(reward)
        focus.completionReward = reward
        self._model.notify_changed()
        self._render()
        self._model.status_message.emit(
            f"Structured {n} effect{'s' if n != 1 else ''} "
            f"from raw script — undo restores the raw form.")

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
        items = focus.completionReward.items
        # The card's index is render-time; the list may have shrunk/shifted
        # underneath us (e.g. an AI-bridge edit while this focus is selected).
        # Out-of-range or mismatched identity → re-render instead of deleting
        # the wrong item (or crashing).
        if not (0 <= index < len(items)) or not self._card_matches(index, items[index]):
            self._render()
            return
        del items[index]
        if not focus.completionReward.items:
            focus.completionReward.items = None
        self._render()
        self._model.notify_changed()

    def _card_matches(self, index: int, item) -> bool:
        """True when the rendered card at ``index`` still edits ``item``."""
        layout_item = self._items_box.itemAt(index)
        card = layout_item.widget() if layout_item else None
        if not isinstance(card, PresetItemCard):
            return False
        return card._item is item

    def _refresh_preview(self) -> None:
        focus = self._focus()
        if not focus:
            self._preview.setPlainText("")
            return
        lines = export_completion_reward_lines(focus.completionReward or CompletionReward())
        self._preview.setPlainText("\n".join(lines) if lines else "(empty)")
