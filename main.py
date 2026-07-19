"""Focus Forge — native Windows entry point."""
from __future__ import annotations

import datetime
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from core.version import version_label
from ui import theme as T
from ui.main_window import MainWindow
from ui.style import build_qss

CRASH_LOG = Path(os.getenv("APPDATA") or ".") / "FocusForge" / "crash.log"


def _icon_path() -> str:
    """assets/icon.ico — next to the exe when frozen, in the repo when not."""
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent
    p = base / "assets" / "icon.ico"
    return str(p) if p.exists() else ""


def _install_crash_handler() -> None:
    """Log any unhandled exception to a file and tell the user where it is —
    pre-alpha users hit edge cases we can't reproduce without a traceback."""

    def hook(etype, value, tb):
        try:
            CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.datetime.now().isoformat(timespec='seconds')} "
                        f"{version_label()} ---\n")
                traceback.print_exception(etype, value, tb, file=f)
        except OSError:
            pass
        traceback.print_exception(etype, value, tb)  # keep stderr output too
        try:
            from PySide6.QtWidgets import QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None, "Focus Forge hit an error",
                    f"Something went wrong:\n\n{value}\n\n"
                    f"A detailed report was written to:\n{CRASH_LOG}\n\n"
                    f"Your project file on disk is untouched — if the app is "
                    f"unstable, save a copy now and restart.")
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    _install_crash_handler()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # App-wide font so non-QSS surfaces (completer popups, native menus) inherit
    # the Bahnschrift stack too, with a graceful fallback if it's absent.
    ui_font = QFont(T.FONT_UI_FAMILY, T.TEXT_BODY)
    ui_font.setStyleHint(QFont.SansSerif)
    app.setFont(ui_font)
    app.setStyleSheet(build_qss())
    app.setApplicationName("Focus Forge")
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))
    if sys.platform == "win32":
        # Own taskbar identity for source runs — without this Windows groups
        # the window under python.exe and shows the Python icon.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FocusForge.App")
        # Auto-update handshake: installer.iss waits for this mutex to vanish
        # before replacing files, so a /SILENT update can't race our shutdown.
        # Windows releases it only when the process has fully exited — exactly
        # the "safe to overwrite" signal setup needs. Never CloseHandle it.
        ctypes.windll.kernel32.CreateMutexW(None, False, "FocusForgeAppMutex")
    win = MainWindow()
    win.load_blank()      # don't auto-open a project; the launcher chooses
    win.show()
    win.show_welcome()    # startup menu: New Submod / Open / Recent / sample
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
