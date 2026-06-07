"""Index Millennium Dawn leader PORTRAIT IMAGE files (gfx/leaders/<TAG>/*.dds) so
the Country editor can offer a country's real MD portraits.

Most MD leaders have no GFX sprite *name* — only an image file — so we scan the
image files directly. We only look under roots that have a ``descriptor.mod``
(i.e. MD + submods); the base game has none, so vanilla portraits are excluded.
The chosen portrait is wrapped in a generated spriteType on export.
"""
from __future__ import annotations

import glob
import os


def _mod_roots(roots) -> list:
    """Roots that are mods (have a descriptor.mod) — excludes the base game."""
    return [r for r in roots
            if r and os.path.isfile(os.path.join(r, "descriptor.mod"))]


def build_leader_portraits(roots, tag: str) -> list:
    """[(relpath, abspath, label)] for a country's MD leader portraits.

    ``relpath`` is the posix ``gfx/leaders/<TAG>/<file>.dds`` (what an exported
    spriteType references); ``label`` is the filename stem. Top-level files only
    (the ``small/`` thumbnails are skipped). Later mod roots override by relpath.
    """
    t = (tag or "").strip().upper()
    if not t:
        return []
    by_rel: dict = {}
    for root in _mod_roots(roots):
        d = os.path.join(root, "gfx", "leaders", t)
        if not os.path.isdir(d):
            continue
        for fp in glob.glob(os.path.join(d, "*.dds")):
            fn = os.path.basename(fp)
            rel = f"gfx/leaders/{t}/{fn}"
            by_rel[rel] = (rel, os.path.normpath(fp), fn.rsplit(".", 1)[0])
    return sorted(by_rel.values(), key=lambda x: x[2].lower())


def resolve_portrait(roots, relpath: str):
    """Absolute path for a stored portrait relpath, or None — searches mod roots
    first (so a submod override wins) then any root."""
    rel = (relpath or "").replace("\\", "/").strip("/")
    if not rel:
        return None
    for root in list(_mod_roots(roots)) + list(roots):
        cand = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(cand):
            return cand
    return None
