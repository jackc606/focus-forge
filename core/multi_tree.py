"""Multi-tree projects: several ``focus_tree`` blocks plus top-level
``shared_focus`` blocks living in ONE national_focus file (Millennium Dawn's
Australia file has 8 trees and 89 shared focuses).

A project exports in "replace" mode — it overwrites the file it was imported
from — so it has to hold the WHOLE file or the export would delete every tree
it didn't carry. The editor, however, works on one tree at a time, so the
project stays "one ACTIVE tree":

* ``project.treeId / focuses / shortcuts / continuousFocusPosition /
  countryRawLines / sharedFocusRefs / treeRawLines`` describe the active tree;
* ``project.otherTrees`` parks the inactive ones (``FocusTreeData``, file order
  with the active one removed) and ``project.activeTreeIndex`` is the active
  tree's position among ALL trees;
* shared focuses (``FocusNodeData.shared``) that the active tree can see sit in
  ``project.focuses`` after its own focuses; the rest wait in
  ``project.sharedPool``.

A shared focus is VISIBLE in a tree when it is one of the tree's
``sharedFocusRefs`` roots or a transitive descendant of one through
prerequisites (any member of a prerequisite block counts).

Shared focuses may carry ``offset = { x y trigger = { has_focus_tree = T } }``
blocks that move them in one particular tree. ``position`` always holds what
the editor shows for the ACTIVE tree; ``appliedOffset`` records how much of it
is such an offset, so ``base_position`` (what the file's x/y say) is always
recoverable.

Pure functions, no Qt.
"""
from __future__ import annotations

import dataclasses
import re

from .types import FocusPosition, FocusTreeData, iter_prereq_ids

# An offset applies to tree T only when its trigger is EXACTLY
# `has_focus_tree = T`. Anything else (compound / negated / other triggers) is
# not evaluated by the editor — the block is still exported verbatim.
_OFFSET_TRIGGER = re.compile(
    r"\btrigger\s*=\s*\{\s*has_focus_tree\s*=\s*([A-Za-z0-9_.\-]+)\s*\}")
_ANY_TRIGGER = re.compile(r"\btrigger\s*=\s*\{.*\}", re.DOTALL)
_OFFSET_X = re.compile(r"(?<![A-Za-z0-9_])x\s*=\s*(-?\d+(?:\.\d+)?)")
_OFFSET_Y = re.compile(r"(?<![A-Za-z0-9_])y\s*=\s*(-?\d+(?:\.\d+)?)")


def _num(text: str):
    f = float(text)
    return int(f) if f.is_integer() else f


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------
def is_multi(project) -> bool:
    """True when the project carries anything beyond one plain tree (parked
    trees or pooled shared focuses)."""
    return bool(getattr(project, "otherTrees", None) or getattr(project, "sharedPool", None))


def tree_count(project) -> int:
    return len(getattr(project, "otherTrees", None) or []) + 1


def active_index(project) -> int:
    """``activeTreeIndex`` clamped into range (a hand-edited file can't break
    the enumeration)."""
    n = len(getattr(project, "otherTrees", None) or [])
    try:
        i = int(getattr(project, "activeTreeIndex", 0) or 0)
    except (TypeError, ValueError):
        i = 0
    return max(0, min(i, n))


def tree_ids(project) -> list:
    """Every tree id in file order, the active one at ``activeTreeIndex``."""
    ids = [t.treeId for t in (getattr(project, "otherTrees", None) or [])]
    ids.insert(active_index(project), project.treeId)
    return ids


def own_focuses(project) -> list:
    """The ACTIVE tree's own (non-shared) focuses."""
    return [f for f in project.focuses if not getattr(f, "shared", False)]


def all_shared(project) -> list:
    """Every shared focus exactly once (visible first, then the pool) — the
    live objects."""
    out = [f for f in project.focuses if getattr(f, "shared", False)]
    out.extend(getattr(project, "sharedPool", None) or [])
    return out


def all_focuses(project) -> list:
    """Every focus of the whole file exactly once: the active tree's focuses
    (own + visible shared), every other tree's own, then the shared pool.
    For an ordinary single-tree project this is ``project.focuses`` itself."""
    others = getattr(project, "otherTrees", None)
    pool = getattr(project, "sharedPool", None)
    if not others and not pool:
        return project.focuses
    out = list(project.focuses)
    for t in others or []:
        out.extend(t.focuses)
    out.extend(pool or [])
    return out


def all_shortcut_lists(project) -> list:
    """One shortcut list per tree, in file order (the live lists)."""
    lists = [t.shortcuts for t in (getattr(project, "otherTrees", None) or [])]
    lists.insert(active_index(project), project.shortcuts)
    return lists


# ---------------------------------------------------------------------------
# Shared-focus reachability
# ---------------------------------------------------------------------------
def shared_roots(project, refs=None) -> list:
    """The shared focuses named by ``refs`` (default: the active tree's
    ``sharedFocusRefs``), in ref order. Refs defined elsewhere are skipped."""
    by_id = {f.id: f for f in all_shared(project)}
    if refs is None:
        refs = getattr(project, "sharedFocusRefs", None) or []
    return [by_id[r] for r in refs if r in by_id]


def visible_shared_ids(shared, refs) -> set:
    """Ids of the ``shared`` focuses a tree with ``refs`` can see: each
    referenced root plus everything that (transitively) requires one."""
    ids = {f.id for f in shared}
    start = [r for r in (refs or []) if r in ids]
    if not start:
        return set()
    children: dict = {}
    for f in shared:
        for p in iter_prereq_ids(f.prerequisites):
            if p in ids:
                children.setdefault(p, []).append(f.id)
    seen: set = set()
    stack = list(start)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(c for c in children.get(cur, ()) if c not in seen)
    return seen


# ---------------------------------------------------------------------------
# Offsets
# ---------------------------------------------------------------------------
def offset_block_target(lines) -> "str | None":
    """The tree id an offset block applies to, or None when its trigger isn't
    a plain ``has_focus_tree = <id>``."""
    text = " ".join(str(ln) for ln in (lines or []))
    m = _OFFSET_TRIGGER.search(text)
    return m.group(1) if m else None


def offset_block_delta(lines) -> tuple:
    """``(dx, dy)`` of one offset block (its trigger body is ignored)."""
    text = _ANY_TRIGGER.sub(" ", " ".join(str(ln) for ln in (lines or [])))
    mx, my = _OFFSET_X.search(text), _OFFSET_Y.search(text)
    return (_num(mx.group(1)) if mx else 0, _num(my.group(1)) if my else 0)


def _own_delta(focus, tree_id: str) -> tuple:
    dx = dy = 0
    for block in (getattr(focus, "offsets", None) or []):
        if offset_block_target(block) == tree_id:
            bx, by = offset_block_delta(block)
            dx += bx
            dy += by
    return dx, dy


def shared_deltas(shared, tree_id: str) -> dict:
    """``{focus id: (dx, dy)}`` for every shared focus in tree ``tree_id``: its
    own applicable offsets plus the delta of the focus it is positioned
    relative to (recursively, cycle-safe) — the game moves a whole
    ``relative_position_id`` chain when its anchor is offset."""
    by_id = {f.id: f for f in shared}
    if not any(getattr(f, "offsets", None) for f in shared):
        return {}
    cache: dict = {}

    def delta(fid: str) -> tuple:
        if fid in cache:
            return cache[fid]
        # Walk up the relative chain iteratively (chains can be long).
        chain, seen, cur = [], set(), fid
        while cur in by_id and cur not in cache and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = getattr(by_id[cur], "relativePositionId", None) or ""
        base = cache.get(cur, (0, 0))
        for cid in reversed(chain):
            ox, oy = _own_delta(by_id[cid], tree_id)
            base = (base[0] + ox, base[1] + oy)
            cache[cid] = base
        return cache.get(fid, (0, 0))

    for f in shared:
        delta(f.id)
    return {k: v for k, v in cache.items() if v != (0, 0)}


def base_position(focus) -> tuple:
    """``(x, y)`` as the file states it: position minus the applied offset."""
    off = getattr(focus, "appliedOffset", None)
    if off is None:
        return (focus.position.x, focus.position.y)
    return (focus.position.x - off.x, focus.position.y - off.y)


def _clear_offset(focus) -> None:
    off = getattr(focus, "appliedOffset", None)
    if off is not None:
        focus.position = FocusPosition(x=focus.position.x - off.x, y=focus.position.y - off.y)
        focus.appliedOffset = None


def _apply_offset(focus, delta: tuple) -> None:
    if delta and delta != (0, 0):
        focus.position = FocusPosition(x=focus.position.x + delta[0],
                                       y=focus.position.y + delta[1])
        focus.appliedOffset = FocusPosition(x=delta[0], y=delta[1])


# ---------------------------------------------------------------------------
# Switching the active tree
# ---------------------------------------------------------------------------
def shared_sort_key(focus) -> tuple:
    """Canonical order of shared focuses (pool, canvas and export): by BASE
    position then id. The interleaving of visible and pooled focuses is lost
    every time some move to the canvas, so a stored file order could not
    survive a switch there and back — a derived order can."""
    x, y = base_position(focus)
    return (y, x, focus.id)


def park_shared(project) -> None:
    """Move every shared focus out of ``project.focuses`` into the pool, with
    its position restored to the base (offset-free) one, and put the pool back
    into canonical order."""
    visible = [f for f in project.focuses if getattr(f, "shared", False)]
    if not visible:
        return
    for f in visible:
        _clear_offset(f)
    project.focuses = [f for f in project.focuses if not getattr(f, "shared", False)]
    project.sharedPool = sorted(visible + list(project.sharedPool or []), key=shared_sort_key)


def pull_visible(project) -> None:
    """Move the shared focuses visible in the ACTIVE tree from the pool into
    ``project.focuses`` (after the own focuses, pool order preserved) and bake
    the active tree's offsets into their positions."""
    pool = list(getattr(project, "sharedPool", None) or [])
    if not pool:
        return
    everything = all_shared(project)
    visible = visible_shared_ids(everything, getattr(project, "sharedFocusRefs", None) or [])
    if not visible:
        return
    deltas = shared_deltas(everything, project.treeId)
    moved = [f for f in pool if f.id in visible]
    for f in moved:
        _apply_offset(f, deltas.get(f.id))
    project.sharedPool = [f for f in pool if f.id not in visible]
    project.focuses = list(project.focuses) + moved


def _pack_active(project) -> FocusTreeData:
    return FocusTreeData(
        treeId=project.treeId,
        focuses=[f for f in project.focuses if not getattr(f, "shared", False)],
        shortcuts=list(project.shortcuts or []),
        continuousFocusPosition=project.continuousFocusPosition,
        countryRawLines=list(getattr(project, "countryRawLines", None) or []),
        sharedFocusRefs=list(getattr(project, "sharedFocusRefs", None) or []),
        extraRawLines=list(getattr(project, "treeRawLines", None) or []),
    )


def _install(project, tree: FocusTreeData, index: int) -> None:
    project.treeId = tree.treeId
    project.focuses = list(tree.focuses)
    project.shortcuts = list(tree.shortcuts or [])
    project.continuousFocusPosition = tree.continuousFocusPosition
    project.countryRawLines = list(tree.countryRawLines or [])
    project.sharedFocusRefs = list(tree.sharedFocusRefs or [])
    project.treeRawLines = list(tree.extraRawLines or [])
    project.activeTreeIndex = index


def switch_tree(project, index: int) -> bool:
    """Make tree ``index`` (file order) the active one, in place. False (and
    nothing changes) for an out-of-range or already-active index."""
    try:
        index = int(index)
    except (TypeError, ValueError):
        return False
    current = active_index(project)
    if index < 0 or index >= tree_count(project) or index == current:
        return False
    # (a) shared focuses leave the canvas, offsets undone
    park_shared(project)
    # (b) park the active tree at its file position
    trees = list(project.otherTrees or [])
    trees.insert(current, _pack_active(project))
    # (c) install the target
    target = trees.pop(index)
    project.otherTrees = trees
    _install(project, target, index)
    # (d) bring in what the new tree can see
    pull_visible(project)
    return True


def index_of_tree(project, tree_id: str) -> int:
    """File index of the tree with this id, or -1."""
    try:
        return tree_ids(project).index(tree_id)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# Read-only per-tree views
# ---------------------------------------------------------------------------
def tree_views(project) -> list:
    """One project per tree, in file order, each presenting THAT tree as the
    active one: ``focuses`` = its own focuses + the shared focuses it can see,
    positioned with its offsets. Views are shallow (``dataclasses.replace``)
    and carry no parked trees / pool, so ``all_focuses(view) == view.focuses``.

    Focus objects are the live ones wherever possible; a shared focus is
    copied only when its position in that tree differs from the live object's.
    An ordinary single-tree project yields ``[project]`` itself. Treat views
    as read-only."""
    if not is_multi(project):
        return [project]
    current = active_index(project)
    shared = all_shared(project)
    views: list = []
    others = iter(project.otherTrees or [])
    for i in range(tree_count(project)):
        if i == current:
            views.append(dataclasses.replace(project, otherTrees=[], sharedPool=[]))
            continue
        t = next(others)
        visible = visible_shared_ids(shared, t.sharedFocusRefs)
        focuses = list(t.focuses)
        if visible:
            deltas = shared_deltas(shared, t.treeId)
            for f in shared:
                if f.id not in visible:
                    continue
                bx, by = base_position(f)
                dx, dy = deltas.get(f.id, (0, 0))
                want_off = FocusPosition(x=dx, y=dy) if (dx, dy) != (0, 0) else None
                if (f.position.x, f.position.y) == (bx + dx, by + dy) \
                        and getattr(f, "appliedOffset", None) == want_off:
                    focuses.append(f)
                else:
                    focuses.append(dataclasses.replace(
                        f, position=FocusPosition(x=bx + dx, y=by + dy),
                        appliedOffset=want_off))
        views.append(dataclasses.replace(
            project,
            treeId=t.treeId,
            focuses=focuses,
            shortcuts=t.shortcuts,
            continuousFocusPosition=t.continuousFocusPosition,
            countryRawLines=t.countryRawLines,
            sharedFocusRefs=t.sharedFocusRefs,
            treeRawLines=t.extraRawLines,
            activeTreeIndex=i,
            otherTrees=[],
            sharedPool=[],
        ))
    return views


def tree_summaries(project) -> list:
    """``[{index, treeId, active, ownFocuses, sharedFocuses}]`` in file order."""
    current = active_index(project)
    shared = all_shared(project)
    out: list = []
    others = iter(getattr(project, "otherTrees", None) or [])
    for i in range(tree_count(project)):
        if i == current:
            tid = project.treeId
            own = sum(1 for f in project.focuses if not getattr(f, "shared", False))
            refs = getattr(project, "sharedFocusRefs", None) or []
        else:
            t = next(others)
            tid, own, refs = t.treeId, len(t.focuses), t.sharedFocusRefs
        out.append({"index": i, "treeId": tid, "active": i == current,
                    "ownFocuses": own,
                    "sharedFocuses": len(visible_shared_ids(shared, refs))})
    return out
