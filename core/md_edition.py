"""Millennium Dawn *editions* — the main release vs the public beta.

Focus Forge reads game data from, and exports script for, ONE Millennium Dawn
base mod at a time. The two editions ship as separate Steam Workshop items with
different dependency names, different supported HOI4 versions and a few renamed
or removed scripted-effect helpers. Everything edition-specific lives here so the
rest of the app asks ``active_edition()`` instead of hardcoding main-branch facts.

Two notions, deliberately separate:

* The **project's** edition (``FocusForgeProject.mdEdition``) — what the export
  targets. Saved in the project file; defaults to ``"main"`` so every existing
  project keeps exporting byte-identical output.
* The **active** edition — a process-wide context the UI sets from the open
  project (and the exporter sets for the duration of an export). Reward-preset
  builders consult it so the inspector preview and the exported file agree.

The edition of the *configured game-data roots* is detected from the MD folder's
``descriptor.mod``; the main window keeps roots and project in step.
"""
from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MDEdition:
    key: str                 # "main" | "beta" — stored in project files
    label: str               # short UI label
    workshop_id: str         # Steam Workshop item id (HOI4 appid 394360)
    dependency: str          # exact descriptor.mod `name` to depend on
    supported_version: str   # HOI4 version the edition targets
    # Scripted-effect helper that shifts one party's relative popularity
    # (inputs party_index / party_popularity_increase / temp_outlook_increase
    # are identical in both editions; only the helper's name changed).
    party_popularity_effect: str
    # The beta removed the counter-terror radicalization system, so its
    # `modify_radicalization_effect` helper no longer exists.
    has_radicalization: bool


MAIN = MDEdition(
    key="main",
    label="Millennium Dawn",
    workshop_id="2777392649",
    dependency="Millennium Dawn: A Modern Day Mod",
    supported_version="1.17.*",
    party_popularity_effect="add_relative_party_popularity",
    has_radicalization=True,
)

BETA = MDEdition(
    key="beta",
    label="Millennium Dawn Beta",
    workshop_id="3374271790",
    dependency="Millennium Dawn: A Beta Test Mod",
    supported_version="1.19.*",
    party_popularity_effect="change_relative_party_popularity",
    has_radicalization=False,
)

EDITIONS = [MAIN, BETA]
EDITIONS_BY_KEY = {e.key: e for e in EDITIONS}
DEFAULT_EDITION = MAIN

# Every helper name any edition uses for the same preset, so importers accept
# script written for either edition.
PARTY_POPULARITY_EFFECTS = tuple(e.party_popularity_effect for e in EDITIONS)


def edition(key) -> MDEdition:
    """The edition for a stored key; unknown/blank keys fall back to main so an
    old or hand-edited project file never breaks."""
    return EDITIONS_BY_KEY.get((key or "").strip().lower(), DEFAULT_EDITION)


# ---------------------------------------------------------------------------
# Detection from an MD folder / configured roots
# ---------------------------------------------------------------------------
_NAME_RX = re.compile(r'^\s*name\s*=\s*"([^"]*)"', re.MULTILINE)
_REMOTE_RX = re.compile(r'^\s*remote_file_id\s*=\s*"?(\d+)"?', re.MULTILINE)


def _read_descriptor(root: str) -> str:
    desc = os.path.join(root or "", "descriptor.mod")
    if not os.path.isfile(desc):
        return ""
    try:
        return open(desc, "r", encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return ""


def edition_of_root(root: str):
    """The MD edition a mod folder IS (not depends on), or None if the folder
    isn't a Millennium Dawn base mod. Matches the workshop id first (folder name
    or remote_file_id), then the descriptor name — a copy of MD installed
    anywhere (a local checkout, another drive) is still recognised."""
    if not root:
        return None
    base = os.path.basename(os.path.normpath(root))
    for e in EDITIONS:
        if base == e.workshop_id:
            return e
    text = _read_descriptor(root)
    if not text:
        return None
    m = _REMOTE_RX.search(text)
    if m:
        for e in EDITIONS:
            if m.group(1) == e.workshop_id:
                return e
    m = _NAME_RX.search(text)
    name = (m.group(1) if m else "").strip().lower()
    if not name.startswith("millennium dawn"):
        return None
    if "dependencies" in text and "millennium dawn" in text.lower().split("dependencies", 1)[1]:
        return None  # a SUBMOD that depends on MD, not MD itself
    # Forks / re-uploads: a base mod ships the ideology definitions; submods
    # named "Millennium Dawn: <Country>" never do.
    if not os.path.isdir(os.path.join(root, "common", "ideologies")):
        return None
    return BETA if "beta" in name else MAIN


def md_roots(roots) -> list:
    """(root, edition) for every configured root that is an MD base mod."""
    out = []
    for r in roots or []:
        e = edition_of_root(r)
        if e is not None:
            out.append((r, e))
    return out


def edition_of_roots(roots):
    """The edition of the configured game-data roots: the LAST MD base mod in
    load order wins (later roots override earlier ones). None if no MD root."""
    found = md_roots(roots)
    return found[-1][1] if found else None


def roots_with_md_root(roots, new_md_root: str) -> list:
    """The root list with every MD base-mod folder replaced by ``new_md_root``
    (kept at the position of the first one, so it still sits above the user's
    submods in load order). With no MD root present it goes right after the base
    game (index 1), or first if the list is empty. Pure — the caller persists."""
    roots = [r for r in (roots or []) if r]
    new_norm = os.path.normpath(new_md_root).lower()
    out, placed = [], False
    for r in roots:
        same = os.path.normpath(r).lower() == new_norm
        if same or edition_of_root(r) is not None:
            if not placed:
                # Keep the user's spelling when it's already the same folder
                # (Steam's registry path is lower-cased; the list shouldn't flip).
                out.append(r if same else new_md_root)
                placed = True
            continue
        out.append(r)
    if not placed:
        out.insert(1 if out else 0, new_md_root)
    return out


# ---------------------------------------------------------------------------
# Process-wide active edition (what preset builders emit)
# ---------------------------------------------------------------------------
_active: MDEdition = DEFAULT_EDITION


def active_edition() -> MDEdition:
    return _active


def set_active_edition(key_or_edition) -> MDEdition:
    """Make an edition the one preset builders target. Accepts a key or an
    MDEdition. Returns the edition now active."""
    global _active
    _active = key_or_edition if isinstance(key_or_edition, MDEdition) else edition(key_or_edition)
    return _active


@contextlib.contextmanager
def edition_context(key_or_edition):
    """Temporarily activate an edition (exports use this so the file written
    matches the project's target even if the UI is showing something else)."""
    global _active
    prev = _active
    set_active_edition(key_or_edition)
    try:
        yield _active
    finally:
        _active = prev
