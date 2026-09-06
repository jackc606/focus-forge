"""Index of the focus trees the game/mod roots already ship, and the
"replace, don't duplicate" collision check against a project's export.

HOI4 loads EVERY ``common/national_focus/*.txt`` it can see. A submod that
exports an edited copy of Millennium Dawn's Nigeria tree as ``nga_focus.txt``
sits NEXT TO MD's ``05_nigeria.txt`` instead of replacing it: every focus id
is then defined twice, the tree renders with no prerequisite lines and no
focus can be started — and nothing in the editor said a word. The only safe
outcomes are (a) exporting under the SAME file name so the mod's file
overrides MD's, or (b) giving every focus a unique prefix so the two trees
can coexist. This module tells the rest of the app which of those a project
is in.

Qt-free. ``scan_base_trees`` reuses focus_import's Paradox-script helpers;
``current_index`` is the lazily built, mtime-keyed cache the UI and the AI
bridge share so validation never rescans MD's 20 MB of trees per keystroke.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from .focus_import import _ID, _TREE_START, _match_brace, _statements, _strip_comments
from .mod_paths import effective_roots_for_path
from .types import FocusForgeProject, ValidationIssue

# The mod every Focus Forge project targets; named in user-facing messages.
BASE_MOD_NAME = "Millennium Dawn"


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
@dataclass
class BaseTreeFile:
    path: str
    basename: str
    tree_ids: list = field(default_factory=list)
    focus_ids: set = field(default_factory=set)


@dataclass
class BaseTreeIndex:
    files: list = field(default_factory=list)          # [BaseTreeFile]
    _by_focus: dict = field(default_factory=dict, repr=False)   # focus id -> [basename]
    _by_tree: dict = field(default_factory=dict, repr=False)    # tree id -> [basename]

    def __post_init__(self) -> None:
        for bf in self.files:
            for fid in bf.focus_ids:
                self._by_focus.setdefault(fid, []).append(bf.basename)
            for tid in bf.tree_ids:
                self._by_tree.setdefault(tid, []).append(bf.basename)

    def file_for_focus(self, fid: str):
        """Basename of the first base file defining focus ``fid``, or None."""
        hits = self._by_focus.get(fid)
        return hits[0] if hits else None

    def files_for_focus(self, fid: str) -> list:
        return list(self._by_focus.get(fid, ()))

    def file_for_tree(self, tree_id: str):
        """Basename of the first base file declaring ``focus_tree id = tree_id``."""
        hits = self._by_tree.get(tree_id)
        return hits[0] if hits else None

    def files_for_tree(self, tree_id: str) -> list:
        return list(self._by_tree.get(tree_id, ()))

    def basenames(self) -> set:
        return {bf.basename for bf in self.files}

    def is_empty(self) -> bool:
        return not self.files


def _focus_files(roots):
    """Same discovery as focus_import._focus_files (replace_path-aware) —
    kept local so the index and the importer can't drift apart silently."""
    for root in effective_roots_for_path(roots, "common/national_focus"):
        nf = os.path.join(root, "common", "national_focus")
        if not os.path.isdir(nf):
            continue
        try:
            names = sorted(os.listdir(nf))
        except OSError:
            continue
        for fn in names:
            if fn.lower().endswith(".txt"):
                yield os.path.join(nf, fn)


def _scan_file(path: str) -> BaseTreeFile:
    """Every tree id and focus id one national_focus file declares."""
    bf = BaseTreeFile(path=path, basename=os.path.basename(path))
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError:
        return bf
    text = _strip_comments(raw)
    for m in _TREE_START.finditer(text):
        brace = m.end() - 1
        end = _match_brace(text, brace)
        block = text[brace + 1:end]
        tid = _ID.search(block)
        if tid and tid.group(1) not in bf.tree_ids:
            bf.tree_ids.append(tid.group(1))
        for key, kind, body in _statements(block):
            if kind != "block" or key.lower() != "focus":
                continue
            # The id is (in practice always) the first statement, so the lazy
            # walk stops almost immediately; a regex over the body could pick
            # up an `id =` nested inside an effect block instead.
            for k2, kind2, val in _statements(body):
                if kind2 == "scalar" and k2.lower() == "id":
                    bf.focus_ids.add(val)
                    break
    return bf


# path -> (mtime, BaseTreeFile); the same shape find_focus_trees uses so a
# touched MD file is reparsed and nothing else is.
_FILE_CACHE: dict = {}
_LOCK = threading.Lock()


def invalidate() -> None:
    """Forget every cached scan (tests; a roots change that keeps the paths)."""
    with _LOCK:
        _FILE_CACHE.clear()
        _INDEX_CACHE.clear()


def scan_base_trees(roots) -> BaseTreeIndex:
    """Index every ``common/national_focus/*.txt`` visible from ``roots``."""
    files: list = []
    for path in _focus_files(roots):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        cached = _FILE_CACHE.get(path)
        if cached is not None and cached[0] == mtime:
            files.append(cached[1])
            continue
        bf = _scan_file(path)
        _FILE_CACHE[path] = (mtime, bf)
        files.append(bf)
    return BaseTreeIndex(files=files)


# ---------------------------------------------------------------------------
# Shared lazily-built index
# ---------------------------------------------------------------------------
_INDEX_CACHE: dict = {}       # single entry: cache key -> BaseTreeIndex
_BUILDING: set = set()        # cache keys with a background build in flight


def _cache_key(roots) -> tuple:
    """(sorted roots, mtime of each national_focus dir): a new/removed tree
    file changes a directory's mtime, so the key rolls over without stat-ing
    every file on each validation pass."""
    stamps = []
    for root in effective_roots_for_path(roots, "common/national_focus"):
        nf = os.path.join(root, "common", "national_focus")
        try:
            stamps.append((nf, os.path.getmtime(nf)))
        except OSError:
            continue
    return (tuple(sorted(roots)), tuple(stamps))


def current_index(roots_provider, block: bool = True, on_ready=None):
    """The ``BaseTreeIndex`` for the roots ``roots_provider()`` returns,
    rebuilt only when the roots or their national_focus folders change.
    None when there are no roots.

    ``block=False`` never scans on the caller's thread: a miss starts one
    background build (calling ``on_ready()`` from that thread when it lands)
    and returns None, so keystroke-driven validation stays instant and simply
    goes silent on this check until the index exists."""
    try:
        roots = list(roots_provider() or ())
    except Exception:
        return None
    if not roots:
        return None
    key = _cache_key(roots)
    with _LOCK:
        hit = _INDEX_CACHE.get(key)
    if hit is not None:
        return hit
    if block:
        idx = scan_base_trees(roots)
        with _LOCK:
            _INDEX_CACHE.clear()
            _INDEX_CACHE[key] = idx
        return idx
    with _LOCK:
        if key in _BUILDING:
            return None
        _BUILDING.add(key)

    def _build() -> None:
        try:
            idx = scan_base_trees(roots)
            with _LOCK:
                _INDEX_CACHE.clear()
                _INDEX_CACHE[key] = idx
        except Exception:
            pass
        finally:
            with _LOCK:
                _BUILDING.discard(key)
        if on_ready is not None:
            try:
                on_ready()
            except Exception:
                pass

    threading.Thread(target=_build, daemon=True, name="base-tree-index").start()
    return None


# ---------------------------------------------------------------------------
# Collision check
# ---------------------------------------------------------------------------
@dataclass
class CollisionReport:
    export_basename: str = ""
    replaces: object = None            # base basename the export overrides (GOOD)
    duplicate_ids: dict = field(default_factory=dict)   # base basename -> [our ids]
    tree_id_clash: object = None       # base basename (≠ export) declaring our tree id
    suggested_basename: object = None  # one-click fix target
    tree_id: str = ""                  # the project's tree id (for messages)

    @property
    def is_problem(self) -> bool:
        return bool(self.duplicate_ids or self.tree_id_clash)

    @property
    def suggested_stem(self) -> str:
        return _stem(self.suggested_basename or "")


def _stem(basename: str) -> str:
    return basename[:-4] if basename.lower().endswith(".txt") else basename


def find_collisions(project: FocusForgeProject, index) -> CollisionReport:
    """How the project's export relates to the base trees in ``index``."""
    from .exporters import focus_file_basename
    export = focus_file_basename(project.exportSettings)
    report = CollisionReport(export_basename=export,
                             tree_id=(project.treeId or "").strip())
    if index is None:
        return report
    low = export.lower()
    for base in index.basenames():
        if base.lower() == low:
            report.replaces = base
            break

    dups: dict = {}
    for focus in project.focuses:
        fid = (focus.id or "").strip()
        if not fid:
            continue
        for base in index.files_for_focus(fid):
            if base.lower() == low:
                continue
            dups.setdefault(base, []).append(fid)
    report.duplicate_ids = dups

    if report.tree_id:
        for base in index.files_for_tree(report.tree_id):
            if base.lower() != low:
                report.tree_id_clash = base
                break

    if dups:
        report.suggested_basename = max(dups, key=lambda b: (len(dups[b]), b))
    elif report.tree_id_clash:
        report.suggested_basename = report.tree_id_clash
    return report


def collision_issues(report: CollisionReport) -> list:
    """Validation issues (plain language, for non-programmers) for a report
    that ``is_problem``; empty otherwise."""
    if report is None or not report.is_problem:
        return []
    issues: list = []
    export = report.export_basename
    for base in sorted(report.duplicate_ids, key=lambda b: (-len(report.duplicate_ids[b]), b)):
        n = len(report.duplicate_ids[base])
        issues.append(ValidationIssue(
            severity="error", code="project.tree.duplicate",
            message=(f"Your export file '{export}' would load NEXT TO {BASE_MOD_NAME}'s "
                     f"'{base}', and {n} of your focus ids exist in both. In-game the "
                     f"tree breaks: no connecting lines, no focus can be started. "
                     f"Fix: set the export file name to '{_stem(base)}' so your tree "
                     f"REPLACES MD's (Export tab → Fix), or give every focus a unique "
                     f"prefix.")))
    if report.tree_id_clash and report.tree_id_clash not in report.duplicate_ids:
        base = report.tree_id_clash
        issues.append(ValidationIssue(
            severity="error", code="project.tree.idClash",
            message=(f"Your tree id '{report.tree_id}' is already used by "
                     f"{BASE_MOD_NAME}'s '{base}'. Either export as '{_stem(base)}' to "
                     f"replace that tree, or change the tree id.")))
    return issues
