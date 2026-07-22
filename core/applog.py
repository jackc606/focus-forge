"""Rotating event log + one-paste diagnostic report.

Remote support for a distributed pre-alpha means asking "what happened?" over
Discord. The event log records what the app actually did (opens, saves,
exports, bridge activity, Qt warnings, unhandled exceptions); the diagnostic
report packages app/project/environment facts plus the recent log into one
clipboard-sized text a user can paste without hunting for files."""
from __future__ import annotations

import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.getenv("APPDATA") or ".") / "FocusForge" / "logs"
_LOGGER_NAME = "focusforge"
_log_file: Path = LOG_DIR / "focusforge.log"


def logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def install(log_dir=None, force: bool = False) -> None:
    """Attach the rotating file handler (500 KB × 3). Safe to call twice;
    ``force`` re-installs (tests). Logging must never break the app: on any
    OS error the logger degrades to a null handler."""
    global _log_file
    log = logger()
    if log.handlers and not force:
        return
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    log.setLevel(logging.INFO)
    log.propagate = False
    directory = Path(log_dir) if log_dir else LOG_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _log_file = directory / "focusforge.log"
        handler = RotatingFileHandler(_log_file, maxBytes=500_000,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(handler)
    except OSError:
        log.addHandler(logging.NullHandler())


def install_qt_handler() -> None:
    """Route Qt warnings/criticals into the event log — 'QPainter not active'
    style spew is exactly what a remote bug report needs and users never see."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:  # pragma: no cover - PySide always present in the app
        return
    levels = {QtMsgType.QtWarningMsg: logging.WARNING,
              QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def handler(mode, _context, message) -> None:
        level = levels.get(mode)
        if level:
            logger().log(level, "Qt: %s", message)

    qInstallMessageHandler(handler)


def log_exception(etype, value, tb) -> None:
    """For the crash hook — records the traceback in the event log too, so a
    diagnostic report copied later still contains it."""
    try:
        logger().error("UNHANDLED EXCEPTION", exc_info=(etype, value, tb))
    except Exception:
        pass


def tail(lines: int = 120) -> str:
    """The last ``lines`` of the current log file ('' when there is none)."""
    try:
        text = _log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def build_report(info: dict, tail_lines: int = 120) -> str:
    """One-paste diagnostic report: environment header, caller-supplied
    key/value facts (project, paths, validation), then the recent event log."""
    out = ["=== Focus Forge diagnostic report ==="]
    out.append(f"os: {platform.platform()}")
    out.append(f"python: {sys.version.split()[0]}")
    try:
        import PySide6
        out.append(f"pyside: {PySide6.__version__}")
    except Exception:
        pass
    for key, value in info.items():
        out.append(f"{key}: {value}")
    out.append("")
    out.append(f"--- recent log (last {tail_lines} lines) ---")
    out.append(tail(tail_lines) or "(no log entries)")
    return "\n".join(out)
