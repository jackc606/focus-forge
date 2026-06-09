"""Millennium Dawn's global party / sub-ideology index.

MD's ``party_pop_array`` and ``party_index`` use a single, GLOBAL ordering of
24 parties (sub-ideologies) — the same index means the same party in every
country (e.g. index 1 is always "Western Conservatives"). The
``add_relative_party_popularity`` helper picks the party to shift by this index.

Source: MD ``common/scripted_effects/00_subideology_scripted_effects.txt``
(the per-party ``# comment`` labels) + ``attract_voters_pos.*`` localisation for
the two Khomeinist entries (8/9).
"""
from __future__ import annotations

import os
import re

from .ideologies import IDEOLOGY_TREE

# (party_index, display name), ordered by index. Index order roughly groups the
# parties by their top ideology: 0-3 democratic, 4-9 communism (incl. the two
# Vilayat-e Faqih theocracies), 10-12 Islamic, 13-19 neutrality, 20-23 nationalist.
MD_PARTIES = [
    (0, "Western Autocrats"),
    (1, "Western Conservatives"),
    (2, "Western Liberals"),
    (3, "Western Socialists"),
    (4, "Emerging Communists"),
    (5, "Emerging Left-Wing Radicals"),
    (6, "Emerging Reactionaries"),
    (7, "Emerging Autocrats"),
    (8, "Moderate Vilayat-e Faqih"),
    (9, "Vilayat-e Faqih"),
    (10, "Salafist Kingdom"),
    (11, "Salafist Caliphate"),
    (12, "Neutral Moderate Islam"),
    (13, "Neutral Autocrats"),
    (14, "Neutral Conservatives"),
    (15, "Neutral Oligarchs"),
    (16, "Neutral Libertarians"),
    (17, "Neutral Greens"),
    (18, "Neutral Socialists"),
    (19, "Neutral Communists"),
    (20, "Nationalist Populists"),
    (21, "Nationalist Fascists"),
    (22, "Nationalist Military Junta"),
    (23, "Nationalist Monarchists"),
]


# ---------------------------------------------------------------------------
# Per-country party import
# ---------------------------------------------------------------------------
# MD localises each country's parties by SUB-ideology, e.g.
#   CAN.conservatism:      "£can_western_conservative Conservative Party"
#   CAN.conservatism_icon: "£can_western_conservative"
#   CAN.conservatism_desc: ""
# The name carries a leading "£<sprite> " icon token; the _icon line is just the
# sprite; _desc is the politics-screen description (often blank in vanilla MD).
_SUB_TOP = {sub: top for top, subs in IDEOLOGY_TREE.items() for sub in subs}
_LOC_LINE = re.compile(r'^\s*([A-Za-z0-9_.]+):\d*\s*"(.*)"\s*$', re.MULTILINE)


def _strip_icon_prefix(value: str) -> str:
    """A party name value is '£<sprite> <Display Name>'. Drop the leading icon
    token, returning just the display name."""
    v = (value or "").strip()
    if v.startswith("£"):
        parts = v.split(" ", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return v


def parse_country_parties(roots, tag: str) -> list:
    """Every Millennium Dawn party defined for ``tag``, newest-root-wins, as a list
    of dicts: {ideology, subIdeology, name, longName, logoRef, description}.

    Scans ``localisation/**/*_l_english.yml`` for ``<TAG>.<sub>`` keys (and the
    ``_icon`` / ``_desc`` companions). Only sub-ideologies known to MD's ideology
    tree are returned, mapped to their top ideology. Ordered by top ideology then
    sub so the editor lists them predictably."""
    t = (tag or "").strip().upper()
    if not t:
        return []
    prefix = t + "."
    raw: dict = {}
    for root in roots:                       # later roots win (mod load order)
        loc = os.path.join(root, "localisation")
        if not os.path.isdir(loc):
            continue
        for dirpath, _dirs, files in os.walk(loc):
            for fn in files:
                if not fn.lower().endswith("_l_english.yml"):
                    continue
                try:
                    with open(os.path.join(dirpath, fn), "r", encoding="utf-8-sig",
                              errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                for m in _LOC_LINE.finditer(text):
                    key = m.group(1)
                    if key.startswith(prefix):
                        raw[key] = m.group(2)

    fields: dict = {}
    for key, value in raw.items():
        rest = key[len(prefix):]
        if rest.endswith("_icon"):
            sub, kind = rest[:-5], "icon"
        elif rest.endswith("_desc"):
            sub, kind = rest[:-5], "desc"
        else:
            sub, kind = rest, "name"
        fields.setdefault(sub, {})[kind] = value

    parties = []
    for sub, f in fields.items():
        top = _SUB_TOP.get(sub)
        if not top:
            continue  # only real MD sub-ideologies become editable parties
        icon = (f.get("icon") or "").strip()
        if icon.startswith("£"):
            icon = icon[1:].strip()
        name = _strip_icon_prefix(f.get("name", ""))
        desc = (f.get("desc") or "").strip()
        # nothing meaningful for this sub? skip
        if not (name or icon or desc):
            continue
        parties.append({
            "ideology": top,
            "subIdeology": sub,
            "name": name,
            "longName": name,        # MD has no separate long name
            "logoRef": icon,
            "description": desc,
        })

    order = {top: i for i, top in enumerate(IDEOLOGY_TREE)}
    parties.sort(key=lambda p: (order.get(p["ideology"], 99), p["subIdeology"]))
    return parties
