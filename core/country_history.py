"""Read a country's STARTING politics from MD's ``history/countries/<TAG> - <Name>.txt``
so the Country editor can auto-fill its Politics tab.

Each file holds ``set_popularities = { democratic = N communism = N … }`` (the 5
top ideologies; values may be ints or decimals) and ``set_politics = {
ruling_party = <top ideology> last_election = "YYYY.M.D" election_frequency = N
elections_allowed = yes/no }``. MD replace_path's history/countries, so only the
effective (MD-onward) roots are scanned. A few niche countries use
``party_pop_array^N`` instead of set_popularities — those return None (no autofill).
"""
from __future__ import annotations

import glob
import os
import re

from .ideologies import TOP_IDEOLOGIES
from .mod_paths import effective_roots_for_path

_COMMENT = re.compile(r"#.*")
_POP_BLOCK = re.compile(r"\bset_popularities\s*=\s*\{")
_POLITICS_BLOCK = re.compile(r"\bset_politics\s*=\s*\{")
_KV_NUM = re.compile(r"([A-Za-z_]+)\s*=\s*(-?\d+(?:\.\d+)?)")
_RULING = re.compile(r"\bruling_party\s*=\s*(\w+)")
_LAST_ELECTION = re.compile(r'\blast_election\s*=\s*"?([0-9.]+)"?')
_FREQ = re.compile(r"\belection_frequency\s*=\s*(\d+)")
_ALLOWED = re.compile(r"\belections_allowed\s*=\s*(yes|no)")


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


def _find_country_file(roots, tag: str):
    """The history/countries file for ``tag`` across the effective roots (later
    roots win). Matches the part of the filename before ' - ' against the tag."""
    t = (tag or "").strip().upper()
    if not t:
        return None
    found = None
    for root in effective_roots_for_path(roots, "history/countries"):
        cd = os.path.join(root, "history", "countries")
        if not os.path.isdir(cd):
            continue
        for fp in glob.glob(os.path.join(cd, "*.txt")):
            stem = os.path.basename(fp).rsplit(".", 1)[0]
            file_tag = stem.split(" - ", 1)[0].strip().upper()
            if file_tag == t:
                found = fp  # keep scanning so a later root overrides
    return found


def parse_starting_politics(roots, tag: str):
    """MD starting politics for ``tag`` as a dict, or None if no file / no
    set_popularities block. Keys: popularities {ideo: float}, rulingParty,
    lastElection, electionFrequency, electionsAllowed."""
    fp = _find_country_file(roots, tag)
    if not fp:
        return None
    try:
        text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                     errors="replace").read())
    except OSError:
        return None

    pm = _POP_BLOCK.search(text)
    if not pm:
        return None  # e.g. party_pop_array countries — nothing to autofill
    brace = text.index("{", pm.start())
    body = text[brace + 1:_match_brace(text, brace)]
    pops = {}
    for key, val in _KV_NUM.findall(body):
        if key in TOP_IDEOLOGIES:
            pops[key] = float(val)
    if not pops:
        return None

    out = {
        "popularities": pops,
        "rulingParty": "",
        "lastElection": "",
        "electionFrequency": 48,
        "electionsAllowed": True,
    }
    sm = _POLITICS_BLOCK.search(text)
    if sm:
        sbrace = text.index("{", sm.start())
        sbody = text[sbrace + 1:_match_brace(text, sbrace)]
        rm = _RULING.search(sbody)
        if rm:
            out["rulingParty"] = rm.group(1)
        lm = _LAST_ELECTION.search(sbody)
        if lm:
            out["lastElection"] = lm.group(1)
        fm = _FREQ.search(sbody)
        if fm:
            out["electionFrequency"] = int(fm.group(1))
        am = _ALLOWED.search(sbody)
        if am:
            out["electionsAllowed"] = am.group(1) == "yes"
    return out
