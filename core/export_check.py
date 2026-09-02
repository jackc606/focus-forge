"""Smoke-check an export before (and after) HOI4 sees it.

Two halves:

**Pre-flight** — ``smoke_check(files)`` parses every generated file with the
app's own Paradox-script reader and applies the structural rules the game
enforces at load: balanced braces and quotes, a single ``focus_tree`` with an
id and unique focus ids whose prerequisite / mutually-exclusive / relative-
position references resolve, events inside their namespace with a title and an
option and a way to fire, localisation files with the ``l_english:`` header, a
BOM and well-formed entries, sprite blocks with a name and texture — plus the
cross-file check that every focus, idea and event actually has localisation.
Validation of the *project* catches design mistakes; this catches "the file
the game reads is malformed", which is what testers otherwise discover by
launching and reading error.log.

**Post-flight** — ``scan_error_log(files, project)`` reads HOI4's
``logs/error.log`` after a launch and keeps only the lines that mention this
mod (its files, its focus/idea/event ids, its event namespace), mapping a
``file: … line: N`` reference back to the enclosing focus id so the user lands
on the right card instead of counting lines.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .focus_import import _parse_focus, _statements, _strip_comments
from .types import ValidationIssue

_LOC_HEADER = "l_english:"
_LOC_LINE = re.compile(r'^\s([A-Za-z0-9_.\-]+):(\d*)\s*"(.*)"\s*(#.*)?$')
_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
# Paradox strings never span lines: a quote with no closing quote on its line is
# an error (the game reads to the next quote and mangles everything between).
_TOKEN = re.compile(r'"[^"\n]*"|"[^"\n]*$|\{|\}|<=|>=|!=|==|[=<>]|[^\s{}=<>"#]+|#[^\n]*|\n',
                    re.MULTILINE)


def _err(issues, code, msg, focus_id=None):
    issues.append(ValidationIssue(severity="error", code=code, message=msg, focusId=focus_id))


def _warn(issues, code, msg, focus_id=None):
    issues.append(ValidationIssue(severity="warning", code=code, message=msg, focusId=focus_id))


# ---------------------------------------------------------------------------
# Structural parse with line numbers
# ---------------------------------------------------------------------------
def parse_script(text: str) -> list:
    """Structural problems as ``[(line, message)]``: unbalanced braces, an
    unterminated string, an operator with nothing before or after it, a value
    with no key. Empty list = the game's parser will get through the file."""
    problems: list = []
    depth = 0
    line = 1
    prev = None            # previous significant token kind: 'word' | 'op' | 'open' | 'close' | None
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        if tok == "\n":
            line += 1
            continue
        if tok.startswith("#"):
            continue
        if tok.startswith('"') and (len(tok) == 1 or not tok.endswith('"')):
            problems.append((line, "unterminated string"))
            prev = "word"
            continue
        if tok in ("=", "<", ">", "<=", ">=", "!=", "=="):
            if prev != "word":
                problems.append((line, f"'{tok}' has no key before it"))
            prev = "op"
            continue
        if tok == "{":
            depth += 1
            if prev == "op":
                pass
            elif prev == "word":
                problems.append((line, "'{' after a bare word (missing '=')"))
            prev = "open"
            continue
        if tok == "}":
            depth -= 1
            if depth < 0:
                problems.append((line, "'}' closes a block that was never opened"))
                depth = 0
            if prev == "op":
                problems.append((line, "'=' with no value before '}'"))
            prev = "close"
            continue
        # word / quoted string
        prev = "word"
    if prev == "op":
        problems.append((line, "file ends after '=' with no value"))
    if depth > 0:
        problems.append((line, f"{depth} unclosed '{{'"))
    return problems


# ---------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------
def _check_focus_tree(rel: str, text: str, issues: list) -> dict:
    """Returns {"focus_ids": [...]} for the cross-file loc check."""
    body = _strip_comments(text)
    trees = [(k, v) for k, kind, v in _statements(body) if kind == "block" and k.lower() == "focus_tree"]
    out = {"focus_ids": []}
    if not trees:
        _err(issues, "export.focus.noTree", f"{rel}: no focus_tree block.")
        return out
    if len(trees) > 1:
        _err(issues, "export.focus.multipleTrees", f"{rel}: {len(trees)} focus_tree blocks — one per file.")
    _k, tree = trees[0]
    stmts = list(_statements(tree))
    if not any(kind == "scalar" and k.lower() == "id" for k, kind, _v in stmts):
        _err(issues, "export.focus.treeId", f"{rel}: focus_tree has no id.")
    if not any(kind == "block" and k.lower() == "country" for k, kind, _v in stmts):
        _warn(issues, "export.focus.country", f"{rel}: focus_tree has no country = {{ }} block — no country will use it.")
    parsed = [_parse_focus(v) for k, kind, v in stmts if kind == "block" and k.lower() == "focus"]
    ids: list = []
    for pf in parsed:
        if not pf.id:
            _err(issues, "export.focus.noId", f"{rel}: a focus has no id.")
            continue
        if pf.id in ids:
            _err(issues, "export.focus.duplicateId", f"{rel}: focus id {pf.id} appears twice.", pf.id)
        ids.append(pf.id)
    idset = set(ids)
    for pf in parsed:
        if not pf.id:
            continue
        for blk in pf.prereqs:
            for p in (blk if isinstance(blk, list) else [blk]):
                if p not in idset:
                    _err(issues, "export.focus.prereqMissing",
                         f"{rel}: {pf.id} requires {p}, which is not in this tree.", pf.id)
        for m in pf.mutex:
            if m not in idset:
                _err(issues, "export.focus.mutexMissing",
                     f"{rel}: {pf.id} is mutually exclusive with {m}, which is not in this tree.", pf.id)
        if pf.rel and pf.rel not in idset:
            _err(issues, "export.focus.relativeMissing",
                 f"{rel}: {pf.id} is positioned relative to {pf.rel}, which is not in this tree.", pf.id)
        if not pf.icon:
            _warn(issues, "export.focus.noIcon", f"{rel}: {pf.id} has no icon.", pf.id)
    out["focus_ids"] = ids
    return out


def _check_ideas(rel: str, text: str, issues: list) -> dict:
    body = _strip_comments(text)
    top = [(k, v) for k, kind, v in _statements(body) if kind == "block" and k.lower() == "ideas"]
    ids: list = []
    if not top:
        _err(issues, "export.ideas.noBlock", f"{rel}: no ideas = {{ }} block.")
        return {"idea_ids": ids}
    for _k, v in top:
        for cat, kind, cv in _statements(v):
            if kind != "block":
                continue
            for iid, ikind, _iv in _statements(cv):
                if ikind == "block":
                    if not _ID_RE.match(iid):
                        _err(issues, "export.ideas.badId", f"{rel}: idea id {iid!r} has illegal characters.")
                    if iid in ids:
                        _err(issues, "export.ideas.duplicateId", f"{rel}: idea {iid} defined twice.")
                    ids.append(iid)
    return {"idea_ids": ids}


def _check_events(rel: str, text: str, issues: list) -> dict:
    body = _strip_comments(text)
    stmts = list(_statements(body))
    namespaces = [v for k, kind, v in stmts if kind == "scalar" and k.lower() == "add_namespace"]
    events: list = []       # (id, option_keys, hidden)
    if not namespaces:
        _err(issues, "export.events.noNamespace", f"{rel}: no add_namespace — every event id needs one.")
    for k, kind, v in stmts:
        if kind != "block" or k.lower() not in ("country_event", "news_event", "state_event", "unit_leader_event"):
            continue
        inner = list(_statements(v))
        eid = next((iv for ik, ikind, iv in inner if ikind == "scalar" and ik.lower() == "id"), "")
        if not eid:
            _err(issues, "export.events.noId", f"{rel}: an event has no id.")
            continue
        ns = eid.rsplit(".", 1)[0] if "." in eid else ""
        if namespaces and ns not in namespaces:
            _err(issues, "export.events.namespace",
                 f"{rel}: event {eid} is outside the declared namespace(s) {', '.join(namespaces)}.")
        keys = {ik.lower() for ik, _kk, _iv in inner}
        hidden = any(ik.lower() == "hidden" and iv.lower() == "yes" for ik, ikind, iv in inner if ikind == "scalar")
        options = [iv for ik, ikind, iv in inner if ikind == "block" and ik.lower() == "option"]
        if not hidden and "title" not in keys:
            _warn(issues, "export.events.noTitle", f"{rel}: event {eid} has no title.")
        if not hidden and not options:
            _err(issues, "export.events.noOption", f"{rel}: event {eid} has no option — the game cannot close it.")
        fires = ({"is_triggered_only", "trigger", "mean_time_to_happen", "fire_only_once"} & keys)
        if not fires:
            _warn(issues, "export.events.neverFires",
                  f"{rel}: event {eid} has neither is_triggered_only nor a trigger — it will never fire.")
        opt_names = []
        for ov in options:
            name = next((v2 for k2, kk2, v2 in _statements(ov) if kk2 == "scalar" and k2.lower() == "name"), "")
            if name:
                opt_names.append(name)
        events.append((eid, opt_names, hidden))
    return {"events": events}


def _check_localisation(rel: str, text: str, bom: bool, issues: list) -> dict:
    keys: dict = {}
    if not bom:
        _err(issues, "export.loc.bom", f"{rel}: localisation must be written with a UTF-8 BOM or the game ignores it.")
    if not rel.lower().endswith("_l_english.yml"):
        _err(issues, "export.loc.filename", f"{rel}: localisation file names must end in _l_english.yml.")
    lines = text.split("\n")
    first = next((ln for ln in lines if ln.strip()), "")
    if first.strip() != _LOC_HEADER:
        _err(issues, "export.loc.header", f"{rel}: first line must be '{_LOC_HEADER}' (got {first.strip()!r}).")
    for n, ln in enumerate(lines, start=1):
        s = ln.rstrip("\r")
        if not s.strip() or s.strip() == _LOC_HEADER or s.lstrip().startswith("#"):
            continue
        m = _LOC_LINE.match(s)
        if not m:
            _err(issues, "export.loc.entry", f"{rel}:{n}: malformed localisation line: {s.strip()[:80]}")
            continue
        key, value = m.group(1), m.group(3)
        if key in keys:
            _warn(issues, "export.loc.duplicate", f"{rel}:{n}: key {key} defined twice (last one wins).")
        keys[key] = value
        # an unescaped quote inside the text ends the string early in-game
        if re.search(r'(?<!\\)"', value):
            _err(issues, "export.loc.quote", f"{rel}:{n}: {key} contains an unescaped double quote.")
    return {"loc_keys": keys}


def _check_gfx(rel: str, text: str, issues: list) -> None:
    body = _strip_comments(text)
    for k, kind, v in _statements(body):
        if kind != "block" or k.lower() != "spritetypes":
            continue
        for sk, skind, sv in _statements(v):
            if skind != "block":
                continue
            inner = {ik.lower(): iv for ik, ikind, iv in _statements(sv) if ikind == "scalar"}
            if "name" not in inner:
                _err(issues, "export.gfx.noName", f"{rel}: a {sk} has no name.")
            if sk.lower() in ("spritetype", "corneredtilespritetype") and "texturefile" not in inner:
                _err(issues, "export.gfx.noTexture", f"{rel}: sprite {inner.get('name', '?')} has no texturefile.")


def _check_generic(rel: str, text: str, issues: list) -> None:
    """Everything else that is Paradox script: decisions, on_actions, history."""
    body = _strip_comments(text)
    if not list(_statements(body)) and body.strip():
        _warn(issues, "export.script.empty", f"{rel}: no statements could be read from the file.")


# ---------------------------------------------------------------------------
# Whole-export smoke check
# ---------------------------------------------------------------------------
def smoke_check(files) -> list:
    """Parse and structurally check every exported file (``ExportedFile`` list
    or objects with ``relativePath`` / ``content`` / ``bom``), then check that
    focuses, ideas and events are localised. Returns ValidationIssues."""
    issues: list = []
    focus_ids: list = []
    idea_ids: list = []
    events: list = []
    loc_keys: dict = {}
    for f in files or []:
        rel = f.relativePath.replace("\\", "/")
        text = f.content or ""
        low = rel.lower()
        if low.endswith(".yml"):
            loc_keys.update(_check_localisation(rel, text, bool(getattr(f, "bom", False)), issues)["loc_keys"])
            continue
        if not (low.endswith(".txt") or low.endswith(".gfx") or low.endswith(".mod")):
            continue
        for line, msg in parse_script(text):
            _err(issues, "export.parse", f"{rel}:{line}: {msg}.")
        if any(i.code == "export.parse" and i.message.startswith(rel + ":") for i in issues):
            continue  # structural checks on a broken file only add noise
        if low.startswith("common/national_focus/"):
            focus_ids += _check_focus_tree(rel, text, issues)["focus_ids"]
        elif low.startswith("common/ideas/"):
            idea_ids += _check_ideas(rel, text, issues)["idea_ids"]
        elif low.startswith("events/"):
            events += _check_events(rel, text, issues)["events"]
        elif low.endswith(".gfx"):
            _check_gfx(rel, text, issues)
        else:
            _check_generic(rel, text, issues)

    if loc_keys or focus_ids or idea_ids or events:
        for fid in focus_ids:
            if fid not in loc_keys:
                _warn(issues, "export.loc.missingFocus", f"{fid} has no localised title — it shows as its id in-game.", fid)
            if f"{fid}_desc" not in loc_keys:
                _warn(issues, "export.loc.missingFocusDesc", f"{fid} has no description text ({fid}_desc).", fid)
        for iid in idea_ids:
            if iid not in loc_keys:
                _warn(issues, "export.loc.missingIdea", f"idea {iid} has no localised name.")
        for eid, opts, hidden in events:
            if hidden:
                continue
            if f"{eid}.t" not in loc_keys:
                _warn(issues, "export.loc.missingEvent", f"event {eid} has no title text ({eid}.t).")
            if f"{eid}.d" not in loc_keys:
                _warn(issues, "export.loc.missingEvent", f"event {eid} has no description text ({eid}.d).")
            for name in opts:
                if name not in loc_keys:
                    _warn(issues, "export.loc.missingOption", f"event {eid}: option {name} has no text.")
    return issues


# ---------------------------------------------------------------------------
# Post-flight: HOI4 error.log
# ---------------------------------------------------------------------------
@dataclass
class LogHit:
    time: str = ""
    source: str = ""
    message: str = ""
    file: str = ""
    line: int = 0
    focusId: str = ""
    matched: list = field(default_factory=list)
    raw: str = ""


_LOG_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\[([^\]]*)\]\[([^\]]*)\]:\s*(.*)$")
_LOG_FILE_REF = re.compile(r'file:\s*"?([^"\s]+?\.(?:txt|yml|gfx))"?\s*(?:near\s+)?line:\s*(\d+)', re.IGNORECASE)
_FOCUS_ID_LINE = re.compile(r"^\t\tid\s*=\s*(\S+)")


def default_error_log() -> str:
    """HOI4's error.log under the user's Documents (the launcher's default)."""
    home = Path.home()
    for base in (home / "Documents", home / "OneDrive" / "Documents"):
        p = base / "Paradox Interactive" / "Hearts of Iron IV" / "logs" / "error.log"
        if p.is_file():
            return str(p)
    return str(home / "Documents" / "Paradox Interactive" / "Hearts of Iron IV" / "logs" / "error.log")


def log_needles(project, files, mod_dir: str = "") -> list:
    """Strings that identify THIS mod in a log line: its file paths, mod folder
    name, event namespace, and every focus / idea / event id."""
    needles: set = set()
    for f in files or []:
        needles.add(f.relativePath.replace("\\", "/"))
        needles.add(os.path.basename(f.relativePath))
    if mod_dir:
        needles.add(os.path.basename(os.path.normpath(mod_dir)))
    if project is not None:
        for fo in project.focuses:
            if fo.id:
                needles.add(fo.id)
        for i in project.ideas:
            if i.id:
                needles.add(i.id)
        for e in project.events:
            if e.id:
                needles.add(e.id)
        prefix = (project.exportSettings.localisationPrefix or "").strip()
        if prefix:
            needles.add(prefix + ".")
        if project.exportSettings.focusFileName:
            needles.add(project.exportSettings.focusFileName)
    return sorted(n for n in needles if n and len(n) >= 4)


def _focus_at_line(content: str, line: int) -> str:
    current = ""
    for n, ln in enumerate((content or "").split("\n"), start=1):
        m = _FOCUS_ID_LINE.match(ln)
        if m:
            current = m.group(1)
        if n >= line:
            return current
    return current


def attribute_focus(files, rel_path: str, line: int, mod_dir: str = "") -> str:
    """The focus id whose block contains ``line`` of the file at ``rel_path``.
    Prefers the file ON DISK in ``mod_dir`` (what the game actually read); falls
    back to the in-memory export. '' when unknown."""
    target = rel_path.replace("\\", "/").lower()
    if mod_dir:
        disk = Path(mod_dir) / rel_path.replace("\\", "/")
        if disk.is_file():
            try:
                return _focus_at_line(disk.read_text(encoding="utf-8-sig", errors="replace"), line)
            except OSError:
                pass
    for f in files or []:
        rel = f.relativePath.replace("\\", "/").lower()
        if rel == target or rel.endswith("/" + target) or target.endswith("/" + rel) or target.endswith(rel):
            return _focus_at_line(f.content, line)
    return ""


def log_is_stale(path: str = None, mod_dir: str = "") -> bool:
    """True when the mod folder was written AFTER error.log was last touched —
    the log then describes an older export and its line numbers may be off."""
    path = path or default_error_log()
    try:
        log_m = os.path.getmtime(path)
    except OSError:
        return False
    newest = 0.0
    if mod_dir and os.path.isdir(mod_dir):
        for dirpath, _d, files in os.walk(mod_dir):
            for fn in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(dirpath, fn)))
                except OSError:
                    pass
    return newest > log_m


def scan_error_log(files, project=None, path: str = None, mod_dir: str = "",
                   since: str = "") -> list:
    """Lines of HOI4's error.log that mention this mod, as LogHits. ``since`` is
    an optional ``HH:MM:SS`` — only entries at or after it (the launch you just
    did). Missing log → empty list (callers report that separately)."""
    path = path or default_error_log()
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    needles = log_needles(project, files, mod_dir)
    lowered = [(n, n.lower()) for n in needles]
    hits: list = []
    seen: set = set()
    for raw in text.splitlines():
        m = _LOG_LINE.match(raw)
        if not m:
            continue
        t, _date, source, msg = m.groups()
        if since and t < since:
            continue
        low = msg.lower()
        matched = [n for n, nl in lowered if nl in low]
        if not matched:
            continue
        key = (source, msg)
        if key in seen:
            continue
        seen.add(key)
        hit = LogHit(time=t, source=source, message=msg, matched=matched, raw=raw)
        fm = _LOG_FILE_REF.search(msg)
        if fm:
            hit.file, hit.line = fm.group(1), int(fm.group(2))
            hit.focusId = attribute_focus(files, hit.file, hit.line, mod_dir)
        hits.append(hit)
    return hits


def format_hits(hits) -> str:
    if not hits:
        return "No lines in HOI4's error.log mention this mod."
    out = []
    for h in hits:
        where = f" → {h.focusId}" if h.focusId else ""
        loc = f" ({h.file}:{h.line})" if h.file else ""
        out.append(f"[{h.time}] {h.message}{loc}{where}")
    return "\n".join(out)
