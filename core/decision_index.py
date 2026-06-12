"""Index existing decision-category ids from the configured game roots
(common/decisions/categories/*.txt) so the decision editor can offer MD's real
categories alongside the project's custom ones.
"""
from __future__ import annotations

import os
import re

_COMMENT = re.compile(r"#.*")
# Top-level blocks only: id at the start of a line (category files never nest
# category definitions).
_CATEGORY_ID = re.compile(r"(?m)^([A-Za-z0-9_]+)\s*=\s*\{")


def build_decision_categories(roots) -> list:
    """Sorted category ids across all roots (later roots add to the set)."""
    ids: set = set()
    for root in roots:
        folder = os.path.join(root, "common", "decisions", "categories")
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if not fn.lower().endswith(".txt"):
                continue
            try:
                with open(os.path.join(folder, fn), "r",
                          encoding="utf-8-sig", errors="replace") as f:
                    text = _COMMENT.sub("", f.read())
            except OSError:
                continue
            for m in _CATEGORY_ID.finditer(text):
                ids.add(m.group(1))
    return sorted(ids)
