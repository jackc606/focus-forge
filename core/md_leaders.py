"""Parse a country's preset Millennium Dawn leaders from
``history/countries/<TAG> - <Name>.txt`` — the ``create_country_leader`` blocks
(name, picture, ideology, traits). Used to offer the country's existing leaders in
the "Put leader in power" reward alongside the project's custom leaders."""
from __future__ import annotations

import re

from .country_history import _COMMENT, _find_country_file, _match_brace
from .focus_import import find_focus_trees

_LEADER_BLOCK = re.compile(r"\bcreate_country_leader\s*=\s*\{")
_NAME = re.compile(r'\bname\s*=\s*"([^"]*)"')
_PICTURE = re.compile(r'\bpicture\s*=\s*"?([^"\s}]+)"?')
_IDEOLOGY = re.compile(r"\bideology\s*=\s*(\w+)")
_TRAITS = re.compile(r"\btraits\s*=\s*\{([^}]*)\}")


def _leaders_from_text(text: str):
    for m in _LEADER_BLOCK.finditer(text):
        brace = text.index("{", m.start())
        body = text[brace + 1:_match_brace(text, brace)]
        nm = _NAME.search(body)
        if not nm:
            continue
        name = nm.group(1).strip()
        if not name:
            continue
        pic = _PICTURE.search(body)
        ideo = _IDEOLOGY.search(body)
        tr = _TRAITS.search(body)
        yield {
            "name": name,
            "picture": pic.group(1).strip() if pic else "",
            "ideology": ideo.group(1).strip() if ideo else "",
            "traits": tr.group(1).split() if tr else [],
        }


def parse_country_leaders(roots, tag: str) -> list:
    """[{name, picture, ideology, traits[]}] for ``tag`` — its history starting
    leader plus every leader its focus tree installs via create_country_leader.
    De-duped by name; later roots win via the shared lookups. Empty if none."""
    t = (tag or "").strip().upper()
    if not t:
        return []
    files = []
    fp = _find_country_file(roots, t)
    if fp:
        files.append(fp)
    try:
        for ref in find_focus_trees(roots):
            if ref.tag == t and ref.file not in files:
                files.append(ref.file)
    except Exception:
        pass

    out, seen = [], set()
    for path in files:
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                text = _COMMENT.sub("", f.read())
        except OSError:
            continue
        for d in _leaders_from_text(text):
            if d["name"] in seen:
                continue
            seen.add(d["name"])
            out.append(d)
    return out
