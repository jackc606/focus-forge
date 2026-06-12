"""Build the comprehensive list of idea modifiers for the New Idea editor.

Two sources, unioned:
  * the base game's ``documentation/modifiers_documentation.md`` (the ~755
    modifiers HOI4 recognises, listed per scope), and
  * the modifier keys Millennium Dawn actually uses inside its ideas
    (``common/ideas/*.txt`` ``modifier``/``targeted_modifier`` blocks) — this
    catches MD's hundreds of custom modifiers that aren't in the base doc.

Each modifier is then bucketed into a *functional theme* group (Trade,
Diplomacy, …) via an ordered keyword ruleset, for a browsable grouped dropdown.
"""
from __future__ import annotations

import glob
import os
import re
from collections import Counter

from .mod_paths import effective_roots_for_path
from .pdx_loc import _read_loc_lines
from .presets import COMMON_IDEA_MODIFIERS
from .tech_index import _COMMENT, _match_brace

# A documentation bullet: `* [modifier_name](#anchor)`. Anchors that start with
# `modifiers-for-scope-` are the per-scope table-of-content links, not modifiers.
_DOC_BULLET = re.compile(r"^\*\s*\[([A-Za-z0-9_]+)\]\(#([A-Za-z0-9_-]+)\)", re.MULTILINE)
# Inside a modifier block: `key = <number>` scalar assignments.
_MOD_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*-?\d")
_MOD_BLOCK = re.compile(r"\b(?:targeted_)?modifier\s*=\s*\{")


# ---------------------------------------------------------------------------
# Functional-theme classification
# ---------------------------------------------------------------------------
GROUP_ORDER = [
    "Trade", "Diplomacy", "Politics & Power", "Economy & Industry",
    "Stability & Unrest", "Construction", "Manpower", "Army", "Air",
    "Naval", "Intelligence", "Research", "Other",
]

# Ordered (label, substrings) — FIRST match wins, so order is load-bearing:
# narrower / higher-priority themes come before broader ones (Trade before the
# Economy bucket, Politics before Army, Air before Naval, …).
_RULES = [
    ("Trade", ("trade", "export", "import", "embargo")),
    ("Diplomacy", ("opinion", "relation", "wargoal", "war_goal", "justify",
                   "guarantee", "influence", "faction", "lend_lease", "lendlease",
                   "annex", "puppet", "subject", "autonomy", "peace", "volunteer",
                   "join_", "diplomat")),
    ("Politics & Power", ("political_power", "_drift", "drift_defence", "party_popularity",
                          "democratic", "communism", "fascism", "neutrality", "nationalist",
                          "war_support", "ideology", "election", "legitimacy",
                          "mobiliz", "mobilis", "governing", "command_power")),
    # Construction before Economy so building-speed modifiers (production_speed_
    # buildings_factor, *_infrastructure_*) land here rather than in Economy's
    # broad production_speed bucket.
    ("Construction", ("construction", "building", "infrastructure", "repair",
                      "refit", "fortification", "line_change", "fort_")),
    ("Economy & Industry", ("industr", "factory", "factories", "consumer_goods",
                            "production_speed", "production_factory", "production_efficiency",
                            "tax", "corruption", "cost_factor", "cost_multiplier",
                            "social_cost", "expenditure", "budget", "oil", "fuel",
                            "resource", "economy", "gdp", "dockyard", "license", "conversion")),
    ("Stability & Unrest", ("stability", "unrest", "resistance", "compliance",
                            "non_core", "surrender_limit", "weariness")),
    ("Manpower", ("manpower", "conscription", "recruitable", "monthly_population",
                  "population", "training_time")),
    ("Army", ("army", "land_", "division", "_org", "org_", "morale", "planning",
              "combat", "terrain", "supply", "attrition", "breakthrough", "attack",
              "defence", "defense", "entrenchment", "cavalry", "armor", "armour",
              "motorized", "mechanized", "infantry", "experience")),
    ("Air", ("air_", "_air", "aircraft", "airforce", "bomber", "fighter",
             "air_mission", "strategic_bombing", "anti_air", "ground_attack")),
    ("Naval", ("naval", "navy", "ship", "fleet", "submarine", "convoy",
               "carrier", "port", "amphibious")),
    ("Intelligence", ("intel", "spy", "operative", "decryption", "encryption",
                      "cipher", "agency", "covert", "subversion")),
    ("Research", ("research", "tech_", "_tech", "ahead_of_time", "doctrine_cost")),
]


def classify_modifier(name: str) -> str:
    """Functional theme group label for a modifier name (first matching rule)."""
    low = name.lower()
    for label, subs in _RULES:
        if any(s in low for s in subs):
            return label
    return "Other"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def build_base_modifier_names(roots) -> set:
    """Every modifier name in any root's documentation/modifiers_documentation.md.

    The doc lives in the GAME ROOT (not a common/ subdir), so we iterate roots
    directly rather than via replace_path. Returns an empty set if none found.
    """
    names = set()
    for root in roots:
        doc = os.path.join(root, "documentation", "modifiers_documentation.md")
        if not os.path.isfile(doc):
            continue
        try:
            text = open(doc, "r", encoding="utf-8-sig", errors="replace").read()
        except OSError:
            continue
        for m in _DOC_BULLET.finditer(text):
            name, anchor = m.group(1), m.group(2)
            if anchor.startswith("modifiers-for-scope-"):
                continue  # a table-of-content scope link, not a modifier
            names.add(name)
    return names


def _iter_md_idea_modifier_keys(roots):
    """Yield every modifier key (WITH repeats) declared inside brace-matched
    modifier/targeted_modifier blocks in common/ideas/*.txt — so callers can
    either collect a set or count usage frequency."""
    for root in effective_roots_for_path(roots, "common/ideas"):
        idir = os.path.join(root, "common", "ideas")
        if not os.path.isdir(idir):
            continue
        for fp in glob.glob(os.path.join(idir, "*.txt")):
            try:
                text = _COMMENT.sub("", open(fp, "r", encoding="utf-8-sig",
                                             errors="replace").read())
            except OSError:
                continue
            for bm in _MOD_BLOCK.finditer(text):
                brace = text.index("{", bm.start())
                body = text[brace + 1:_match_brace(text, brace)]
                for key in _MOD_KEY.findall(body):
                    if key != "tag":  # the targeted_modifier `tag` target, not a modifier
                        yield key


def build_md_idea_modifier_keys(roots) -> set:
    """Distinct modifier keys harvested from common/ideas/*.txt."""
    return set(_iter_md_idea_modifier_keys(roots))


def build_common_modifiers(roots, limit: int = 20) -> list:
    """The ``limit`` most-frequently-used modifier keys across MD's own ideas —
    the genuinely common ones a modder reaches for. Falls back to the curated
    ``COMMON_IDEA_MODIFIERS`` when no game files are configured. Ordered
    most-used first."""
    counts = Counter(_iter_md_idea_modifier_keys(roots))
    if not counts:
        return list(COMMON_IDEA_MODIFIERS[:limit])
    return [name for name, _ in counts.most_common(limit)]


# ---------------------------------------------------------------------------
# Human-readable tooltips from the game's MODIFIER_* localisation
# ---------------------------------------------------------------------------
# `[ MODIFIER_<NAME>(_DESC)?:<ver> "text"`  — _DESC is the long sentence form;
# the bare key is the short display name.
_MODIFIER_LOC = re.compile(r'^\s*MODIFIER_([A-Z0-9_]+?)(_DESC)?:\d*\s*"(.*)"\s*$')
# HOI4 loc markup we strip for a clean tooltip: §Y..§! colour codes, £icon
# sprite refs, $VAR$ references, [scripted] segments.
_LOC_MARKUP = re.compile(r"§.|£\w+|\$[^$]*\$|\[[^\]]*\]")


def _clean_loc(text: str) -> str:
    return " ".join(_LOC_MARKUP.sub("", text).split()).strip()


def build_modifier_tooltips(roots) -> dict:
    """{modifier_name(lower): tooltip} from each root's English localisation.

    Prefers the long ``MODIFIER_<NAME>_DESC`` sentence, combined with the short
    display name; falls back to whichever is present. Later roots win (mod load
    order), so a mod's override of a base-game modifier's text takes precedence.
    """
    names: dict = {}
    descs: dict = {}
    for root in roots:
        loc = os.path.join(root, "localisation")
        if not os.path.isdir(loc):
            continue
        for dirpath, _d, files in os.walk(loc):
            for fn in files:
                if not fn.lower().endswith("_l_english.yml"):
                    continue
                for line in _read_loc_lines(os.path.join(dirpath, fn)):
                    m = _MODIFIER_LOC.match(line)
                    if not m:
                        continue
                    key = m.group(1).lower()
                    if key.endswith("_prefix"):
                        continue  # £icon prefixes, not real modifiers
                    value = _clean_loc(m.group(3))
                    if not value:
                        continue
                    (descs if m.group(2) else names)[key] = value

    out: dict = {}
    for key in set(names) | set(descs):
        name = names.get(key)
        desc = descs.get(key)
        if name and desc and desc != name:
            out[key] = f"{name} — {desc}"
        else:
            out[key] = desc or name
    return out


def build_modifier_names(roots) -> set:
    """Union of base-game doc names + MD idea keys; falls back to the curated
    COMMON_IDEA_MODIFIERS when no game files yield anything."""
    names = build_base_modifier_names(roots) | build_md_idea_modifier_keys(roots)
    return names or set(COMMON_IDEA_MODIFIERS)


def build_modifier_groups(roots) -> list:
    """[(group_label, [modifier_name])] consumed by the provider/editor.

    A ``Common`` group of the 20 most-used modifiers leads (ordered by usage,
    a quick-pick shortcut); the functional-theme groups in GROUP_ORDER follow,
    each sorted case-insensitively. Common modifiers still also appear in their
    theme group, so nothing is hidden."""
    buckets: dict = {}
    for name in build_modifier_names(roots):
        buckets.setdefault(classify_modifier(name), []).append(name)
    out = []
    common = build_common_modifiers(roots)
    if common:
        out.append(("Common", common))
    for label in GROUP_ORDER:
        if label in buckets:
            out.append((label, sorted(buckets[label], key=str.lower)))
    return out
