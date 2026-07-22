"""Left sidebar: focus list (dossier rows: icon, title, mono id, status dot)
+ warnings summary. Rows are painted by a delegate — with 500+ focuses only
the visible rows ever pay for their paint."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from . import theme as T
from .icon_provider import provider
from .project_model import ProjectModel
from .widgets import divider, issue_card, mono_font, section_header

ROLE_ID = Qt.UserRole
ROLE_TITLE = Qt.UserRole + 1
ROLE_ICON = Qt.UserRole + 2
ROLE_STATUS = Qt.UserRole + 3  # None | "warning" | "error"

_STATUS_COLORS = {"error": T.STATUS_ERROR, "warning": T.STATUS_WARN}


class _FocusRowDelegate(QStyledItemDelegate):
    """One focus as a dossier row: icon thumbnail, title, mono id, and a
    validation dot on the right when the focus has issues."""

    ROW_H = 42
    _ICON_W, _ICON_H = 30, 26

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pm_cache: dict = {}  # icon name -> scaled QPixmap (or None)

    def clear_cache(self) -> None:
        self._pm_cache.clear()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt override)
        return QSize(option.rect.width(), self.ROW_H)

    def _scaled_icon(self, name: str):
        if name in self._pm_cache:
            return self._pm_cache[name]
        pm = provider().pixmap(name) if name else None
        scaled = None
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(self._ICON_W, self._ICON_H,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._pm_cache[name] = scaled
        return scaled

    def paint(self, p, option, index) -> None:
        r = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.save()
        if selected:
            p.fillRect(r, QColor(T.ACCENT_SOFT))
            p.fillRect(QRect(r.left(), r.top(), 2, r.height()), QColor(T.ACCENT))
        elif hover:
            p.fillRect(r, QColor(T.BG_HOVER))

        icon_rect = QRect(r.left() + 10, r.top() + (self.ROW_H - self._ICON_H) // 2,
                          self._ICON_W, self._ICON_H)
        scaled = self._scaled_icon(index.data(ROLE_ICON) or "")
        if scaled is not None:
            x = icon_rect.left() + (self._ICON_W - scaled.width()) // 2
            y = icon_rect.top() + (self._ICON_H - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            p.setPen(QPen(QColor(T.BORDER_SUBTLE)))
            p.setBrush(Qt.NoBrush)
            p.drawRect(icon_rect.adjusted(2, 2, -2, -2))

        right = r.right() - 10
        status = index.data(ROLE_STATUS)
        if status:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_STATUS_COLORS.get(status, T.STATUS_WARN)))
            p.setRenderHint(p.RenderHint.Antialiasing, True)
            p.drawEllipse(QRect(right - 7, r.center().y() - 3, 7, 7))
            right -= 14

        text_left = icon_rect.right() + 10
        text_w = max(10, right - text_left)
        title = index.data(ROLE_TITLE) or index.data(ROLE_ID) or ""
        fid = index.data(ROLE_ID) or ""

        title_font = option.font
        fm = QFontMetrics(title_font)
        p.setFont(title_font)
        p.setPen(QColor(T.TEXT_PRIMARY))
        p.drawText(QRect(text_left, r.top() + 5, text_w, fm.height()),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(title, Qt.ElideRight, text_w))

        id_font = mono_font(T.TEXT_MICRO)
        fm2 = QFontMetrics(id_font)
        p.setFont(id_font)
        p.setPen(QColor(T.TEXT_MUTED))
        p.drawText(QRect(text_left, r.bottom() - fm2.height() - 4, text_w, fm2.height()),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(fid, Qt.ElideRight, text_w))
        p.restore()


class FocusesListPanel(QWidget):
    search_changed = Signal(str)

    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._query = ""
        self._status_map: dict = {}  # focus_id -> "error" | "warning"
        self.setMinimumWidth(260)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SPACE_MD, T.SPACE_MD, T.SPACE_MD, T.SPACE_MD)
        layout.setSpacing(T.SPACE_MD)

        # Search box (filters this list + highlights the canvas)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search focuses…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_text)
        layout.addWidget(self._search)

        def counted_header(title: str):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(section_header(title))
            row.addStretch(1)
            count = QLabel()
            count.setObjectName("hint")
            row.addWidget(count)
            layout.addLayout(row)
            return count

        self._focus_count = counted_header("Focuses")
        self._list = QListWidget()
        self._list.setItemDelegate(_FocusRowDelegate(self._list))
        self._list.setMouseTracking(True)  # delegate hover state
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._on_clicked)
        layout.addWidget(self._list, 3)

        layout.addWidget(divider())

        self._warn_count = counted_header("Warnings")
        self._warnings_box = QVBoxLayout()
        self._warnings_box.setSpacing(T.SPACE_SM)
        warn_holder = QWidget()
        warn_holder.setLayout(self._warnings_box)
        warn_holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout.addWidget(warn_holder, 2)

        # Debounced rebuild: a burst of edits (typing a title) coalesces into
        # one list rebuild instead of one per keystroke.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self.refresh)
        self._model.project_changed.connect(self._refresh_timer.start)
        self._model.selection_changed.connect(self._sync_selection)
        self._model.validation_changed.connect(self._refresh_warnings)
        # Focus icons decode async — repaint rows (and rescale) as they land.
        provider().changed.connect(self._on_icons_changed)
        self.refresh()
        self._refresh_warnings(self._model.issues())

    def _on_icons_changed(self) -> None:
        delegate = self._list.itemDelegate()
        if isinstance(delegate, _FocusRowDelegate):
            delegate.clear_cache()
        self._list.viewport().update()

    def _on_search_text(self, text: str) -> None:
        self._query = text.strip().lower()
        self._apply_filter()
        self.search_changed.emit(text.strip())

    def _apply_filter(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(bool(self._query) and self._query not in item.text().lower())

    def refresh(self) -> None:
        scroll = self._list.verticalScrollBar().value()
        self._list.blockSignals(True)
        self._list.clear()
        for f in self._model.project.focuses:
            # The item TEXT is never painted (the delegate draws from roles) —
            # it exists so the search filter has one lowercase haystack.
            item = QListWidgetItem(f"{f.title}\n{f.id}")
            item.setData(ROLE_ID, f.id)
            item.setData(ROLE_TITLE, f.title or f.id)
            item.setData(ROLE_ICON, f.icon or "")
            item.setData(ROLE_STATUS, self._status_map.get(f.id))
            self._list.addItem(item)
            if f.id == self._model.selected_id:
                item.setSelected(True)
        self._list.blockSignals(False)
        n = self._list.count()
        self._focus_count.setText(f"{n} focus{'es' if n != 1 else ''}")
        self._apply_filter()
        self._list.verticalScrollBar().setValue(scroll)

    def _sync_selection(self, focus_id: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setSelected(item.data(ROLE_ID) == focus_id)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self._model.set_selection(item.data(ROLE_ID))

    def _refresh_warnings(self, issues: list) -> None:
        # Per-focus status for the row dots (errors outrank warnings).
        self._status_map = {}
        for issue in issues:
            if not issue.focusId:
                continue
            if issue.severity == "error" or self._status_map.get(issue.focusId) != "error":
                self._status_map[issue.focusId] = (
                    "error" if issue.severity == "error" else "warning")
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setData(ROLE_STATUS, self._status_map.get(item.data(ROLE_ID)))
        self._list.viewport().update()

        errors = sum(1 for i in issues if i.severity == "error")
        warns = len(issues) - errors
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warns:
            parts.append(f"{warns} warning{'s' if warns != 1 else ''}")
        self._warn_count.setText(" · ".join(parts) if parts else "clean")

        # clear
        while self._warnings_box.count():
            child = self._warnings_box.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        if not issues:
            placeholder = QLabel("No validation issues.")
            placeholder.setObjectName("muted")
            self._warnings_box.addWidget(placeholder)
            self._warnings_box.addStretch(1)
            return
        for issue in issues[:6]:
            # Clicking an issue that names a focus jumps to it.
            on_click = None
            if issue.focusId:
                on_click = (lambda fid=issue.focusId:
                            self._model.set_selection(fid))
            self._warnings_box.addWidget(
                issue_card(issue.severity, issue.message, on_click=on_click))
        if len(issues) > 6:
            more = QLabel(f"+{len(issues) - 6} more …")
            more.setObjectName("muted")
            self._warnings_box.addWidget(more)
        self._warnings_box.addStretch(1)
