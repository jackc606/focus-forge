"""Background workers for the auto-updater.

QObject workers moved to a QThread (never QThread subclasses) so the network
I/O in ``core.update_check`` stays off the UI thread. Each worker emits exactly
one outcome signal from ``run()``, then ``finished``; :func:`run_in_thread`
wires the standard lifecycle (quit → deleteLater for both objects).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.update_check import UpdateError, UpdateInfo, download_asset, fetch_latest


def run_in_thread(worker: QObject, parent=None) -> QThread:
    """Start ``worker.run`` on a fresh QThread with standard cleanup wiring.

    Connect the worker's outcome signals BEFORE calling this (the thread starts
    immediately). The caller should keep a Python reference to the worker until
    ``finished`` fires so it isn't garbage-collected mid-run.
    """
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread


class UpdateCheckWorker(QObject):
    """Asks GitHub whether a newer release exists.

    Emits exactly one of ``update_available`` / ``no_update`` / ``failed``,
    then ``finished``.
    """

    update_available = Signal(object)  # UpdateInfo
    no_update = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self._current = current_version

    @Slot()
    def run(self) -> None:
        try:
            info = fetch_latest(self._current, raise_on_error=True)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # defensive — never die silently off-thread
            self.failed.emit(str(exc))
        else:
            if info is not None:
                self.update_available.emit(info)
            else:
                self.no_update.emit()
        finally:
            self.finished.emit()


class UpdateDownloadWorker(QObject):
    """Streams the installer to disk (with SHA-256 verification).

    Emits ``progress(received, total)`` while downloading, then exactly one of
    ``downloaded(path)`` / ``failed(message)``, then ``finished``.
    """

    progress = Signal(int, int)
    downloaded = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, info: UpdateInfo, dest_dir: str) -> None:
        super().__init__()
        self._info = info
        self._dest_dir = dest_dir

    @Slot()
    def run(self) -> None:
        try:
            path = download_asset(self._info, self._dest_dir,
                                  progress_cb=self.progress.emit)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.downloaded.emit(path)
        finally:
            self.finished.emit()
