"""Shared HOI4 English-localisation lookup.

HOI4 stores every language under ``localisation/<lang>/`` with the SAME keys, so
reading any ``.yml`` picks up other languages. Read ONLY ``*_l_english.yml``;
later roots win (mod load order).
"""
from __future__ import annotations

import os
import re

_LOC_LINE = re.compile(r'^\s*([A-Za-z0-9_.]+):\d*\s*"(.*)"\s*$')


def load_english_localisation(roots, needed: set) -> dict:
    """Return {key: value} for the requested keys, English only."""
    found = {}
    for root in roots:
        loc = os.path.join(root, "localisation")
        if not os.path.isdir(loc):
            continue
        for dirpath, _d, files in os.walk(loc):
            for fn in files:
                if not fn.lower().endswith("_l_english.yml"):
                    continue
                try:
                    with open(os.path.join(dirpath, fn), "r", encoding="utf-8-sig",
                              errors="replace") as f:
                        for line in f:
                            mm = _LOC_LINE.match(line)
                            if mm and mm.group(1) in needed:
                                found[mm.group(1)] = mm.group(2)  # last wins
                except OSError:
                    continue
    return found
