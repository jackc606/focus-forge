"""Combo/spin widgets that ignore the mouse wheel unless focused, so scrolling a
panel doesn't accidentally change a control the cursor happens to be over."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSizePolicy, QSpinBox


class _NoWheel:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # StrongFocus (not WheelFocus) → the widget won't grab focus on a wheel
        # roll; combined with the override below, the wheel propagates to the
        # scroll area instead of changing the value.
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollComboBox(_NoWheel, QComboBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Fill the available width but stay shrinkable, so a combo's long items
        # never force a horizontal scrollbar on the panel it lives in. The popup
        # still shows full text; the in-field text elides when cramped.
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def wheelEvent(self, event):
        # ALWAYS propagate to the scroll area — never cycle the selection. The
        # _NoWheel base allows the wheel when focused, but an EDITABLE combo
        # reports hasFocus() via its line edit, so selecting/typing a value
        # left it "focused" and a later scroll silently changed it (the random
        # modifier-swap bug). Combos are chosen by click/type/completer, never
        # the wheel; the open dropdown/completer popup is a separate widget and
        # still scrolls normally.
        event.ignore()


class NoScrollSpinBox(_NoWheel, QSpinBox):
    pass


class NoScrollDoubleSpinBox(_NoWheel, QDoubleSpinBox):
    pass
