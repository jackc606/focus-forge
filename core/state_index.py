"""Index HOI4 states from ``history/states/*.txt`` so the editor can offer a
country's states (with names) for state-scoped rewards.

Each state file: ``state = { id = N  name = "STATE_N"  history = { owner = TAG … } }``.
Names are loc keys resolved English-only. Later roots override earlier by state
id (mod load order)."""
from __future__ import annotations

import glob
import os
import re

from .pdx_loc import load_english_localisation

_COMMENT = re.compile(r"#.*")
_STATE_START = re.compile(r"\bstate\s*=\s*\{", re.IGNORECASE)
_ID = re.compile(r"\bid\s*=\s*(\d+)")
_NAME = re.compile(r'\bname\s*=\s*"?(\w+)"?')
_OWNER = re.compile(r"\bowner\s*=\s*([A-Za-z0-9]{3})")


def _match_brace(text: str, open_idx: int) -> int:
    depth = 0
    n = len(text)
    j = open_idx
    while j < n:
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return n


def build_state_index(roots) -> dict:
    """{state_id: {"owner": TAG, "name_key": str}} — later roots win."""
    index: dict = {}
    for root in roots:
        sd = os.path.join(root, "history", "states")
        if not os.path.isdir(sd):
            continue
        for fp in glob.glob(os.path.join(sd, "*.txt")):
            try:
                with open(fp, "r", encoding="utf-8-sig", errors="replace") as f:
                    raw = f.read()
            except OSError:
                continue
            text = _COMMENT.sub("", raw)
            for m in _STATE_START.finditer(text):
                brace = m.end() - 1
                end = _match_brace(text, brace)
                block = text[brace + 1:end]
                idm = _ID.search(block)
                if not idm:
                    continue
                sid = int(idm.group(1))
                nm = _NAME.search(block)
                owm = _OWNER.search(block)
                index[sid] = {
                    "owner": owm.group(1).upper() if owm else "",
                    "name_key": nm.group(1) if nm else f"STATE_{sid}",
                }
    return index


def states_for_owner(index: dict, tag: str) -> list:
    """[(id, name_key)] owned by tag, sorted by id."""
    t = (tag or "").strip().upper()
    if not t:
        return []
    out = [(sid, info["name_key"]) for sid, info in index.items() if info["owner"] == t]
    out.sort(key=lambda s: s[0])
    return out


def resolve_states(roots, tag: str) -> list:
    """[(id, "id — Name")] for the country's states, sorted by display name."""
    index = build_state_index(roots)
    owned = states_for_owner(index, tag)
    if not owned:
        return []
    loc = load_english_localisation(roots, {k for _sid, k in owned})
    labelled = []
    for sid, key in owned:
        name = loc.get(key, key)
        labelled.append((sid, f"{sid} — {name}"))
    labelled.sort(key=lambda s: s[1].lower())
    return labelled
