"""Import an existing HOI4 focus tree (``common/national_focus/*.txt``) into a
FocusForgeProject — essentially the inverse of ``exporters.py``.

It is intentionally pragmatic: structural fields (id, icon, x/y, cost,
prerequisites, mutually_exclusive, search_filters) are parsed into the data
model, while ``available`` and ``completion_reward`` bodies are kept verbatim as
raw lines (which the exporter re-emits). Focus titles/descriptions are pulled
from the matching ``localisation/english/*.yml``. Advanced focus statements not
modelled by the editor (ai_will_do, bypass, allow_branch, …) are not preserved.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .types import (
    AvailabilityRule,
    CompletionReward,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    FocusShortcut,
    map_prereq_groups,
)
from .mod_paths import effective_roots_for_path
from .pdx_loc import load_english_localisation

_TREE_START = re.compile(r"\bfocus_tree\s*=\s*\{", re.IGNORECASE)
_FOCUS_COUNT = re.compile(r"\bfocus\s*=\s*\{")
_TAG = re.compile(r"\b(?:original_tag|tag)\s*=\s*([A-Za-z0-9_]+)")
_ID = re.compile(r"\bid\s*=\s*([A-Za-z0-9_.]+)")


# ---------------------------------------------------------------------------
# Generic Paradox-script helpers
# ---------------------------------------------------------------------------
def _strip_comments(text: str) -> str:
    """Remove ``#`` comments, but only OUTSIDE quoted strings.

    A blind ``#.*`` strip truncated lines like ``log = "50% done # half"`` to an
    unterminated quote, and a ``{``/``}`` after a ``#`` inside a string desynced
    the brace matcher for the rest of the file. Line structure is preserved."""
    out: list = []
    for line in text.split("\n"):
        if "#" in line:
            in_string = False
            for i, ch in enumerate(line):
                if ch == '"':
                    in_string = not in_string
                elif ch == "#" and not in_string:
                    line = line[:i]
                    break
        out.append(line)
    return "\n".join(out)


def _match_brace(text: str, open_idx: int) -> int:
    """Index of the '}' matching the '{' at open_idx."""
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


_KEY_RE = re.compile(r"[A-Za-z0-9_.\-]+")
_NONSPACE_RE = re.compile(r"\S+")


def _statements(text: str):
    """Yield (key, kind, body) for each top-level ``key = value`` / ``key = { }``.
    kind is 'block' or 'scalar'. Comments must already be stripped."""
    i = 0
    n = len(text)
    key_re = _KEY_RE
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return
        m = key_re.match(text, i)
        if not m:
            i += 1
            continue
        key = m.group(0)
        i = m.end()
        while i < n and text[i].isspace():
            i += 1
        if i >= n or text[i] != "=":
            continue
        i += 1
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return
        if text[i] == "{":
            end = _match_brace(text, i)
            yield key, "block", text[i + 1:end]
            i = end + 1
        elif text[i] == '"':
            end = text.find('"', i + 1)
            if end == -1:
                end = n
            yield key, "scalar", text[i + 1:end]
            i = end + 1
        else:
            m2 = _NONSPACE_RE.match(text, i)
            yield key, "scalar", m2.group(0)
            i = m2.end()


def _raw_lines(body: str, drop_log: bool = False) -> list:
    out = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if drop_log and s.startswith("log =") and "GetDateText" in s:
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Parsed focus
# ---------------------------------------------------------------------------
@dataclass
class _PFocus:
    id: str = ""
    icon: str = ""
    x: int = 0
    y: int = 0
    cost: float = 5
    rel: str = ""
    prereqs: list = field(default_factory=list)
    mutex: list = field(default_factory=list)
    filters: list = field(default_factory=list)
    available_raw: list = field(default_factory=list)
    reward_raw: list = field(default_factory=list)


def _parse_focus(body: str) -> _PFocus:
    pf = _PFocus()
    for key, kind, val in _statements(body):
        k = key.lower()
        if kind == "scalar":
            if k == "id":
                pf.id = val
            elif k == "icon":
                pf.icon = val
            elif k == "x":
                pf.x = _to_int(val)
            elif k == "y":
                pf.y = _to_int(val)
            elif k == "cost":
                pf.cost = _to_float(val)
            elif k == "relative_position_id":
                pf.rel = val
        else:  # block
            if k == "prerequisite":
                # One prerequisite BLOCK -> one group. Several focus= inside the
                # same block are an OR choice; keep them together (don't flatten
                # across blocks, which would silently turn OR into AND).
                block = [f for key2, kk, f in _statements(val)
                         if kk == "scalar" and key2.lower() == "focus"]
                if len(block) == 1:
                    pf.prereqs.append(block[0])
                elif block:
                    pf.prereqs.append(block)
            elif k == "mutually_exclusive":
                pf.mutex.extend(f for _, kk, f in _statements(val) if kk == "scalar")
            elif k == "search_filters":
                pf.filters.extend(val.split())
            elif k == "available":
                pf.available_raw = _raw_lines(val)
            elif k == "completion_reward":
                pf.reward_raw = _raw_lines(val, drop_log=True)
    return pf


@dataclass
class _PShortcut:
    name: str = ""       # the loc key referenced by `name = ...`
    target: str = ""
    zoom: object = None  # float, or None when scroll_wheel_factor is absent
    trigger_raw: list = field(default_factory=list)


def _parse_shortcut(body: str) -> _PShortcut:
    ps = _PShortcut()
    for key, kind, val in _statements(body):
        k = key.lower()
        if kind == "scalar":
            if k == "name":
                ps.name = val
            elif k == "target":
                ps.target = val
            elif k == "scroll_wheel_factor":
                try:
                    ps.zoom = float(val)
                except (TypeError, ValueError):
                    ps.zoom = None
        elif k == "trigger":  # block — keep inner lines verbatim
            ps.trigger_raw = _raw_lines(val)
    return ps


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 5.0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
@dataclass
class FocusTreeRef:
    tag: str
    tree_id: str
    focus_count: int
    file: str
    prefix_ids: bool = False  # rename every focus id to <TAG>_<id> on import
                              # (used for "start from the generic MD tree")
    roots: tuple = ()         # roots to use for loc/replace_path on import; empty
                              # → the caller's default. Set for ad-hoc folders the
                              # user browses to that aren't in the configured roots.


def _focus_files(roots):
    # MD (and most overhauls) declare replace_path="common/national_focus", which
    # makes the game ignore the entire vanilla focus folder. Honour that so the
    # importer doesn't leak vanilla WW2 trees (which duplicate the modern majors
    # under GER/FRA/USA/… and resolve some tags to "?").
    for root in effective_roots_for_path(roots, "common/national_focus"):
        nf = os.path.join(root, "common", "national_focus")
        if not os.path.isdir(nf):
            continue
        for fn in sorted(os.listdir(nf)):
            if fn.lower().endswith(".txt"):
                yield os.path.join(nf, fn)


_TREE_CACHE = {}


def _trees_in_file(path: str, roots: tuple = ()) -> list:
    """Every focus_tree declared in a single .txt file, as FocusTreeRefs."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    text = _strip_comments(raw)
    out = []
    for m in _TREE_START.finditer(text):
        brace = m.end() - 1
        end = _match_brace(text, brace)
        block = text[brace + 1:end]
        tid = _ID.search(block)
        # tags from the country block — a single tree can apply to several
        # countries via an OR list (e.g. gulf_focus → SAU/QAT/UAE/BHR/KUW/OMA),
        # so collect ALL of them and surface the tree under each tag.
        tags = []
        for key, kind, body in _statements(block):
            if key.lower() == "country" and kind == "block":
                tags = list(dict.fromkeys(_TAG.findall(body)))
                break
        count = len(_FOCUS_COUNT.findall(block))
        if count == 0:
            continue
        tree_id = tid.group(1) if tid else "(unknown)"
        for tag in (tags or ["?"]):
            out.append(FocusTreeRef(
                tag=tag,
                tree_id=tree_id,
                focus_count=count,
                file=path,
                roots=roots,
            ))
    return out


def find_focus_trees(roots, use_cache: bool = True) -> list:
    """All importable focus trees across the given roots (cached per root set)."""
    key = tuple(roots)
    if use_cache and key in _TREE_CACHE:
        return _TREE_CACHE[key]
    trees = []
    for path in _focus_files(roots):
        trees.extend(_trees_in_file(path))
    trees.sort(key=lambda t: (t.tag, t.tree_id))
    _TREE_CACHE[key] = trees
    return trees


def _folder_focus_files(folder: str):
    """national_focus .txt files for a folder the user browses to ad-hoc.

    Accepts a mod root (``<folder>/common/national_focus``), the
    ``national_focus`` directory itself, or any loose folder that directly holds
    focus_tree .txt files."""
    nf = os.path.join(folder, "common", "national_focus")
    if os.path.isdir(nf):
        scan = nf
    elif os.path.basename(os.path.normpath(folder)).lower() == "national_focus":
        scan = folder
    else:
        scan = folder
    if not os.path.isdir(scan):
        return
    for fn in sorted(os.listdir(scan)):
        if fn.lower().endswith(".txt"):
            yield os.path.join(scan, fn)


def find_focus_trees_in_folder(folder: str, import_roots) -> list:
    """Importable focus trees inside an ad-hoc folder the user browsed to.

    ``import_roots`` is the root list to record on each ref so import-time
    localisation lookup sees both the folder and the configured game/mod roots.
    Not cached — the folder is transient and may change between scans."""
    roots = tuple(import_roots)
    trees = []
    for path in _folder_focus_files(folder):
        trees.extend(_trees_in_file(path, roots=roots))
    trees.sort(key=lambda t: (t.tag, t.tree_id))
    return trees


# ---------------------------------------------------------------------------
# Localisation lookup (only the keys we need)
# ---------------------------------------------------------------------------
def _load_localisation(roots, needed: set) -> dict:
    """English titles/descriptions for the needed keys (shared loader)."""
    return load_english_localisation(roots, needed)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def _resolve_positions(focuses: list) -> dict:
    by_id = {f.id: f for f in focuses}
    cache = {}

    def resolve(fid, stack):
        if fid in cache:
            return cache[fid]
        f = by_id.get(fid)
        if f is None:
            return (0, 0)
        if f.rel and f.rel in by_id and f.rel not in stack and f.rel != fid:
            px, py = resolve(f.rel, stack | {fid})
            res = (f.x + px, f.y + py)
        else:
            res = (f.x, f.y)
        cache[fid] = res
        return res

    for f in focuses:
        resolve(f.id, set())
    return cache


def import_focus_tree(ref: FocusTreeRef, roots) -> FocusForgeProject:
    # Ad-hoc folder refs carry their own roots (folder + configured) so loc
    # resolves from the browsed folder; configured-root refs leave it empty.
    if ref.roots:
        roots = list(ref.roots)
    # UTF-8-BOM per HOI4 spec, with a cp1252 fallback for legacy files — so
    # accented characters survive instead of being silently mangled to U+FFFD.
    raw = open(ref.file, "rb").read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            decoded = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = raw.decode("utf-8-sig", errors="replace")
    text = _strip_comments(decoded)

    block = ""
    for m in _TREE_START.finditer(text):
        brace = m.end() - 1
        end = _match_brace(text, brace)
        b = text[brace + 1:end]
        tid = _ID.search(b)
        if tid and tid.group(1) == ref.tree_id:
            block = b
            break
    if not block:
        raise ValueError(f"focus_tree '{ref.tree_id}' not found in {ref.file}")

    cfp = FocusPosition(x=0, y=0)
    parsed = []
    parsed_shortcuts = []
    for key, kind, body in _statements(block):
        k = key.lower()
        if k == "focus" and kind == "block":
            pf = _parse_focus(body)
            if pf.id:
                parsed.append(pf)
        elif k == "shortcut" and kind == "block":
            parsed_shortcuts.append(_parse_shortcut(body))
        elif k == "continuous_focus_position" and kind == "block":
            xm = re.search(r"\bx\s*=\s*(-?\d+)", body)
            ym = re.search(r"\by\s*=\s*(-?\d+)", body)
            cfp = FocusPosition(x=_to_int(xm.group(1)) if xm else 0,
                                y=_to_int(ym.group(1)) if ym else 0)

    abs_pos = _resolve_positions(parsed)

    # localisation: titles + descriptions for every focus id, plus each
    # shortcut's button label (its `name` is a loc key).
    needed = set()
    for pf in parsed:
        needed.add(pf.id)
        needed.add(pf.id + "_desc")
    for ps in parsed_shortcuts:
        if ps.name:
            needed.add(ps.name)
    loc = _load_localisation(roots, needed)

    focuses = []
    for pf in parsed:
        x, y = abs_pos.get(pf.id, (pf.x, pf.y))
        reward = CompletionReward(rawLines=pf.reward_raw or None)
        available = AvailabilityRule(rawLines=pf.available_raw) if pf.available_raw else None
        focuses.append(FocusNodeData(
            id=pf.id,
            title=loc.get(pf.id, pf.id),
            description=loc.get(pf.id + "_desc", ""),
            icon=pf.icon,
            position=FocusPosition(x=x, y=y),
            cost=pf.cost,
            filters=pf.filters,
            prerequisites=pf.prereqs,
            mutuallyExclusive=pf.mutex,
            completionReward=reward,
            available=available,
        ))

    # Preserve tree order; recover each label from the loc file (fall back to the
    # raw loc key when it isn't localised).
    shortcuts = [
        FocusShortcut(
            label=loc.get(ps.name, ps.name) if ps.name else "",
            target=ps.target,
            zoomFactor=ps.zoom,
            triggerRawLines=list(ps.trigger_raw),
        )
        for ps in parsed_shortcuts
    ]

    tag = ref.tag if ref.tag and ref.tag != "?" else "TAG"

    tree_id = ref.tree_id
    project_name = f"{ref.tree_id} (imported)"
    if ref.prefix_ids and tag != "TAG":
        # "Start from the generic tree": the generic focus ids are global and
        # would collide with MD's own generic_focus in-game, so namespace every
        # id under the country tag and remap the prerequisite/mutex graph to match.
        pref = tag + "_"
        rename = {f.id: (f.id if f.id.startswith(pref) else pref + f.id) for f in focuses}
        for f in focuses:
            f.id = rename.get(f.id, f.id)
            f.prerequisites = map_prereq_groups(f.prerequisites, lambda p: rename.get(p, p))
            f.mutuallyExclusive = [rename.get(m, m) for m in f.mutuallyExclusive]
            if f.available and f.available.completedFocuses:
                f.available.completedFocuses = [rename.get(c, c) for c in f.available.completedFocuses]
        # Shortcut targets point at renamed focuses too.
        for sc in shortcuts:
            sc.target = rename.get(sc.target, sc.target)
        tree_id = f"{tag.lower()}_focus"
        project_name = f"{tag} focus tree (from generic)"

    return FocusForgeProject(
        projectName=project_name,
        countryTag=tag,
        treeId=tree_id,
        continuousFocusPosition=cfp,
        focuses=focuses,
        shortcuts=shortcuts,
        exportSettings=ExportSettings(
            modPrefix=tag,
            focusFileName=f"{tag.lower()}_focus",
            localisationPrefix=tag,
        ),
    )
