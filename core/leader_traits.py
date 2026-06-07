"""Index HOI4 / Millennium Dawn country-leader traits from
``common/country_leader/*.txt`` (the ``leader_traits = { <id> = { … } }`` blocks)
for the leader editor's trait picker.

Each trait is bucketed into a functional theme by an ordered keyword ruleset (no
built-in categories exist), with the project country's own traits surfaced as a
pinned top group. We also capture each trait's modifier lines so the picker can
show, on hover, what bonuses a trait grants. MD does not replace_path
country_leader → union MD + vanilla (later roots win a trait's effects).
"""
from __future__ import annotations

import glob
import os
import re

_COMMENT = re.compile(r"#.*")
_BLOCK = re.compile(r"\bleader_traits\s*=\s*\{")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{")
_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*")

# Keys inside a trait that aren't player-facing bonuses.
_SKIP_KEYS = {"random", "sprite", "name", "removal_cost", "allowed", "allowed_civil_war"}

THEME_ORDER = ["Ideology & Party", "Personality", "Military", "Economy",
               "Diplomacy", "Intelligence", "Political", "Other"]

# Ordered (label, substrings) — first match wins.
_RULES = [
    ("Ideology & Party", ("western_", "communis", "marxis", "leninis", "maois",
                          "fascis", "nazi", "monarch", "islamis", "salafis",
                          "vilayat", "caliphate", "kingdom_", "theocra", "baath",
                          "ba_ath", "jihad", "autocrac", "democrat", "socialis",
                          "liberal", "conservat", "nationalis", "neutrality",
                          "ideolog", "ruling", "anarchis", "technocrat")),
    ("Military", ("war_", "_war", "general", "militar", "soldier", "command",
                  "guerilla", "guerrilla", "officer", "admiral", "army", "navy",
                  "naval", "air_", "defense_company", "defence", "strateg",
                  "tactic", "veteran", "warrior", "militia", "armed", "marshal")),
    ("Economy", ("econom", "industr", "trade", "tax", "captain_of_industry",
                 "business", "tycoon", "financ", "budget", "oil", "resource",
                 "corporate", "banker", "capitalis", "agrar", "agricultur",
                 "infrastructur", "merchant")),
    ("Diplomacy", ("diplomat", "alliance", "_ally", "ally_", "relation", "peace",
                   "isolationis", "interventionis", "foreign", "treaty", "embassy",
                   "pan_", "unifier")),
    ("Intelligence", ("spy", "intel", "operative", "espionage", "covert",
                      "surveillanc", "secret_police")),
    ("Personality", ("charismat", "popular", "incorrupt", "corrupt", "dictator",
                     "naive", "cynic", "ambitious", "pragmat", "drunk", "ill_",
                     "disease", "old_", "underage", "paranoi", "ruthless",
                     "idealist", "reformer", "populis", "demagog", "figurehead",
                     "puppet", "hero", "beloved", "hated", "young")),
    ("Political", ("politic", "stability", "war_support", "bureaucr", "propagand",
                   "censor", "police", "law", "constitution", "election",
                   "authorit", "revolution")),
]


def classify_trait(trait_id: str) -> str:
    low = trait_id.lower()
    for label, subs in _RULES:
        if any(s in low for s in subs):
            return label
    return "Other"


def _match_brace(text: str, open_idx: int) -> int:
    depth = 0
    j = open_idx
    n = len(text)
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


def _parse_modifiers(body: str) -> list:
    """Top-level scalar modifier (key, value) pairs of a trait — the bonuses it
    grants. Nested blocks (ai_will_do, targeted_modifier, equipment_bonus…) and
    ai_*/metadata keys are skipped."""
    out, i, n = [], 0, len(body)
    while i < n:
        m = _KV.search(body, i)
        if not m:
            break
        key, j = m.group(1), m.end()
        if j < n and body[j] == "{":
            i = _match_brace(body, j) + 1   # nested block — skip
            continue
        vm = re.match(r"\S+", body[j:])
        val = vm.group(0) if vm else ""
        i = j + (vm.end() if vm else 0)
        if key in _SKIP_KEYS or key.startswith("ai_"):
            continue
        out.append((key, val))
    return out


def build_trait_index(roots) -> dict:
    """{trait_id: {"sources": set(filename), "effects": [(key, value)]}}.
    Effects are last-root-wins (MD overrides vanilla); sources is the union."""
    index: dict = {}
    for root in roots:
        d = os.path.join(root, "common", "country_leader")
        if not os.path.isdir(d):
            continue
        for fp in glob.glob(os.path.join(d, "*.txt")):
            base = os.path.basename(fp)
            try:
                text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                             errors="replace").read())
            except OSError:
                continue
            for bm in _BLOCK.finditer(text):
                brace = text.index("{", bm.start())
                body = text[brace + 1:_match_brace(text, brace)]
                i = 0
                while True:
                    km = _KEY.search(body, i)
                    if not km:
                        break
                    tid = km.group(1)
                    tbrace = body.index("{", km.start())
                    tend = _match_brace(body, tbrace)
                    entry = index.setdefault(tid, {"sources": set(), "effects": []})
                    entry["sources"].add(base)
                    entry["effects"] = _parse_modifiers(body[tbrace + 1:tend])
                    i = tend + 1
    return index


def format_trait_tooltip(trait_id: str, effects: list) -> str:
    """Human-readable bonus list for a trait, for a hover tooltip."""
    lines = [trait_id]
    for key, val in effects[:16]:
        try:
            val = f"{float(val):+g}"
        except ValueError:
            pass
        lines.append(f"  {key} = {val}")
    if len(effects) > 16:
        lines.append(f"  … +{len(effects) - 16} more")
    if not effects:
        lines.append("  (no direct modifiers — special / AI trait)")
    return "\n".join(lines)


def group_traits(index: dict, tag: str = "") -> list:
    """[(group_label, [trait_id])] from a built index: the project country's
    traits first (pinned), then functional theme groups (non-empty, sorted)."""
    if not index:
        return []
    t = (tag or "").strip().upper()
    country, buckets = [], {}
    for tid, entry in index.items():
        is_country = bool(t) and any(
            b.upper().startswith(t + "_") or b.upper().startswith(t + " ")
            for b in entry["sources"])
        if is_country:
            country.append(tid)
        else:
            buckets.setdefault(classify_trait(tid), []).append(tid)
    groups = []
    if country:
        groups.append((f"{t} — this country", sorted(country, key=str.lower)))
    for label in THEME_ORDER:
        if buckets.get(label):
            groups.append((label, sorted(buckets[label], key=str.lower)))
    return groups


# ----- thin wrappers (used by tests / callers that pass roots directly) -----
def build_trait_sources(roots) -> dict:
    return {tid: e["sources"] for tid, e in build_trait_index(roots).items()}


def build_trait_groups(roots, tag: str = "") -> list:
    return group_traits(build_trait_index(roots), tag)


def build_trait_tooltips(roots) -> dict:
    return {tid: format_trait_tooltip(tid, e["effects"])
            for tid, e in build_trait_index(roots).items()}
