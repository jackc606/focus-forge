"""Shared HOI4 English-localisation lookup.

HOI4 stores every language under ``localisation/<lang>/`` with the SAME keys, so
reading any ``.yml`` picks up other languages. Read ONLY ``*_l_english.yml``;
later roots win (mod load order).
"""
from __future__ import annotations

import os
import re

_LOC_LINE = re.compile(r'^\s*([A-Za-z0-9_.]+):\d*\s*"(.*)"\s*$')


def _read_loc_lines(path: str) -> list:
    """Decode a localisation file: UTF-8-BOM per HOI4 spec, falling back to
    cp1252 (old vanilla / legacy mods) instead of mangling accents to U+FFFD."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8-sig", errors="replace").splitlines()


def load_english_localisation(roots, needed: set) -> dict:
    """Return {key: value} for the requested keys, English only.

    Walks roots in REVERSE (a later root overrides an earlier one — mod load
    order) so the search can stop as soon as every requested key is found,
    instead of always scanning every root's full localisation tree."""
    found: dict = {}
    remaining = set(needed)
    for root in reversed(list(roots)):
        if not remaining:
            break
        loc = os.path.join(root, "localisation")
        if not os.path.isdir(loc):
            continue
        root_found: dict = {}
        for dirpath, _d, files in os.walk(loc):
            for fn in files:
                if not fn.lower().endswith("_l_english.yml"):
                    continue
                for line in _read_loc_lines(os.path.join(dirpath, fn)):
                    mm = _LOC_LINE.match(line)
                    if mm and mm.group(1) in remaining:
                        root_found[mm.group(1)] = mm.group(2)  # last wins within a root
        found.update(root_found)
        remaining -= root_found.keys()
    return found
