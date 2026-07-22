"""Index HOI4/MD technologies, grouped by research folder (the research-screen
tabs), with English names — for the "Has technology" availability dropdown."""
from __future__ import annotations

import glob
import os
import re

from .mod_paths import effective_roots_for_path
from .pdx_loc import load_english_localisation

_COMMENT = re.compile(r"#.*")
_TECHS_BLOCK = re.compile(r"\btechnologies\s*=\s*\{")
_CATEGORIES_BLOCK = re.compile(r"\btechnology_categories\s*=\s*\{", re.IGNORECASE)
_CAT_TOKEN = re.compile(r"\bCAT_\w+")
_BUILDINGS_BLOCK = re.compile(r"\bbuildings\s*=\s*\{", re.IGNORECASE)
_OPINION_BLOCK = re.compile(r"\bopinion_modifiers\s*=\s*\{", re.IGNORECASE)
_VALUE = re.compile(r"\bvalue\s*=\s*(-?\d+(?:\.\d+)?)")
_TECH_START = re.compile(r"([A-Za-z0-9_]+)\s*=\s*\{")
_FOLDER = re.compile(r"\bfolder\s*=\s*\{[^}]*?\bname\s*=\s*(\w+)")

# Pretty labels for the research folders (research-screen tabs).
_FOLDER_LABELS = {
    "infantry_folder": "Infantry",
    "armour_folder": "Armour",
    "nsb_armour_folder": "Armour (NSB)",
    "artillery_folder": "Artillery",
    "air_techs_folder": "Air",
    "fixed_wing_folder": "Fixed Wing",
    "bba_aircraft_folder": "Aircraft",
    "bomber_folder": "Bombers",
    "naval_folder": "Naval",
    "civilian_folder": "Industry & Civilian",
    "electronics_folder": "Electronics",
    "cruise_missiles_folder": "Cruise Missiles",
    "missile_non_got_folder": "Missiles",
    "space_folder": "Space",
}
_GROUP_ORDER = [
    "Industry & Civilian", "Infantry", "Artillery", "Armour", "Armour (NSB)",
    "Air", "Fixed Wing", "Aircraft", "Bombers", "Naval", "Cruise Missiles",
    "Missiles", "Electronics", "Space",
]


def _match_brace(text: str, open_idx: int) -> int:
    # Best-effort: unbalanced braces (malformed file) return ``n``, so the
    # caller's slice covers the rest of the file — oversized but never crashes,
    # and the per-line regex extraction still finds what it can.
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


def _folder_label(folder: str) -> str:
    if folder in _FOLDER_LABELS:
        return _FOLDER_LABELS[folder]
    return folder.replace("_folder", "").replace("_", " ").strip().title() or "Other"


def build_tech_index(roots) -> dict:
    """{tech_id: folder_name} across the effective tech roots (later overrides)."""
    index: dict = {}
    for root in effective_roots_for_path(roots, "common/technologies"):
        td = os.path.join(root, "common", "technologies")
        if not os.path.isdir(td):
            continue
        for fp in glob.glob(os.path.join(td, "*.txt")):
            try:
                raw = open(fp, "r", encoding="utf-8-sig", errors="replace").read()
            except OSError:
                continue
            text = _COMMENT.sub("", raw)
            bm = _TECHS_BLOCK.search(text)
            if not bm:
                continue
            brace = text.index("{", bm.start())
            body = text[brace + 1:_match_brace(text, brace)]
            i = 0
            while True:
                tm = _TECH_START.search(body, i)
                if not tm:
                    break
                tid = tm.group(1)
                bstart = tm.end() - 1
                bend = _match_brace(body, bstart)
                block = body[bstart + 1:bend]
                if tid not in ("path", "folder", "categories", "ai_will_do", "dependencies"):
                    fm = _FOLDER.search(block)
                    index[tid] = fm.group(1) if fm else ""
                i = bend + 1
    return index


_IDEA_TOKEN = re.compile(r"([A-Za-z0-9_.\-]+)\s*=\s*\{|\{|\}")


def build_known_idea_ids(roots) -> set:
    """Every idea id defined by the game/MD roots (common/ideas): the names
    that open a block at nesting depth 2 — ``ideas = { <slot> = { <ID> = {``.
    Union across roots. Used to keep validation from flagging focus rewards
    that grant base-mod ideas (only project-missing + game-missing warns)."""
    ids = set()
    for root in roots:
        d = os.path.join(root, "common", "ideas")
        if not os.path.isdir(d):
            continue
        for fp in glob.glob(os.path.join(d, "*.txt")):
            try:
                text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                             errors="replace").read())
            except OSError:
                continue
            depth = 0
            for m in _IDEA_TOKEN.finditer(text):
                if m.group(1):
                    if depth == 2:
                        ids.add(m.group(1))
                    depth += 1
                elif m.group(0) == "{":
                    depth += 1
                else:
                    depth = max(0, depth - 1)
    return ids


def build_tech_categories(roots) -> list:
    """Sorted unique CAT_* technology categories from common/technology_tags
    (for add_tech_bonus). technology_tags isn't replace_path'd → union all roots."""
    cats = set()
    for root in roots:
        td = os.path.join(root, "common", "technology_tags")
        if not os.path.isdir(td):
            continue
        for fp in glob.glob(os.path.join(td, "*.txt")):
            try:
                text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                             errors="replace").read())
            except OSError:
                continue
            bm = _CATEGORIES_BLOCK.search(text)
            if not bm:
                continue
            brace = text.index("{", bm.start())
            body = text[brace + 1:_match_brace(text, brace)]
            cats.update(_CAT_TOKEN.findall(body))
    return sorted(cats)


def build_building_types(roots) -> list:
    """Sorted unique building ids from common/buildings (for add_building_construction
    / building checks). Not replace_path'd → union all roots."""
    names = set()
    for root in roots:
        bd = os.path.join(root, "common", "buildings")
        if not os.path.isdir(bd):
            continue
        for fp in glob.glob(os.path.join(bd, "*.txt")):
            try:
                text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                             errors="replace").read())
            except OSError:
                continue
            m = _BUILDINGS_BLOCK.search(text)
            if not m:
                continue
            brace = text.index("{", m.start())
            body = text[brace + 1:_match_brace(text, brace)]
            i = 0
            while True:
                tm = _TECH_START.search(body, i)
                if not tm:
                    break
                bs = tm.end() - 1
                be = _match_brace(body, bs)
                names.add(tm.group(1))
                i = be + 1
    return sorted(names)


def build_building_list(roots) -> list:
    """[(building_id, display_name)] — ids from common/buildings paired with their
    English names so the dropdown is searchable by in-game name (e.g. air_facility
    -> "Aerodynamics & Avionics Facility", nuclear_facility -> "Civilian R&D
    Facility"). Falls back to a prettified id when a building has no loc. Sorted
    by display name."""
    ids = build_building_types(roots)
    if not ids:
        return []
    loc = load_english_localisation(roots, set(ids))
    out = [(b, loc.get(b) or b.replace("_", " ").title()) for b in ids]
    out.sort(key=lambda t: t[1].lower())
    return out


def build_opinion_modifiers(roots) -> list:
    """[(modifier_id, value)] from common/opinion_modifiers (for add_opinion_modifier).
    ``value`` is a float (the modifier's opinion amount) or None when undeclared.
    Not replace_path'd → union all roots, later roots override by id. Sorted by id."""
    found: dict = {}
    for root in roots:
        od = os.path.join(root, "common", "opinion_modifiers")
        if not os.path.isdir(od):
            continue
        for fp in glob.glob(os.path.join(od, "*.txt")):
            try:
                text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                             errors="replace").read())
            except OSError:
                continue
            for wm in _OPINION_BLOCK.finditer(text):
                brace = text.index("{", wm.start())
                body = text[brace + 1:_match_brace(text, brace)]
                i = 0
                while True:
                    tm = _TECH_START.search(body, i)
                    if not tm:
                        break
                    bs = tm.end() - 1
                    be = _match_brace(body, bs)
                    block = body[bs + 1:be]
                    vm = _VALUE.search(block)
                    found[tm.group(1)] = float(vm.group(1)) if vm else None
                    i = be + 1
    return sorted(found.items(), key=lambda kv: kv[0].lower())


def build_tech_groups(roots) -> list:
    """[(group_label, [(tech_id, display_name)])] sorted for navigation."""
    index = build_tech_index(roots)
    if not index:
        return []
    loc = load_english_localisation(roots, set(index.keys()))
    by_group: dict = {}
    for tid, folder in index.items():
        label = _folder_label(folder) if folder else "Other"
        by_group.setdefault(label, []).append((tid, loc.get(tid, tid)))
    ordered = []
    for label in _GROUP_ORDER:
        if label in by_group:
            ordered.append((label, sorted(by_group.pop(label), key=lambda t: t[1].lower())))
    for label in sorted(by_group):
        if label == "Other":
            continue
        ordered.append((label, sorted(by_group[label], key=lambda t: t[1].lower())))
    if "Other" in by_group:
        ordered.append(("Other", sorted(by_group["Other"], key=lambda t: t[1].lower())))
    return ordered
