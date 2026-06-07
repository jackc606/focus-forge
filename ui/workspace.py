"""Focus Forge workspace location — where new submod project dirs live."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings


def focusforge_home() -> Path:
    """The Focus Forge app directory (exe dir when frozen, repo root from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # this file is <home>/ui/workspace.py → parents[1] is the repo root
    return Path(__file__).resolve().parents[1]


def workspace_dir() -> Path:
    """The projects workspace; overridable via QSettings, default <home>/projects."""
    override = QSettings("FocusForge", "FocusForge").value("workspace_dir", "")
    return Path(override) if override else focusforge_home() / "projects"
