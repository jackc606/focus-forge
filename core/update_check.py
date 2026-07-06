"""Auto-update logic — pure Python, no Qt.

Checks the public releases repo (``jackc606/focus-forge-releases``) for a newer
GitHub Release, and can stream its Inno Setup installer to disk with SHA-256
verification. The UI wraps these calls in background workers
(``ui/update_worker.py``) and presents them via ``ui/update_dialog.py``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from urllib.request import Request, urlopen

UPDATE_REPO = "jackc606/focus-forge-releases"
LATEST_RELEASE_URL = "https://api.github.com/repos/{repo}/releases/latest"

_HEADERS = {
    "User-Agent": "FocusForge-Updater",
    "Accept": "application/vnd.github+json",
}
_CHUNK = 64 * 1024

log = logging.getLogger("focusforge.update")


class UpdateError(Exception):
    """An update step (check, download, verification) failed."""


@dataclass
class UpdateInfo:
    """Everything the UI needs to offer one downloadable update."""

    version: str            # "0.3.1" (no leading v)
    tag: str                # "v0.3.1"
    notes: str              # release body (markdown, shown as plain text)
    asset_url: str          # browser_download_url of the -setup.exe
    asset_name: str         # "FocusForge-0.3.1-setup.exe"
    asset_size: int         # bytes (0 if GitHub didn't say)
    sha256: str | None = None   # expected digest of the installer, if published
    html_url: str = ""      # release page (fallback for non-frozen dev runs)


def parse_version(text) -> tuple[int, int, int]:
    """``"v0.3.0-pre"`` → ``(0, 3, 0)``. Tolerant of a leading ``v``, missing
    parts (``"0.3"`` → ``(0, 3, 0)``) and trailing junk; anything unparseable
    is ``(0, 0, 0)``."""
    m = re.match(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or ""), re.IGNORECASE)
    if not m:
        return (0, 0, 0)
    major, minor, patch = (int(g) if g else 0 for g in m.groups())
    return (major, minor, patch)


def is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is a strictly newer version than ``current``."""
    return parse_version(latest) > parse_version(current)


def parse_release(data: dict, current_version: str) -> UpdateInfo | None:
    """Turn a GitHub *latest release* JSON payload into an :class:`UpdateInfo`.

    Returns None when the release isn't newer than ``current_version`` or has
    no ``FocusForge-*-setup.exe`` asset (matched case-insensitively). Pure —
    no network — so it's unit-testable; :func:`fetch_latest` does the I/O.
    """
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name") or "")
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    if not is_newer(version, current_version):
        return None
    asset = None
    for a in data.get("assets") or []:
        name = str(a.get("name") or "").lower()
        if name.startswith("focusforge") and name.endswith("-setup.exe"):
            asset = a
            break
    if asset is None:
        return None
    return UpdateInfo(
        version=version,
        tag=tag,
        notes=str(data.get("body") or ""),
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_name=str(asset.get("name") or ""),
        asset_size=int(asset.get("size") or 0),
        html_url=str(data.get("html_url") or ""),
    )


def _open(url: str, timeout: float):
    return urlopen(Request(url, headers=_HEADERS), timeout=timeout)


def fetch_latest(current_version: str, timeout: float = 10.0, *,
                 raise_on_error: bool = False) -> UpdateInfo | None:
    """Ask GitHub for the latest release; None if there's nothing newer.

    Network / JSON errors are logged and swallowed (None) so the silent
    startup check can never bother the user; a manual "Check for updates"
    passes ``raise_on_error=True`` to surface the failure as an
    :class:`UpdateError` instead.
    """
    url = LATEST_RELEASE_URL.format(repo=UPDATE_REPO)
    try:
        with _open(url, timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log.warning("Update check failed: %s", exc)
        if raise_on_error:
            raise UpdateError(f"Couldn't reach the update server ({exc}).") from exc
        return None
    info = parse_release(data, current_version)
    if info is None:
        return None
    info.sha256 = _fetch_sha256(data, info.asset_name, timeout)
    return info


def _fetch_sha256(data: dict, asset_name: str, timeout: float) -> str | None:
    """The installer's digest from the release's SHA256SUMS.txt asset
    (lines of ``<hex>  <filename>``). Missing/broken is non-fatal → None."""
    url = None
    for a in data.get("assets") or []:
        if str(a.get("name") or "").lower() == "sha256sums.txt":
            url = str(a.get("browser_download_url") or "")
            break
    if not url:
        return None
    try:
        with _open(url, timeout) as resp:
            text = resp.read(1_000_000).decode("utf-8", "replace")
    except Exception as exc:
        log.warning("Couldn't fetch SHA256SUMS.txt: %s", exc)
        return None
    for line in text.splitlines():
        parts = line.split()
        # sha256sum-style "*name" binary marker tolerated.
        if len(parts) >= 2 and parts[-1].lstrip("*").lower() == asset_name.lower():
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    log.warning("No SHA-256 entry for %s in SHA256SUMS.txt", asset_name)
    return None


def download_asset(info: UpdateInfo, dest_dir: str, progress_cb=None,
                   timeout: float = 30.0) -> str:
    """Stream the installer to ``dest_dir/asset_name`` in 64 KiB chunks.

    ``progress_cb(received_bytes, total_bytes)`` is called per chunk if given.
    When ``info.sha256`` is known the finished file is verified and an
    :class:`UpdateError` raised (and the file removed) on mismatch. Returns
    the downloaded file's path.
    """
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, info.asset_name)
    hasher = hashlib.sha256()
    received = 0
    try:
        with _open(info.asset_url, timeout) as resp, open(dest, "wb") as out:
            total = info.asset_size or int(resp.headers.get("Content-Length") or 0)
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                received += len(chunk)
                if progress_cb is not None:
                    progress_cb(received, total)
    except Exception as exc:
        _remove_quietly(dest)
        raise UpdateError(f"Download failed: {exc}") from exc
    if info.sha256 and hasher.hexdigest().lower() != info.sha256.lower():
        _remove_quietly(dest)
        raise UpdateError(
            "The downloaded installer failed its integrity check "
            "(SHA-256 mismatch) and was discarded. Try again later.")
    return dest


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def can_self_update() -> bool:
    """Only the frozen (PyInstaller) build can install over itself; a dev run
    from source gets a link to the download page instead."""
    return bool(getattr(sys, "frozen", False))
