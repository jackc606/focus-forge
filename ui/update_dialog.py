"""'Update available' dialog: release notes, download-with-progress, install.

The install hand-off is deliberately ordered: ask the main window to close
FIRST (which runs its normal unsaved-changes prompt), and only if it actually
closed spawn the installer (``/SILENT``) and quit the app — so an update can
never bypass the save prompt, and a cancelled close never launches setup.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from core.update_check import UPDATE_REPO, UpdateInfo, can_self_update

from . import theme as T
from .update_worker import UpdateDownloadWorker, run_in_thread
from .widgets import hint, panel_header


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f}"


class UpdateDialog(QDialog):
    """Offers one downloadable update. ``request_close`` is a callable that
    asks the main window to close via its normal path (returning True only if
    it really closed); without it the dialog assumes closing is fine."""

    def __init__(self, info: UpdateInfo, current_version: str,
                 request_close=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update available")
        self.resize(*T.DIALOG_MD)
        self._info = info
        self._request_close = request_close
        self._installer_path: str | None = None
        self._worker = None
        self._thread = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        outer.setSpacing(T.SPACE_MD)
        outer.addWidget(panel_header("Update available"))
        outer.addWidget(hint(
            f"Focus Forge v{info.version} (you have v{current_version})"))

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(info.notes.strip() or "No release notes.")
        outer.addWidget(notes, 1)

        self._skip = QCheckBox("Skip this version")
        self._skip.setToolTip(
            "Don't offer this version again at startup. The status-bar notice "
            "stays so you can still install it later.")
        outer.addWidget(self._skip)

        self._error = QLabel("")
        self._error.setObjectName("issueTextError")
        self._error.setWordWrap(True)
        self._error.hide()
        outer.addWidget(self._error)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.hide()
        outer.addWidget(self._progress)
        self._progress_label = hint("")
        self._progress_label.hide()
        outer.addWidget(self._progress_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(T.SPACE_SM)
        buttons.addStretch(1)
        self._btn_later = QPushButton("Later")
        self._btn_later.clicked.connect(self.reject)
        buttons.addWidget(self._btn_later)
        self._btn_primary = QPushButton()
        self._btn_primary.setObjectName("primary")
        if can_self_update():
            self._btn_primary.setText("Download && install")
            self._btn_primary.clicked.connect(self._on_primary)
        else:
            # Dev run from source — can't install over ourselves.
            self._btn_primary.setText("Open download page")
            self._btn_primary.clicked.connect(self._open_download_page)
        buttons.addWidget(self._btn_primary)
        outer.addLayout(buttons)

    # ----- public -----
    def skip_requested(self) -> bool:
        """True if the user ticked 'Skip this version' (read after exec)."""
        return self._skip.isChecked()

    def reject(self) -> None:
        # Esc / title-bar X route through here: while a download thread is
        # live, dismissing would leave it running against a dead dialog (and
        # crash on app exit) — ignore until it finishes.
        if self._thread is not None:
            return
        super().reject()

    # ----- download -----
    def _on_primary(self) -> None:
        if self._installer_path:
            self._try_install()  # already downloaded; close was cancelled before
        else:
            self._start_download()

    def _start_download(self) -> None:
        self._error.hide()
        self._set_buttons_enabled(False)
        self._progress.show()
        self._progress_label.setText("Starting download…")
        self._progress_label.show()

        dest = str(Path(tempfile.gettempdir()) / "FocusForge")
        self._worker = UpdateDownloadWorker(self._info, dest)
        self._worker.progress.connect(self._on_progress)
        self._worker.downloaded.connect(self._on_downloaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._thread = run_in_thread(self._worker, self)

    def _on_progress(self, received: int, total: int) -> None:
        if total > 0:
            self._progress.setRange(0, 1000)
            self._progress.setValue(min(1000, received * 1000 // total))
            self._progress_label.setText(
                f"Downloading {self._info.asset_name} — "
                f"{_mb(received)} / {_mb(total)} MB")
        else:
            self._progress.setRange(0, 0)  # indeterminate
            self._progress_label.setText(
                f"Downloading {self._info.asset_name} — {_mb(received)} MB")

    def _on_worker_finished(self) -> None:
        self._worker = None
        self._thread = None

    def _on_downloaded(self, path: str) -> None:
        self._installer_path = path
        self._progress.setRange(0, 1000)
        self._progress.setValue(1000)
        self._progress_label.setText("Download complete — verified.")
        self._try_install()

    def _on_failed(self, message: str) -> None:
        self._progress.hide()
        self._progress_label.hide()
        self._error.setText(message)
        self._error.show()
        self._set_buttons_enabled(True)

    # ----- install hand-off -----
    def _try_install(self) -> None:
        # Ask the app to close FIRST (normal unsaved-changes prompt included);
        # only a real close launches the installer.
        closed = True
        if callable(self._request_close):
            closed = bool(self._request_close())
        if not closed:
            self._error.setText(
                "Install cancelled — Focus Forge has to close to update. "
                "The installer is downloaded; click \"Install now\" when "
                "you're ready.")
            self._error.show()
            self._btn_primary.setText("Install now")
            self._set_buttons_enabled(True)
            return
        try:
            subprocess.Popen([self._installer_path, "/SILENT"], close_fds=True)
        except OSError as exc:
            self._error.setText(f"Couldn't launch the installer: {exc}")
            self._error.show()
            self._btn_primary.setText("Install now")
            self._set_buttons_enabled(True)
            return
        self.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _open_download_page(self) -> None:
        url = self._info.html_url or f"https://github.com/{UPDATE_REPO}/releases/latest"
        QDesktopServices.openUrl(QUrl(url))

    def _set_buttons_enabled(self, on: bool) -> None:
        self._btn_primary.setEnabled(on)
        self._btn_later.setEnabled(on)
        self._skip.setEnabled(on)
