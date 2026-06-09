"""Visual focus-icon picker: a searchable grid of in-game icon thumbnails.

Thumbnails decode lazily on the UI thread in small batches so the dialog stays
responsive even with thousands of candidate sprites.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from . import theme as T
from .dds_image import load_dds_qimage
from .icon_provider import provider
from .widgets import hint, panel_header

_THUMB = QSize(64, 56)
_MAX_SHOWN = 600       # cap the grid; refine the search to see narrower results
_NAME_ROLE = Qt.UserRole
_PATH_ROLE = Qt.UserRole + 1
_DONE_ROLE = Qt.UserRole + 2   # this item's thumbnail load has been attempted

# Decoded thumbnails, keyed by absolute path, shared across every picker instance
# and session — so reopening a picker (or scrolling back) is instant. Values are a
# QPixmap, or None for a file that failed to decode (so we don't retry it).
_THUMB_CACHE: dict = {}


class IconPickerDialog(QDialog):
    def __init__(self, current: str = "", parent=None, *, sprites=None,
                 title: str = "Choose Focus Icon", loader=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 560)
        self._chosen = None
        self._loader = loader or load_dds_qimage
        raw = list(sprites) if sprites is not None else provider().focus_sprites()
        # Normalise to (value, path, label). 2-tuples (name, path) display the
        # name (GFX_ stripped); 3-tuples carry an explicit display label.
        self._all = [self._norm(s) for s in raw]
        # Thumbnails decode lazily — only for items scrolled into view — so opening a
        # picker with thousands of large images (e.g. event pictures) stays snappy.
        # A short debounce coalesces the burst of scroll signals into one decode pass.
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(16)
        self._load_timer.timeout.connect(self._load_visible)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header(title.replace("Choose ", "")))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search icons by name…")
        self._search.textChanged.connect(self._populate)
        v.addWidget(self._search)

        self._count = hint("")
        v.addWidget(self._count)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setIconSize(_THUMB)
        self._list.setGridSize(QSize(94, 92))
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setUniformItemSizes(True)
        self._list.setWordWrap(True)
        self._list.setSpacing(4)
        self._list.itemDoubleClicked.connect(self._accept_item)
        self._list.itemSelectionChanged.connect(self._update_ok)
        self._list.verticalScrollBar().valueChanged.connect(self._schedule_load)
        v.addWidget(self._list, 1)

        if not self._all:
            v.addWidget(hint("No icons available — add your HOI4 / mod folders in "
                             "Settings → In-game Icons first."))

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self._accept_selected)
        self._buttons.rejected.connect(self.reject)
        v.addWidget(self._buttons)

        prefilter = current if (current and not current.startswith("GFX_")
                                and "/" not in current) else ""
        self._populate(prefilter)
        # Pre-select the current icon if it's in the list.
        if current:
            self._search.setText("")
            self._select_name(current)
        self._update_ok()

    @staticmethod
    def _norm(sprite) -> tuple:
        if len(sprite) >= 3:
            return (sprite[0], sprite[1], sprite[2])
        name, path = sprite[0], sprite[1]
        label = name[4:] if name.lower().startswith("gfx_") else name
        return (name, path, label)

    # ----- population + lazy thumbnails -----
    def _populate(self, query: str) -> None:
        self._load_timer.stop()
        self._list.clear()
        q = (query or "").strip().lower()
        if q:
            matches = [t for t in self._all if q in t[2].lower() or q in t[0].lower()]
        else:
            matches = list(self._all)
        total = len(matches)
        shown = matches[:_MAX_SHOWN]
        for value, path, label in shown:
            item = QListWidgetItem(label)
            item.setData(_NAME_ROLE, value)
            item.setData(_PATH_ROLE, path)
            item.setToolTip(value)
            item.setSizeHint(QSize(90, 90))
            self._list.addItem(item)
        if total > _MAX_SHOWN:
            self._count.setText(f"Showing {_MAX_SHOWN:,} of {total:,} — refine the search to narrow.")
        else:
            self._count.setText(f"{total:,} icon(s)")
        self._schedule_load()

    def _schedule_load(self, *_args) -> None:
        """(Re)start the debounce; thumbnails for the visible range load shortly after."""
        if self._list.count():
            self._load_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Layout (and thus visualItemRect) is only valid once shown.
        super().showEvent(event)
        self._schedule_load()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._schedule_load()

    def _load_visible(self) -> None:
        """Decode thumbnails only for items in (or just outside) the viewport."""
        if not self._list.count():
            return
        vp = self._list.viewport().rect()
        # one screen of buffer above/below, so thumbnails are ready just before
        # they scroll into view
        top = vp.top() - vp.height()
        bottom = vp.bottom() + vp.height()
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is None or item.data(_DONE_ROLE):
                continue
            r = self._list.visualItemRect(item)
            if r.bottom() < top:
                continue
            if r.top() > bottom:
                break  # items are in order — everything past here is further down
            self._set_thumb(item)
            item.setData(_DONE_ROLE, True)

    def _set_thumb(self, item) -> None:
        path = item.data(_PATH_ROLE)
        pm = _THUMB_CACHE.get(path, False)
        if pm is False:  # not decoded yet this session
            img = self._loader(path)
            pm = None
            if img is not None and not img.isNull():
                pm = QPixmap.fromImage(img).scaled(
                    _THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            _THUMB_CACHE[path] = pm
        if pm is not None and not pm.isNull():
            item.setIcon(QIcon(pm))

    # ----- selection -----
    def _select_name(self, name: str) -> None:
        low = name.lower()
        for row in range(self._list.count()):
            if (self._list.item(row).data(_NAME_ROLE) or "").lower() == low:
                self._list.setCurrentRow(row)
                self._list.scrollToItem(self._list.item(row))
                return

    def _update_ok(self) -> None:
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self._list.selectedItems()))

    def _accept_item(self, item: QListWidgetItem) -> None:
        self._chosen = item.data(_NAME_ROLE)
        self.accept()

    def _accept_selected(self) -> None:
        items = self._list.selectedItems()
        if items:
            self._chosen = items[0].data(_NAME_ROLE)
        self.accept()

    def selected_name(self):
        return self._chosen
