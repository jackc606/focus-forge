"""Dialog to author a focus-tree shortcut (the in-game bottom-left branch
bookmark): a button label, the target focus the camera jumps to, an optional
custom zoom level, and an optional advanced visibility trigger. Produces a
FocusShortcut."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.types import FocusShortcut

from . import theme as T
from .no_scroll import NoScrollDoubleSpinBox
from .param_widgets import _id_combo
from .widgets import hint, panel_header, section_header


class ShortcutEditorDialog(QDialog):
    def __init__(self, model, shortcut: FocusShortcut = None,
                 target_default: str = "", parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._editing = shortcut is not None
        self.setWindowTitle("Edit Shortcut" if self._editing else "New Shortcut")
        self.resize(520, 0)

        self._target = (shortcut.target if shortcut else target_default) or ""

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("Focus Tree Shortcut"))
        v.addWidget(hint("A clickable branch bookmark shown bottom-left in-game. "
                         "Clicking it jumps the camera to the target focus."))

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)

        self._label = QLineEdit(shortcut.label if shortcut else "")
        self._label.setPlaceholderText("Button text, e.g. Military")
        form.addRow("Label", self._label)

        focus_ids = [f.id for f in self._model.project.focuses]
        self._target_combo = _id_combo(
            [(fid, fid) for fid in focus_ids], self._target,
            lambda val: setattr(self, "_target", (val or "").strip()),
            numeric=False, completer=True, empty_tip="Type a focus id")
        form.addRow("Target focus", self._target_combo)

        # Optional custom zoom (scroll_wheel_factor).
        self._zoom_check = QCheckBox("Custom zoom after jump")
        self._zoom_spin = NoScrollDoubleSpinBox()
        self._zoom_spin.setRange(0.1, 2.0)
        self._zoom_spin.setSingleStep(0.05)
        self._zoom_spin.setDecimals(2)
        zoom = shortcut.zoomFactor if shortcut else None
        if zoom is not None:
            self._zoom_check.setChecked(True)
            self._zoom_spin.setValue(float(zoom))
        else:
            self._zoom_spin.setValue(0.80)
        self._zoom_spin.setEnabled(self._zoom_check.isChecked())
        self._zoom_check.toggled.connect(self._zoom_spin.setEnabled)
        form.addRow(self._zoom_check, self._zoom_spin)

        # Optional advanced trigger (verbatim HOI4 lines).
        v.addWidget(section_header("Trigger (advanced)"))
        v.addWidget(hint("Optional visibility condition, one HOI4 line per row "
                         '(e.g. has_dlc = "Together for Victory"). Leave blank '
                         "to always show the shortcut."))
        self._trigger = QPlainTextEdit(
            "\n".join(shortcut.triggerRawLines) if shortcut else "")
        self._trigger.setMaximumHeight(T.TEXTAREA_MEDIUM)
        v.addWidget(self._trigger)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save Shortcut")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _on_accept(self) -> None:
        if not (self._target or "").strip():
            QMessageBox.warning(self, "Missing target",
                                "A shortcut needs a target focus (the focus the "
                                "camera jumps to). Pick one before saving.")
            return
        self.accept()

    def result_shortcut(self) -> FocusShortcut:
        zoom = self._zoom_spin.value() if self._zoom_check.isChecked() else None
        trigger = [ln.strip() for ln in self._trigger.toPlainText().splitlines()
                   if ln.strip()]
        return FocusShortcut(
            label=self._label.text().strip(),
            target=(self._target or "").strip(),
            zoomFactor=zoom,
            triggerRawLines=trigger,
        )
