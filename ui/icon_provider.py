"""App-wide provider of in-game focus icons.

Scans configured HOI4 / mod roots for ``interface/*.gfx`` sprite definitions,
resolves a focus's ``icon`` value to its ``.dds``, decodes it (pure-Python), and
hands back a cached ``QPixmap``. Roots persist across sessions via ``QSettings``.

Nodes query the singleton via ``provider()``. When roots change it emits
``changed`` so the scene can repaint.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QPixmap

from core.gfx_index import build_sprite_index, resolve_sprite
from core.portrait_index import build_leader_portraits, resolve_portrait

from .dds_image import load_dds_qimage

_STEAM_GUESSES = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\Steam",
    r"D:\SteamLibrary",
    r"E:\SteamLibrary",
]
_MD_WORKSHOP_ID = "2777392649"  # "Millennium Dawn: A Modern Day Mod"
_HOI4_APPID = "394360"


def _steam_install_dirs() -> list:
    """Steam install directories — from the Windows registry first (where the
    user actually installed Steam), then the common-path guesses as a fallback."""
    dirs = []
    try:
        import winreg
        for hive, key, val in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    p = winreg.QueryValueEx(k, val)[0]
                    if p:
                        dirs.append(os.path.normpath(p))
            except OSError:
                pass
    except ImportError:
        pass  # not on Windows
    dirs.extend(_STEAM_GUESSES)
    seen, out = set(), []
    for d in dirs:
        key = os.path.normpath(d).lower()
        if key not in seen and os.path.isdir(d):
            seen.add(key)
            out.append(d)
    return out


def _parse_libraryfolders(text: str) -> list:
    """Library paths listed in a steamapps/libraryfolders.vdf (un-escaped)."""
    return [m.group(1).replace("\\\\", "\\")
            for m in re.finditer(r'"path"\s*"([^"]+)"', text)]


def _steam_library_steamapps() -> list:
    """Every Steam library's ``steamapps`` folder, on any drive — discovered via
    each Steam install's libraryfolders.vdf."""
    libs = []
    for steam in _steam_install_dirs():
        sa = os.path.join(steam, "steamapps")
        if os.path.isdir(sa):
            libs.append(sa)
        vdf = os.path.join(sa, "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                text = open(vdf, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for p in _parse_libraryfolders(text):
                lsa = os.path.join(p, "steamapps")
                if os.path.isdir(lsa):
                    libs.append(lsa)
    seen, out = set(), []
    for l in libs:
        key = os.path.normpath(l).lower()
        if key not in seen:
            seen.add(key)
            out.append(os.path.normpath(l))
    return out


def _find_millennium_dawn(steamapps_dirs: list):
    """The MD base-mod folder across libraries: the known workshop id first, else
    any 394360 workshop item whose descriptor names Millennium Dawn (forks/updates)."""
    for sa in steamapps_dirs:
        md = os.path.join(sa, "workshop", "content", _HOI4_APPID, _MD_WORKSHOP_ID)
        if os.path.isdir(md):
            return md
    for sa in steamapps_dirs:
        wc = os.path.join(sa, "workshop", "content", _HOI4_APPID)
        if not os.path.isdir(wc):
            continue
        for sub in sorted(os.listdir(wc)):
            desc = os.path.join(wc, sub, "descriptor.mod")
            if not os.path.isfile(desc):
                continue
            try:
                if "millennium dawn" in open(
                        desc, "r", encoding="utf-8-sig", errors="replace").read().lower():
                    return os.path.join(wc, sub)
            except OSError:
                continue
    return None


def autodetect_roots() -> list:
    """Base game + Millennium Dawn base mod, found via Steam's own config on any
    drive (registry + libraryfolders.vdf), with common-path fallbacks."""
    steamapps = _steam_library_steamapps()
    found = []
    for sa in steamapps:
        game = os.path.join(sa, "common", "Hearts of Iron IV")
        if os.path.isdir(game):
            found.append(os.path.normpath(game))
            break
    md = _find_millennium_dawn(steamapps)
    if md:
        found.append(os.path.normpath(md))
    return found


class IconProvider(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("FocusForge", "FocusForge")
        self._roots: list = list(self._settings.value("icon_roots", []) or [])
        self._index: dict = {}
        self._cache: dict = {}      # icon_value(lower) -> QPixmap or None
        self._focus_sprites = None  # cached [(name, path)] under interface/goals
        self._idea_sprites = None   # cached [(name, path)] for GFX_idea_*
        self._leader_portraits: dict = {}  # tag -> [(relpath, abspath, label)]
        self._portrait_cache: dict = {}    # relpath(lower) -> QPixmap or None
        self._index_built = False

    # ----- roots -----
    def roots(self) -> list:
        return list(self._roots)

    def set_roots(self, roots) -> None:
        self._roots = [r for r in roots if r]
        self._settings.setValue("icon_roots", self._roots)
        self._index_built = False
        self._index = {}
        self._cache = {}
        self._focus_sprites = None
        self._idea_sprites = None
        self._leader_portraits = {}
        self._portrait_cache = {}
        self.changed.emit()

    def ensure_default_roots(self) -> None:
        """On first run with no config, seed from autodetection (if anything found)."""
        if not self._roots:
            auto = autodetect_roots()
            if auto:
                self.set_roots(auto)

    # ----- lookup -----
    def _build_index(self) -> None:
        self._index = build_sprite_index(self._roots)
        self._index_built = True

    def is_indexed(self) -> bool:
        return self._index_built

    def focus_sprites(self) -> list:
        """Sorted [(GFX_name, abs_path)] for sprites under interface/goals — the
        focus-icon subset, not every UI sprite. Cached after first build."""
        if self._focus_sprites is None:
            if not self._index_built:
                self._build_index()
            out = []
            for _lower, (name, path) in self._index.items():
                if name.lower().endswith("_shine"):
                    continue  # MD defines <name>_shine on the same .dds — skip dupes
                low = path.lower()
                if "goals" in low and "interface" in low:
                    out.append((name, path))
            out.sort(key=lambda t: t[0].lower())
            self._focus_sprites = out
        return self._focus_sprites

    def idea_sprites(self) -> list:
        """Sorted [(GFX_name, abs_path)] for idea/national-spirit icons
        (GFX_idea_*). Cached after first build."""
        if self._idea_sprites is None:
            if not self._index_built:
                self._build_index()
            out = []
            for _lower, (name, path) in self._index.items():
                low = name.lower()
                if low.startswith("gfx_idea_") and not low.endswith("_shine"):
                    out.append((name, path))
            out.sort(key=lambda t: t[0].lower())
            self._idea_sprites = out
        return self._idea_sprites

    def leader_portraits(self, tag: str) -> list:
        """[(relpath, abspath, label)] of the country's MD leader portrait images
        (gfx/leaders/<TAG>/*.dds, mod roots only); cached per tag."""
        t = (tag or "").strip().upper()
        if not t:
            return []
        if t not in self._leader_portraits:
            self._leader_portraits[t] = build_leader_portraits(self._roots, t)
        return self._leader_portraits[t]

    def portrait_pixmap(self, relpath: str):
        """QPixmap for a stored portrait relpath (gfx/leaders/...dds), or None."""
        if not relpath:
            return None
        key = relpath.lower()
        if key in self._portrait_cache:
            return self._portrait_cache[key]
        pm = None
        path = resolve_portrait(self._roots, relpath)
        if path:
            img = load_dds_qimage(path)
            if img is not None and not img.isNull():
                pm = QPixmap.fromImage(img)
        self._portrait_cache[key] = pm
        return pm

    def has_icons(self) -> bool:
        return self.sprite_count() > 0

    def sprite_count(self) -> int:
        if not self._index_built:
            self._build_index()
        return len(self._index)

    def pixmap(self, icon_value: str):
        """Return a QPixmap for the focus icon, or None if unavailable."""
        if not icon_value or not self._roots:
            return None
        key = icon_value.lower()
        if key in self._cache:
            return self._cache[key]
        if not self._index_built:
            self._build_index()
        path = resolve_sprite(self._index, icon_value)
        pm = None
        if path and os.path.isfile(path):
            img = load_dds_qimage(path)
            if img is not None and not img.isNull():
                pm = QPixmap.fromImage(img)
        self._cache[key] = pm
        return pm


_INSTANCE = None


def provider() -> IconProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = IconProvider()
    return _INSTANCE
