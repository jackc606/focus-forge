"""List existing country flag TGAs (for the preset flag picker) and resolve a
country's default in-game flag."""
from __future__ import annotations

import os

# HOI4 flags are <TAG>_<ideology>.tga (the flag shown depends on the ruling
# ideology); a plain <TAG>.tga is the fallback base flag.
_IDEO_FALLBACK = ("neutrality", "democratic", "communism", "fascism", "nationalist")


def default_flag(roots, tag: str, ideology: str = ""):
    """Absolute path of the flag a country shows at game start, or None.

    Prefers ``<TAG>_<ruling ideology>.tga``, then the base ``<TAG>.tga``, then any
    ideology variant. Later roots win (mod load order)."""
    t = (tag or "").strip().upper()
    if not t:
        return None
    ideo = (ideology or "").strip().lower()
    candidates = ([f"{t}_{ideo}.tga"] if ideo else []) + [f"{t}.tga"]
    candidates += [f"{t}_{i}.tga" for i in _IDEO_FALLBACK]
    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        hit = None
        for root in roots:
            p = os.path.join(root, "gfx", "flags", cand)
            if os.path.isfile(p):
                hit = p  # last root wins
        if hit:
            return hit
    return None


def flag_files(roots) -> list:
    """Sorted [(name, abs_path)] of large flags in gfx/flags/*.tga across roots
    (later roots override by name — mod load order)."""
    by_name = {}
    for root in roots:
        fd = os.path.join(root, "gfx", "flags")
        if not os.path.isdir(fd):
            continue
        try:
            entries = os.listdir(fd)
        except OSError:
            continue
        for fn in entries:
            if fn.lower().endswith(".tga"):
                by_name[fn[:-4]] = os.path.join(fd, fn)
    return sorted(by_name.items())
