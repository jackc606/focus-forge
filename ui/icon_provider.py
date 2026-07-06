"""App-wide provider of in-game focus icons.

Scans configured HOI4 / mod roots for ``interface/*.gfx`` sprite definitions,
resolves a focus's ``icon`` value to its ``.dds``, decodes it (pure-Python), and
hands back a cached ``QPixmap``. Roots persist across sessions via ``QSettings``.

Nodes query the singleton via ``provider()``. Signals:

- ``roots_changed`` — the configured roots (and therefore every derived index)
  genuinely changed. The lazy game-data providers (tech/trait/state/country)
  listen to THIS to invalidate their caches.
- ``icons_warmed`` — a background icon warm finished decoding; caches are intact.
- ``changed`` — fires for BOTH of the above: "something visual may look
  different, repaint". The canvas / icon previews listen to this. A warm
  completion must never invalidate the data providers (it used to, wiping the
  startup warm-up and freezing the first dropdown click), so they must NOT
  subscribe to ``changed``.
"""
from __future__ import annotations

import os
import re
import threading

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QPixmap

from core.gfx_index import build_sprite_index, resolve_sprite
from core.portrait_index import build_leader_portraits, resolve_portrait

from .dds_image import load_dds_qimage

# Decoded-pixmap cache caps. Focus icons are small (~35 KB each) but the same
# cache also holds event-picture banners (~300 KB); portraits are ~130 KB.
# Caps keep a long editing session from growing memory without bound.
_PIXMAP_CACHE_MAX = 256
_PORTRAIT_CACHE_MAX = 64


def _cache_put(cache: dict, key, value, cap: int) -> None:
    """Insert with FIFO eviction once the cache reaches ``cap`` entries."""
    if key not in cache and len(cache) >= cap:
        cache.pop(next(iter(cache)))
    cache[key] = value


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
    # "Repaint" signal: anything visual may have changed (roots OR warm finish).
    changed = Signal()
    # Genuine root/index changes only — cache-invalidation for data providers.
    roots_changed = Signal()
    # A background icon warm finished decoding (subset of `changed`).
    icons_warmed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("FocusForge", "FocusForge")
        self._roots: list = list(self._settings.value("icon_roots", []) or [])
        # Transient roots added for the current session only (e.g. a mod folder
        # the user imported a focus tree from ad-hoc) — NOT persisted to QSettings.
        self._extra_roots: list = []
        self._index: dict = {}
        self._cache: dict = {}      # icon_value(lower) -> QPixmap or None
        # Decoded DDS images (the slow, pure-Python part) keyed icon_value(lower)
        # -> QImage or None. A background thread fills this so the GUI thread only
        # does the cheap QImage→QPixmap conversion instead of decoding inline.
        self._qimage_cache: dict = {}
        self._warming_icons = False
        self._icon_warm_thread = None
        self._focus_sprites = None  # cached [(name, path)] under interface/goals
        self._idea_sprites = None   # cached [(name, path)] for GFX_idea_*
        self._event_sprites = None  # cached [(name, path)] under gfx/event_pictures
        self._decision_sprites = None       # cached GFX_decision_* (icons)
        self._decision_cat_sprites = None   # cached GFX_decision_category_*
        self._leader_portraits: dict = {}  # tag -> [(relpath, abspath, label)]
        self._portrait_cache: dict = {}    # relpath(lower) -> QPixmap or None
        self._party_logos: dict = {}       # tag -> [(GFX_name, abspath)]
        self._index_built = False
        self._index_lock = threading.Lock()
        self._index_gen = 0  # bumped on roots change so a stale build is discarded
        self._index_thread = None

    # ----- roots -----
    def roots(self) -> list:
        return list(self._roots)

    def _all_roots(self) -> list:
        """Persisted roots plus any transient session roots (load order: extras
        last, so an imported submod's icons override the base game/MD)."""
        return self._roots + [r for r in self._extra_roots if r not in self._roots]

    def _reset_caches(self) -> None:
        self._index_gen += 1  # invalidate any in-flight background build
        self._index_built = False
        self._index = {}
        self._cache = {}
        self._qimage_cache = {}
        self._warming_icons = False
        self._focus_sprites = None
        self._idea_sprites = None
        self._event_sprites = None
        self._decision_sprites = None
        self._decision_cat_sprites = None
        self._leader_portraits = {}
        self._portrait_cache = {}
        self._party_logos = {}

    def set_roots(self, roots) -> None:
        self._roots = [r for r in roots if r]
        self._settings.setValue("icon_roots", self._roots)
        self._reset_caches()
        self.roots_changed.emit()
        self.changed.emit()

    def add_extra_roots(self, roots) -> None:
        """Add transient session roots (e.g. an ad-hoc imported mod folder) so
        their custom icons resolve, without persisting them to Settings. No-op if
        nothing new is added."""
        added = False
        for r in roots:
            if r and r not in self._roots and r not in self._extra_roots:
                self._extra_roots.append(r)
                added = True
        if added:
            self._reset_caches()
            self.roots_changed.emit()
            self.changed.emit()

    def ensure_default_roots(self) -> None:
        """On first run with no config, seed from autodetection (if anything found)."""
        if not self._roots:
            auto = autodetect_roots()
            if auto:
                self.set_roots(auto)

    # ----- lookup -----
    def _build_index(self) -> None:
        # Serialized: the background warm-up and a first-paint fallback may
        # arrive together; whoever loses the race finds the index built and
        # returns. A roots change mid-build bumps the generation so the stale
        # result is discarded instead of published.
        with self._index_lock:
            if self._index_built:
                return
            gen = self._index_gen
            index = build_sprite_index(self._all_roots())
            if gen == self._index_gen:
                self._index = index
                self._index_built = True

    def warm_index_async(self) -> None:
        """Build the sprite index on a background thread so the first canvas
        paint / icon lookup doesn't freeze the UI scanning every root's .gfx
        files. Pure file I/O + parsing — no Qt GUI objects are touched."""
        if self._index_built or not self._all_roots():
            return
        if self._index_thread is not None and self._index_thread.is_alive():
            return
        self._index_thread = threading.Thread(
            target=self._build_index, name="focusforge-icon-index", daemon=True)
        self._index_thread.start()

    def is_indexed(self) -> bool:
        return self._index_built

    def sprite_exists(self, icon_value: str):
        """True/False once the index is built; None while it isn't (validation
        skips the warning rather than guessing). Never triggers a build."""
        if not self._index_built or not self._all_roots() or not icon_value:
            return None
        return resolve_sprite(self._index, icon_value) is not None

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

    def decision_icon_sprites(self) -> list:
        """Sorted [(GFX_name, abs_path)] for decision icons (GFX_decision_*,
        excluding the category banners). Cached after first build."""
        if self._decision_sprites is None:
            if not self._index_built:
                self._build_index()
            out = []
            for _lower, (name, path) in self._index.items():
                low = name.lower()
                if (low.startswith("gfx_decision_")
                        and not low.startswith("gfx_decision_category_")
                        and not low.endswith("_shine")):
                    out.append((name, path))
            out.sort(key=lambda t: t[0].lower())
            self._decision_sprites = out
        return self._decision_sprites

    def decision_category_sprites(self) -> list:
        """Sorted [(GFX_name, abs_path)] for decision-category icons."""
        if self._decision_cat_sprites is None:
            if not self._index_built:
                self._build_index()
            out = []
            for _lower, (name, path) in self._index.items():
                low = name.lower()
                if low.startswith("gfx_decision_category_") and not low.endswith("_shine"):
                    out.append((name, path))
            out.sort(key=lambda t: t[0].lower())
            self._decision_cat_sprites = out
        return self._decision_cat_sprites

    def event_picture_sprites(self) -> list:
        """Sorted [(GFX_name, abs_path)] for event pictures (sprites whose texture
        lives under gfx/event_pictures). Cached after first build."""
        if self._event_sprites is None:
            if not self._index_built:
                self._build_index()
            out = []
            for _lower, (name, path) in self._index.items():
                if name.lower().endswith("_shine"):
                    continue
                if "event_pictures" in path.lower().replace("\\", "/"):
                    out.append((name, path))
            out.sort(key=lambda t: t[0].lower())
            self._event_sprites = out
        return self._event_sprites

    def party_logos(self, tag: str) -> list:
        """Sorted [(GFX_name, abs_path)] of a country's MD party-logo sprites
        (under gfx/texticons/parties_icons, named GFX_<TAG>_…). Cached per tag."""
        t = (tag or "").strip().upper()
        if not t:
            return []
        if t not in self._party_logos:
            if not self._index_built:
                self._build_index()
            pref = f"gfx_{t.lower()}_"
            out = []
            for _lower, (name, path) in self._index.items():
                low = name.lower()
                if ("parties_icons" in path.lower() and low.startswith(pref)
                        and not low.endswith("_shine")):
                    out.append((name, path))
            out.sort(key=lambda x: x[0].lower())
            self._party_logos[t] = out
        return self._party_logos[t]

    def leader_portraits(self, tag: str) -> list:
        """[(relpath, abspath, label)] of the country's MD leader portrait images
        (gfx/leaders/<TAG>/*.dds, mod roots only); cached per tag."""
        t = (tag or "").strip().upper()
        if not t:
            return []
        if t not in self._leader_portraits:
            self._leader_portraits[t] = build_leader_portraits(self._all_roots(), t)
        return self._leader_portraits[t]

    def portrait_pixmap(self, relpath: str):
        """QPixmap for a stored portrait relpath (gfx/leaders/...dds), or None."""
        if not relpath:
            return None
        key = relpath.lower()
        if key in self._portrait_cache:
            return self._portrait_cache[key]
        pm = None
        path = resolve_portrait(self._all_roots(), relpath)
        if path:
            img = load_dds_qimage(path)
            if img is not None and not img.isNull():
                pm = QPixmap.fromImage(img)
        _cache_put(self._portrait_cache, key, pm, _PORTRAIT_CACHE_MAX)
        return pm

    def has_icons(self) -> bool:
        return self.sprite_count() > 0

    def sprite_count(self) -> int:
        if not self._index_built:
            self._build_index()
        return len(self._index)

    def _decode_qimage(self, icon_value: str):
        """Resolve + decode an icon's .dds to a QImage (the slow part). Safe to
        call off the GUI thread — QImage isn't GUI-affine; only QPixmap is."""
        if not self._index_built:
            self._build_index()
        path = resolve_sprite(self._index, icon_value)
        if path and os.path.isfile(path):
            img = load_dds_qimage(path)
            if img is not None and not img.isNull():
                return img
        return None

    def _pixmap_from_qimage(self, key: str, img):
        pm = QPixmap.fromImage(img) if (img is not None and not img.isNull()) else None
        _cache_put(self._cache, key, pm, _PIXMAP_CACHE_MAX)
        return pm

    def pixmap(self, icon_value: str):
        """Return a QPixmap for the focus icon, or None if unavailable.

        While a background icon warm is running, an icon that isn't decoded yet
        returns None (the node shows its abbreviation fallback) rather than
        blocking the GUI thread on a pure-Python DDS decode; ``changed`` fires
        when the warm finishes so the canvas repaints with the real icons."""
        if not icon_value or not self._all_roots():
            return None
        key = icon_value.lower()
        if key in self._cache:
            return self._cache[key]
        if key in self._qimage_cache:
            return self._pixmap_from_qimage(key, self._qimage_cache[key])
        if self._warming_icons:
            return None  # defer to the background warm — don't freeze the UI
        img = self._decode_qimage(icon_value)
        self._qimage_cache[key] = img
        return self._pixmap_from_qimage(key, img)

    def warm_focus_icons_async(self, icon_values) -> None:
        """Pre-decode a project's focus icons on a background thread so the first
        canvas paint of a large tree doesn't decode hundreds of .dds files inline
        (a multi-second freeze). No-op once they're all cached, so it's cheap to
        call on every project change."""
        if self._warming_icons or not self._all_roots():
            return
        pending = [v for v in dict.fromkeys(icon_values)
                   if v and v.lower() not in self._qimage_cache and v.lower() not in self._cache]
        if not pending:
            return
        self._warming_icons = True
        gen = self._index_gen

        def work():
            try:
                for v in pending:
                    if gen != self._index_gen:
                        return  # roots changed — abandon this stale warm
                    key = v.lower()
                    if key not in self._qimage_cache:
                        self._qimage_cache[key] = self._decode_qimage(v)
            finally:
                self._warming_icons = False
                # NOT roots_changed: warming decodes pixmaps, it invalidates
                # nothing — the data providers' caches must survive this.
                self.icons_warmed.emit()
                self.changed.emit()  # GUI repaints; deferred icons now resolve

        self._icon_warm_thread = threading.Thread(
            target=work, name="focusforge-icon-warm", daemon=True)
        self._icon_warm_thread.start()


_INSTANCE = None


def provider() -> IconProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = IconProvider()
    return _INSTANCE
