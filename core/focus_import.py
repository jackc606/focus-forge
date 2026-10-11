"""Import an existing HOI4 focus tree (``common/national_focus/*.txt``) into a
FocusForgeProject — essentially the inverse of ``exporters.py``.

It is intentionally pragmatic: structural fields (id, icon, x/y, cost,
prerequisites, mutually_exclusive, search_filters) are parsed into the data
model, while ``available``, ``bypass`` and ``completion_reward`` bodies are kept
verbatim as raw lines (which the exporter re-emits). Focus titles/descriptions
are pulled from the matching ``localisation/english/*.yml``. ai_will_do is
parsed (base + modifiers, triggers kept as raw lines); every other focus
statement the editor doesn't model (allow_branch, cancel, select_effect,
will_lead_to_war_with, …) is preserved verbatim in ``extraRawLines``.

A national_focus file may hold SEVERAL ``focus_tree`` blocks plus top-level
``shared_focus`` blocks (Millennium Dawn's Australia: 8 trees, 89 shared
focuses). Because an imported project REPLACES the file it came from, the
default import carries the whole file — the chosen tree active, the others
parked (see ``core.multi_tree``). "Separate copy" imports take one tree only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .types import (
    AiModifier,
    AvailabilityRule,
    CompletionReward,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    FocusShortcut,
    FocusTreeData,
    map_prereq_groups,
)
from . import multi_tree
from .mod_paths import effective_roots_for_path
from .pdx_loc import load_english_localisation

_TREE_START = re.compile(r"\bfocus_tree\s*=\s*\{", re.IGNORECASE)
_FOCUS_COUNT = re.compile(r"\bfocus\s*=\s*\{")
# Top-level shared focus DEFINITION (a block). Inside a tree `shared_focus = ID`
# is a scalar REFERENCE to one — the two never share a shape.
_SHARED_START = re.compile(r"\bshared_focus\s*=\s*\{", re.IGNORECASE)
_SHARED_REF = re.compile(r"\bshared_focus\s*=\s*([A-Za-z0-9_.\-]+)", re.IGNORECASE)
_TAG = re.compile(r"\b(?:original_tag|tag)\s*=\s*([A-Za-z0-9_]+)")
_ID = re.compile(r"\bid\s*=\s*([A-Za-z0-9_.]+)")
_AI_WEIGHT_LINE = re.compile(r"^(factor|add)\s*=\s*(\S+)$", re.IGNORECASE)
# A focus-id prefix for "start a separate copy" imports: HOI4 id characters
# only, and it must start with a letter so the result is a legal focus id.
ID_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


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


def _statements_q(text: str):
    """``_statements`` with one more field: ``(key, kind, body, quoted)`` where
    ``quoted`` is True for a scalar written as ``key = "value"``. A separate
    generator so the hot 3-tuple ``_statements`` (base-tree indexing walks
    megabytes with it) keeps its shape and speed."""
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
            yield key, "block", text[i + 1:end], False
            i = end + 1
        elif text[i] == '"':
            end = text.find('"', i + 1)
            if end == -1:
                end = n
            yield key, "scalar", text[i + 1:end], True
            i = end + 1
        else:
            m2 = _NONSPACE_RE.match(text, i)
            yield key, "scalar", m2.group(0), False
            i = m2.end()


def _verbatim(key: str, kind: str, body: str, quoted: bool = False) -> list:
    """One statement the editor doesn't model, as raw lines the exporter
    re-emits: ``key = value`` for a scalar (re-quoted if the source was), or
    ``key = {`` / the block's stripped inner lines / ``}`` for a block. A
    block written on one line stays one line, so re-importing an export
    reproduces it exactly."""
    if kind == "scalar":
        return [f'{key} = "{body}"' if quoted else f"{key} = {body}"]
    inner = body.strip()
    if "\n" not in inner:
        return [f"{key} = {{ {inner} }}" if inner else f"{key} = {{ }}"]
    return [f"{key} = {{"] + _raw_lines(body) + ["}"]


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
    ai_base: object = None            # float, or None when ai_will_do has no base
    ai_mods: list = field(default_factory=list)   # [(factor, add, [trigger lines])]
    bypass_raw: list = field(default_factory=list)
    offsets: list = field(default_factory=list)   # [[inner raw lines], …] one per offset block
    extra: list = field(default_factory=list)     # unmodelled statements, verbatim lines


def _parse_ai_will_do(body: str):
    """``(base, [(factor, add, trigger_lines)])`` from an ai_will_do body. A bare
    top-level ``factor`` with no ``base`` (a common MD shorthand) is the base."""
    base, factor_top, mods = None, None, []
    for key, kind, val in _statements(body):
        k = key.lower()
        if kind == "scalar":
            if k == "base":
                base = _to_float(val)
            elif k == "factor":
                factor_top = _to_float(val)
        elif k == "modifier":
            # factor/add are lifted; every other line is the trigger, kept
            # verbatim (so `date > 2006.1.1` and multi-line blocks survive —
            # _statements only understands `=`).
            factor, add, trig = None, None, []
            for ln in _raw_lines(val):
                m = _AI_WEIGHT_LINE.match(ln)
                if m:
                    if m.group(1).lower() == "factor":
                        factor = _to_float(m.group(2))
                    else:
                        add = _to_float(m.group(2))
                    continue
                trig.append(ln)
            mods.append((factor, add, trig))
    if base is None and factor_top is not None:
        base = factor_top
    return base, mods


def _parse_focus(body: str) -> _PFocus:
    pf = _PFocus()
    for key, kind, val, quoted in _statements_q(body):
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
            else:
                pf.extra.extend(_verbatim(key, kind, val, quoted))
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
            elif k == "ai_will_do":
                pf.ai_base, pf.ai_mods = _parse_ai_will_do(val)
            elif k == "bypass":
                pf.bypass_raw = _raw_lines(val)
            elif k == "offset":
                lines = _raw_lines(val)
                if lines:
                    pf.offsets.append(lines)
            else:
                pf.extra.extend(_verbatim(key, kind, val))
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
    id_prefix: str = ""       # "start a separate copy": every focus id becomes
                              # <id_prefix>_<id>, the tree id / export file become
                              # <id_prefix>_focus, so the copy can never collide
                              # with the base tree it was cloned from.
    shared_count: int = 0     # how many of focus_count are shared focuses the
                              # tree pulls in (own focuses = focus_count - this)
    trees_in_file: int = 1    # focus_tree blocks in ``file`` — a default import
                              # brings all of them, a separate copy only this one

    inherited_tag: bool = False  # the tree names no country itself; the tag
                              # comes from a sibling tree in the same file

    @property
    def own_count(self) -> int:
        return max(0, self.focus_count - self.shared_count)


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


def _shared_graph(text: str) -> dict:
    """``{shared focus id: [prerequisite ids]}`` for every top-level
    ``shared_focus = { }`` block — just enough to count what a tree can see."""
    graph: dict = {}
    for m in _SHARED_START.finditer(text):
        brace = m.end() - 1
        body = text[brace + 1:_match_brace(text, brace)]
        sid, prereqs = "", []
        for key, kind, val in _statements(body):
            k = key.lower()
            if kind == "scalar" and k == "id" and not sid:
                sid = val
            elif kind == "block" and k == "prerequisite":
                prereqs.extend(f for k2, kk, f in _statements(val)
                               if kk == "scalar" and k2.lower() == "focus")
        if sid:
            graph[sid] = prereqs
    return graph


def _visible_count(graph: dict, refs) -> int:
    """How many shared focuses in ``graph`` a tree referencing ``refs`` sees:
    the referenced roots plus everything that transitively requires one."""
    start = [r for r in refs if r in graph]
    if not start:
        return 0
    children: dict = {}
    for sid, prereqs in graph.items():
        for p in prereqs:
            if p in graph:
                children.setdefault(p, []).append(sid)
    seen: set = set()
    stack = list(start)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, ()))
    return len(seen)


def _trees_in_file(path: str, roots: tuple = ()) -> list:
    """Every focus_tree declared in a single .txt file, as FocusTreeRefs."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    text = _strip_comments(raw)
    shared = None          # built lazily: most files have no shared focuses
    found = []             # (tree_id, tags, count, shared count)
    trees_in_file = 0      # every focus_tree block, importable on its own or not
    for m in _TREE_START.finditer(text):
        trees_in_file += 1
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
        # Shared focuses defined in THIS file that the tree pulls in through
        # its `shared_focus = X` lines count too — a tree made only of shared
        # branches is still a real, importable tree.
        refs = _SHARED_REF.findall(block)
        shared_count = 0
        if refs:
            if shared is None:
                shared = _shared_graph(text)
            shared_count = _visible_count(shared, refs)
            count += shared_count
        if count == 0:
            continue
        found.append((tid.group(1) if tid else "(unknown)", tags, count, shared_count))
    # A file's secondary trees are usually switched to with load_focus_tree and
    # carry no tag of their own (`country = { base = 0 }`). When every tagged
    # tree in the file names the same tag list, the untagged ones belong to
    # that country too — list them there instead of under "?".
    tagged = [tags for _tid, tags, _n, _s in found if tags]
    inherit = tagged[0] if tagged and all(t == tagged[0] for t in tagged) else []
    out = []
    for tree_id, tags, count, shared_count in found:
        for tag in (tags or inherit or ["?"]):
            out.append(FocusTreeRef(
                tag=tag,
                tree_id=tree_id,
                focus_count=count,
                file=path,
                roots=roots,
                shared_count=shared_count,
                trees_in_file=trees_in_file,
                inherited_tag=not tags,
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


@dataclass
class _PTree:
    id: str = ""
    focuses: list = field(default_factory=list)      # [_PFocus] own focuses
    shortcuts: list = field(default_factory=list)    # [_PShortcut]
    cfp: FocusPosition = field(default_factory=FocusPosition)
    country_raw: list = field(default_factory=list)
    shared_refs: list = field(default_factory=list)
    extra: list = field(default_factory=list)


def _parse_tree(block: str) -> _PTree:
    pt = _PTree()
    for key, kind, body, quoted in _statements_q(block):
        k = key.lower()
        if k == "focus" and kind == "block":
            pf = _parse_focus(body)
            if pf.id:
                pt.focuses.append(pf)
        elif k == "shortcut" and kind == "block":
            pt.shortcuts.append(_parse_shortcut(body))
        elif k == "continuous_focus_position" and kind == "block":
            xm = re.search(r"\bx\s*=\s*(-?\d+)", body)
            ym = re.search(r"\by\s*=\s*(-?\d+)", body)
            pt.cfp = FocusPosition(x=_to_int(xm.group(1)) if xm else 0,
                                   y=_to_int(ym.group(1)) if ym else 0)
        elif k == "id" and kind == "scalar":
            if not pt.id:
                pt.id = body
        elif k == "country" and kind == "block":
            pt.country_raw = _raw_lines(body)
        elif k == "shared_focus" and kind == "scalar":
            # A REFERENCE to a shared focus (the definition is a top-level
            # block). Kept in order; duplicates are meaningless to the game.
            if body not in pt.shared_refs:
                pt.shared_refs.append(body)
        else:
            # default = yes, reset_on_civilwar = no, initial_show_position, …
            pt.extra.extend(_verbatim(key, kind, body, quoted))
    if not pt.id:
        # No top-level id statement (malformed) — fall back to the first one
        # anywhere in the block, which is what discovery reports.
        tid = _ID.search(block)
        pt.id = tid.group(1) if tid else ""
    return pt


def _parse_file(text: str):
    """``([_PTree], [_PFocus shared])`` for a whole (comment-stripped) file."""
    trees, shared = [], []
    for key, kind, body in _statements(text):
        k = key.lower()
        if kind != "block":
            continue
        if k == "focus_tree":
            trees.append(_parse_tree(body))
        elif k == "shared_focus":
            pf = _parse_focus(body)
            if pf.id:
                shared.append(pf)
        # joint_focus (a focus several countries complete together) is not
        # modelled — it has no home in a single-country project. It is
        # ignored, and therefore NOT re-exported.
    return trees, shared


def _build_focus(pf: _PFocus, pos: tuple, loc: dict, shared: bool = False) -> FocusNodeData:
    reward = CompletionReward(rawLines=pf.reward_raw or None)
    available = AvailabilityRule(rawLines=pf.available_raw) if pf.available_raw else None
    bypass = AvailabilityRule(rawLines=pf.bypass_raw) if pf.bypass_raw else None
    # ai_will_do: base 10 is HOI4's default and the editor's "unset"; modifiers
    # keep their triggers as raw lines (Structure Raw Script can lift them).
    ai_base = None if pf.ai_base is None or pf.ai_base == 10 else pf.ai_base
    ai_mods = [AiModifier(factor=f, add=a,
                          trigger=AvailabilityRule(rawLines=t) if t else None)
               for f, a, t in pf.ai_mods] or None
    return FocusNodeData(
        aiWillDo=ai_base,
        aiModifiers=ai_mods,
        id=pf.id,
        title=loc.get(pf.id, pf.id),
        description=loc.get(pf.id + "_desc", ""),
        icon=pf.icon,
        position=FocusPosition(x=pos[0], y=pos[1]),
        cost=pf.cost,
        filters=pf.filters,
        prerequisites=pf.prereqs,
        mutuallyExclusive=pf.mutex,
        completionReward=reward,
        available=available,
        bypass=bypass,
        shared=shared,
        # The relative anchor is kept for shared focuses only: their x/y are
        # written back relative to it, and an `offset` on the anchor moves the
        # whole chain. Own focuses are simply absolute in the editor.
        relativePositionId=(pf.rel or None) if shared else None,
        offsets=[list(b) for b in pf.offsets] or None,
        extraRawLines=list(pf.extra) or None,
    )


def _build_shortcuts(parsed_shortcuts: list, loc: dict) -> list:
    # Preserve tree order; recover each label from the loc file (fall back to the
    # raw loc key when it isn't localised).
    return [
        FocusShortcut(
            label=loc.get(ps.name, ps.name) if ps.name else "",
            target=ps.target,
            zoomFactor=ps.zoom,
            triggerRawLines=list(ps.trigger_raw),
        )
        for ps in parsed_shortcuts
    ]


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

    ptrees, pshared = _parse_file(text)
    active_i = next((i for i, t in enumerate(ptrees) if t.id == ref.tree_id), -1)
    if active_i < 0:
        raise ValueError(f"focus_tree '{ref.tree_id}' not found in {ref.file}")

    tag = ref.tag if ref.tag and ref.tag != "?" else "TAG"
    id_prefix = (ref.id_prefix or "").strip()
    if id_prefix and not ID_PREFIX_PATTERN.match(id_prefix):
        raise ValueError(
            f"'{id_prefix}' can't be used as a prefix: use letters, digits and "
            f"underscores, starting with a letter (for example {tag}_NEW).")
    # A separate COPY takes one tree; the default import REPLACES the source
    # file on export, so it must carry every tree and shared focus in it.
    copy_mode = bool(id_prefix or (ref.prefix_ids and tag != "TAG"))
    wanted = [ptrees[active_i]] if copy_mode else ptrees

    # localisation: titles + descriptions for every focus id, plus each
    # shortcut's button label (its `name` is a loc key).
    needed = set()
    for pf in [f for t in wanted for f in t.focuses] + pshared:
        needed.add(pf.id)
        needed.add(pf.id + "_desc")
    for pt in wanted:
        for ps in pt.shortcuts:
            if ps.name:
                needed.add(ps.name)
    loc = _load_localisation(roots, needed)

    # Absolute positions. Shared focuses resolve among themselves (and, should
    # one be anchored to a focus of the chosen tree, through that tree); each
    # tree's own focuses resolve within the tree, plus the shared focuses in
    # case one is anchored to a shared branch. BASE positions only — per-tree
    # `offset` blocks are applied by core.multi_tree for the active tree.
    shared_abs = _resolve_positions(ptrees[active_i].focuses + pshared)
    shared_focuses = [_build_focus(pf, shared_abs.get(pf.id, (pf.x, pf.y)), loc, shared=True)
                      for pf in pshared]

    def build_tree(pt: _PTree) -> FocusTreeData:
        abs_pos = _resolve_positions(pshared + pt.focuses)
        return FocusTreeData(
            treeId=pt.id,
            focuses=[_build_focus(pf, abs_pos.get(pf.id, (pf.x, pf.y)), loc)
                     for pf in pt.focuses],
            shortcuts=_build_shortcuts(pt.shortcuts, loc),
            continuousFocusPosition=pt.cfp,
            countryRawLines=list(pt.country_raw),
            sharedFocusRefs=list(pt.shared_refs),
            extraRawLines=list(pt.extra),
        )

    trees = [build_tree(pt) for pt in wanted]
    active = trees[0] if copy_mode else trees[active_i]

    base_name = os.path.basename(ref.file)
    base_stem = base_name[:-4] if base_name.lower().endswith(".txt") else base_name

    tree_id = ref.tree_id
    project_name = f"{ref.tree_id} (imported)"
    # Default: the export REPLACES the file it came from. HOI4 loads every
    # national_focus file it sees, so exporting the edited tree under any other
    # name would define every focus twice and break the tree in-game (no
    # prerequisite lines, nothing startable) — a real user hit exactly that.
    focus_file = base_stem
    mode = "replace"
    country_raw = list(active.countryRawLines)
    tree_raw = list(active.extraRawLines)
    shared_refs = list(active.sharedFocusRefs)
    if copy_mode:
        # A separate COPY of the tree: namespace every id (explicit prefix, or
        # the country tag for "start from the generic tree" — the generic focus
        # ids are global and would collide with MD's own generic_focus) and
        # remap the prerequisite/mutex graph to match. An explicit prefix is
        # applied to EVERY id, even ones that already start with it, so the
        # copy shares no id at all with the original.
        # Only the shared focuses this tree can see come along (as copies with
        # their own prefixed ids, still top-level shared_focus blocks).
        visible = multi_tree.visible_shared_ids(shared_focuses, shared_refs)
        shared_focuses = [f for f in shared_focuses if f.id in visible]
        focuses = active.focuses + shared_focuses
        pref = (id_prefix or tag) + "_"
        if id_prefix:
            rename = {f.id: pref + f.id for f in focuses}
        else:
            rename = {f.id: (f.id if f.id.startswith(pref) else pref + f.id) for f in focuses}
        stem = (id_prefix or tag).lower()
        tree_id = f"{stem}_focus"
        # `has_focus_tree = <original tree>` offsets must follow the tree's
        # new id or the copy would lose its per-tree layout.
        old_tree_ref = re.compile(
            r"(\bhas_focus_tree\s*=\s*)" + re.escape(ref.tree_id) + r"(?![A-Za-z0-9_.\-])")
        for f in focuses:
            f.id = rename.get(f.id, f.id)
            f.prerequisites = map_prereq_groups(f.prerequisites, lambda p: rename.get(p, p))
            f.mutuallyExclusive = [rename.get(m, m) for m in f.mutuallyExclusive]
            if f.available and f.available.completedFocuses:
                f.available.completedFocuses = [rename.get(c, c) for c in f.available.completedFocuses]
            if f.relativePositionId:
                f.relativePositionId = rename.get(f.relativePositionId, f.relativePositionId)
            if f.offsets:
                f.offsets = [[old_tree_ref.sub(lambda m: m.group(1) + tree_id, ln) for ln in block]
                             for block in f.offsets]
        # Shortcut targets point at renamed focuses too.
        for sc in active.shortcuts:
            sc.target = rename.get(sc.target, sc.target)
        # References to shared focuses defined in ANOTHER file keep their id.
        shared_refs = [rename.get(r, r) for r in shared_refs]
        focus_file = f"{stem}_focus"
        project_name = (f"{tag} focus tree (copy)" if id_prefix
                        else f"{tag} focus tree (from generic)")
        mode = "copy"
        # The generated tag-based country block is right for a copy, and a
        # second `default = yes` tree would fight the original for every
        # country without a tree of its own.
        country_raw = []
        tree_raw = [ln for ln in tree_raw if not re.match(r"default\s*=", ln)]
        others, active_index = [], 0
    else:
        others = [t for i, t in enumerate(trees) if i != active_i]
        active_index = active_i

    source = {"file": base_name, "treeId": ref.tree_id, "tag": ref.tag, "mode": mode}
    if len(trees) > 1:
        source["trees"] = len(trees)

    project = FocusForgeProject(
        projectName=project_name,
        countryTag=tag,
        treeId=tree_id,
        continuousFocusPosition=active.continuousFocusPosition,
        focuses=list(active.focuses),
        shortcuts=active.shortcuts,
        exportSettings=ExportSettings(
            modPrefix=tag,
            focusFileName=focus_file,
            localisationPrefix=tag,
        ),
        source=source,
        otherTrees=others,
        activeTreeIndex=active_index,
        sharedPool=sorted(shared_focuses, key=multi_tree.shared_sort_key),
        countryRawLines=country_raw,
        sharedFocusRefs=shared_refs,
        treeRawLines=tree_raw,
    )
    # Shared focuses the active tree can see join its canvas, with the
    # tree's `offset` blocks applied; the rest stay pooled for the other trees.
    multi_tree.pull_visible(project)
    return project
