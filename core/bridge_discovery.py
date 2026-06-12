"""Discovery file for the in-process AI bridge.

The running editor binds a loopback TCP port and writes ``bridge.json`` here so the
out-of-process MCP proxy (``focusforge_mcp``) can find it. Qt-free on purpose — both
the GUI and the headless proxy import this.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_DIR_NAME = "FocusForge"
BRIDGE_FILE = "bridge.json"
PROTOCOL_VERSION = 1


def _app_data_dir() -> Path:
    """Per-user app dir for the discovery file (%LOCALAPPDATA% on Windows)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or tempfile.gettempdir()
    else:
        base = (os.environ.get("XDG_CONFIG_HOME")
                or os.path.join(os.path.expanduser("~"), ".config"))
    return Path(base) / APP_DIR_NAME


def bridge_info_path() -> Path:
    return _app_data_dir() / BRIDGE_FILE


def write_bridge_info(port: int, **extra) -> Path:
    """Record the listening port (+ pid/protocol/version/token) for the proxy.

    The file may carry the bridge auth token, so it must stay private to the
    user: %LOCALAPPDATA% is already per-user on Windows; on POSIX we tighten the
    file mode to 0600 (and the dir to 0700) so other local accounts can't read
    the token from a shared home."""
    path = bridge_info_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    info = {"port": int(port), "pid": os.getpid(), "protocol": PROTOCOL_VERSION}
    info.update(extra)
    path.write_text(json.dumps(info), encoding="utf-8")
    if os.name != "nt":
        for target, mode in ((path.parent, 0o700), (path, 0o600)):
            try:
                os.chmod(target, mode)
            except OSError:
                pass
    return path


def read_bridge_info() -> "dict | None":
    try:
        return json.loads(bridge_info_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_bridge_info() -> None:
    """Remove the discovery file — but only if it still points at THIS process.

    Two editor instances share one ``bridge.json``; whichever started last owns it
    (its pid is recorded). A different, older instance shutting down must not wipe the
    live instance's discovery file, or the bridge silently 'disappears'."""
    info = read_bridge_info()
    if info is not None and info.get("pid") not in (None, os.getpid()):
        return  # the file now belongs to another (live) instance — leave it alone
    try:
        bridge_info_path().unlink()
    except OSError:
        pass
