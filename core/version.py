"""Single source of truth for the app version (shown in the UI, used for builds)."""
from __future__ import annotations

__version__ = "0.2.2"
APP_STAGE = "pre-alpha"
APP_VERSION = __version__


def version_label() -> str:
    """Short display string for the status bar, e.g. 'v0.1.0 · pre-alpha'."""
    return f"v{__version__}" + (f" · {APP_STAGE}" if APP_STAGE else "")
