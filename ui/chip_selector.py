"""Multi-select chip widget: pick from a dropdown (with type-ahead) or type a
value; selected values show as removable chips. API-compatible with TokenEditor
(``tokens_changed`` / ``set_tokens`` / ``update_suggestions``)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme as T
from .no_scroll import NoScrollComboBox as QComboBox


class _FlowLayout(QLayout):
    """Minimal wrapping layout (adapted from Qt's FlowLayout example)."""

    def __init__(self, parent=None, spacing=T.SPACE_SM) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + QSize(2, 2)

    def _do_layout(self, rect, test_only) -> int:
        x, y = rect.x(), rect.y()
        line_h = 0
        for item in self._items:
            w = item.sizeHint()
            nx = x + w.width() + self._spacing
            if nx - self._spacing > rect.right() and line_h > 0:
                x = rect.x()
                y = y + line_h + self._spacing
                nx = x + w.width() + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), w))
            x = nx
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()


class _Chip(QFrame):
    removed = Signal(str)

    def __init__(self, token: str, tooltip: str = "") -> None:
        super().__init__()
        self._token = token
        self.setObjectName("chip")
        if tooltip:
            self.setToolTip(tooltip)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.SPACE_SM, 2, T.SPACE_XS, 2)
        lay.setSpacing(T.SPACE_XS)
        lay.addWidget(QLabel(token))
        x = QPushButton("×")
        x.setObjectName("chipClose")
        x.setToolTip("Remove")
        x.setFixedSize(16, 16)
        x.setCursor(Qt.PointingHandCursor)
        x.clicked.connect(lambda: self.removed.emit(self._token))
        lay.addWidget(x)


class ChipSelector(QWidget):
    tokens_changed = Signal(list)

    def __init__(self, suggestions=None, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self._tokens: list = []
        self._suggestions: list = list(suggestions or [])
        self._groups = None  # optional [(label, [value])] for a categorised dropdown
        self._tooltips: dict = {}  # value -> hover tooltip

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(T.SPACE_XS)

        # Optional category filter (only shown when grouped suggestions are set).
        self._filter_combo = QComboBox()
        self._filter_combo.setVisible(False)
        self._filter_combo.currentIndexChanged.connect(lambda *_: self._rebuild_combo())
        outer.addWidget(self._filter_combo)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if placeholder:
            self._combo.lineEdit().setPlaceholderText(placeholder)
        self._rebuild_combo()
        self._combo.activated.connect(self._on_activated)
        self._combo.lineEdit().returnPressed.connect(self._on_return)
        outer.addWidget(self._combo)

        self._chips_host = QWidget()
        self._flow = _FlowLayout(self._chips_host)
        outer.addWidget(self._chips_host)

    # ----- API parity with TokenEditor -----
    def set_tokens(self, tokens) -> None:
        self._tokens = [t for t in (tokens or []) if str(t).strip()]
        self._render_chips()

    def tokens(self) -> list:
        return list(self._tokens)

    def update_suggestions(self, suggestions) -> None:
        self._groups = None
        self._suggestions = list(suggestions or [])
        self._rebuild_combo()

    def set_grouped_suggestions(self, groups, tooltips=None) -> None:
        """Categorised dropdown: ``groups`` = [(label, [value])]. Disabled header
        rows separate the categories; the type-ahead completer still searches all
        values (fully searchable). A category filter combo narrows the list.
        ``tooltips`` = {value: text} shown on hover (dropdown items + chips)."""
        self._groups = list(groups or [])
        self._tooltips = dict(tooltips or {})
        self._suggestions = [v for _label, vals in self._groups for v in vals]
        self._filter_combo.blockSignals(True)
        self._filter_combo.clear()
        self._filter_combo.addItem("All categories")
        for label, _vals in self._groups:
            self._filter_combo.addItem(label)
        self._filter_combo.setVisible(bool(self._groups))
        self._filter_combo.blockSignals(False)
        self._rebuild_combo()
        self._render_chips()  # refresh chip tooltips

    # ----- internals -----
    def _add_item(self, value: str) -> None:
        self._combo.addItem(value)
        tip = self._tooltips.get(value)
        if tip:
            self._combo.setItemData(self._combo.count() - 1, tip, Qt.ToolTipRole)

    def _rebuild_combo(self) -> None:
        self._combo.blockSignals(True)
        text = self._combo.currentText()
        self._combo.clear()
        self._combo.addItem("")  # blank so nothing is preselected
        if self._groups:
            flt = (self._filter_combo.currentText()
                   if self._filter_combo.currentIndex() > 0 else None)
            visible = [g for g in self._groups if flt is None or g[0] == flt]
            for label, vals in visible:
                fresh = [v for v in vals if v not in self._tokens]
                if not fresh:
                    continue
                if flt is None:  # only show headers when browsing all categories
                    self._combo.addItem(f"— {label} —")
                    self._combo.model().item(self._combo.count() - 1).setEnabled(False)
                for v in fresh:
                    self._add_item(v)
            search = [v for _l, vals in visible for v in vals]
        else:
            for s in self._suggestions:
                if s not in self._tokens:
                    self._add_item(s)
            search = list(self._suggestions)
        comp = QCompleter(search, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self._combo.setCompleter(comp)
        self._combo.setCurrentText(text)
        self._combo.blockSignals(False)

    def _on_activated(self, idx: int) -> None:
        if idx <= 0:
            return
        text = self._combo.itemText(idx)
        if text.startswith("— ") and text.endswith(" —"):
            return  # a category header, not a value
        self._add(text)

    def _on_return(self) -> None:
        self._add(self._combo.currentText())

    def _add(self, token: str) -> None:
        token = (token or "").strip()
        if not token or token in self._tokens:
            self._combo.setCurrentText("")
            return
        self._tokens.append(token)
        self._combo.setCurrentText("")
        self._rebuild_combo()
        self._render_chips()
        self.tokens_changed.emit(list(self._tokens))

    def _remove(self, token: str) -> None:
        if token in self._tokens:
            self._tokens.remove(token)
            self._rebuild_combo()
            self._render_chips()
            self.tokens_changed.emit(list(self._tokens))

    def _render_chips(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for token in self._tokens:
            chip = _Chip(token, self._tooltips.get(token, ""))
            chip.removed.connect(self._remove)
            self._flow.addWidget(chip)
        self._chips_host.setVisible(bool(self._tokens))
        self._chips_host.updateGeometry()
