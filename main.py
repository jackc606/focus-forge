"""Focus Forge — native Windows entry point."""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui import theme as T
from ui.main_window import MainWindow
from ui.style import build_qss


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # App-wide font so non-QSS surfaces (completer popups, native menus) inherit
    # the Bahnschrift stack too, with a graceful fallback if it's absent.
    ui_font = QFont(T.FONT_UI_FAMILY, T.TEXT_BODY)
    ui_font.setStyleHint(QFont.SansSerif)
    app.setFont(ui_font)
    app.setStyleSheet(build_qss())
    app.setApplicationName("Focus Forge")
    win = MainWindow()
    win.load_blank()      # don't auto-open a project; the launcher chooses
    win.show()
    win.show_welcome()    # startup menu: New Submod / Open / Recent / sample
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
