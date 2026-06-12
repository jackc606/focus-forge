"""Shared card for one preset-driven item (a focus reward or an availability
condition): header row (preset label, enabled checkbox, delete), optional
description, a param form generated from the preset, and a script preview that
the host toggles with its "show script" checkbox.
"""
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
)

from . import theme as T


class PresetItemCard(QFrame):
    """``build_lines(item)`` renders the preview lines; ``empty_text`` shows when
    it returns none. ``make_widget(param, current, set_value)`` builds each param
    editor — the host binds its own context (tag, refs, focus ids) there."""

    def __init__(self, index: int, item, preset, *, on_change, on_delete,
                 build_lines, empty_text: str, make_widget) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._index = index
        self._item = item
        self._on_change = on_change
        self._on_delete = on_delete
        self._build_lines = build_lines
        self._empty_text = empty_text

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_MD, T.SPACE_MD, T.SPACE_MD, T.SPACE_MD)
        v.setSpacing(T.SPACE_SM)

        header = QHBoxLayout()
        title = QLabel(f"<b>{preset.label if preset else item.kind}</b>")
        if preset and preset.description:
            title.setToolTip(preset.description)
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

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)
        if preset:
            for param in preset.params:
                # Back-fill missing keys (older project files) so the widget and
                # the builder see the same value — without this, the widget shows
                # the preset default while the builder uses its own fallback.
                item.params.setdefault(param.key, param.defaultValue)
                widget = make_widget(
                    param, item.params[param.key],
                    lambda val, k=param.key: self._set_param(k, val))
                widget.setToolTip(param.helpText or "")
                form.addRow(param.label, widget)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(T.TEXTAREA_MEDIUM)
        v.addWidget(self._preview)
        self._refresh_preview()

    def set_preview_visible(self, show: bool) -> None:
        self._preview.setVisible(bool(show))

    def _set_param(self, key: str, value) -> None:
        self._item.params[key] = value
        self._refresh_preview()
        self._on_change()

    def _toggle_enabled(self, checked: bool) -> None:
        self._item.enabled = checked
        self._refresh_preview()
        self._on_change()

    def _refresh_preview(self) -> None:
        lines = self._build_lines(self._item)
        self._preview.setPlainText("\n".join(lines) if lines else self._empty_text)
