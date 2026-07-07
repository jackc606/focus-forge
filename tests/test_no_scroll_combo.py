"""A NoScrollComboBox must never change its value on a mouse-wheel roll — not
even when focused. Selecting/typing in an editable combo leaves its line edit
focused, and the old hasFocus() escape hatch then let a scroll cycle the value
(the decision-editor 'random modifier swap' bug)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.no_scroll import NoScrollComboBox


def _app():
    return QApplication.instance() or QApplication([])


def _wheel(w):
    return QWheelEvent(QPoint(5, 5), w.mapToGlobal(QPoint(5, 5)), QPoint(0, 0),
                       QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                       Qt.NoScrollPhase, False)


def _combo(editable):
    cb = NoScrollComboBox()
    cb.setEditable(editable)
    cb.addItems(["alpha", "beta", "gamma", "delta"])
    cb.setCurrentIndex(1)
    return cb


def test_wheel_ignored_when_unfocused():
    _app()
    cb = _combo(editable=False)
    cb.clearFocus()
    ev = _wheel(cb)
    QApplication.sendEvent(cb, ev)
    assert cb.currentText() == "beta"
    assert not ev.isAccepted()          # propagates to the scroll area


def test_wheel_ignored_when_editable_and_focused():
    _app()
    cb = _combo(editable=True)
    cb.show()
    QApplication.instance().processEvents()
    cb.lineEdit().setFocus()            # the state after picking/typing a value
    assert cb.hasFocus()                # editable combo reports focus via line edit
    ev = _wheel(cb)
    QApplication.sendEvent(cb, ev)
    assert cb.currentText() == "beta"   # value unchanged
    assert not ev.isAccepted()


def test_wheel_ignored_when_noneditable_and_focused():
    _app()
    cb = _combo(editable=False)
    cb.setFocus()
    ev = _wheel(cb)
    QApplication.sendEvent(cb, ev)
    assert cb.currentText() == "beta"
