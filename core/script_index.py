"""Index what the game and Millennium Dawn actually *use* in script, so raw
script in a project can be checked before export instead of failing silently
in-game.

Three indexes, all built from the configured roots (base game + MD + submods):

* **vocabulary** — every statement key that appears anywhere in the roots'
  focus trees, events, decisions, on_actions, scripted effects and scripted
  triggers, plus the names of the scripted effects/triggers themselves. A key
  in a project's raw script that appears nowhere in that set is almost
  certainly a typo, a renamed helper, or a helper from the other MD edition.
  Vanilla files are always scanned (engine effects exist regardless of which
  folders MD replaces); scripted effect/trigger *names* honour ``replace_path``
  and vanilla-only names are dropped.
* **states** — ``{id: {"name", "owner"}}`` from ``history/states`` (honouring
  replace_path), so state ids can be checked for existence and start ownership.
* **equipment** — archetype and equipment names from ``common/units/equipment``.

Plus ``scan_raw_script``: a brace-aware walk over raw lines that reports the
effect/trigger keys, state scopes/params, tag scopes/params and equipment
types they reference — validation decides what to say about each.
"""
from __future__ import annotations

import functools
import os
import re

from .mod_paths import effective_roots_for_path

_TOKEN_RE = re.compile(r'"[^"]*"|\{|\}|<=|>=|!=|==|[=<>]|[^\s{}=<>"]+')
_COMMENT_RE = re.compile(r"#[^\n]*")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_TAG_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")
_SCOPE_RE = re.compile(
    r"^(ROOT|PREV|PREV_PREV|FROM|FROM_FROM|THIS|owner|controller|capital_scope|overlord|"
    r"faction_leader|event_target:.+|var:.+|every_.+|any_.+|all_.+|random_.+|.+_scope)$")
_TRANSPARENT = {
    None, "if", "else", "else_if", "limit", "NOT", "AND", "OR", "hidden_effect", "effect_tooltip",
    "random_list", "while_loop_effect", "for_each_loop", "for_each_scope_loop", "for_loop_effect",
    "hidden_trigger", "custom_override_tooltip", "count_triggers", "trigger",
}
STATE_VALUE_KEYS = {
    "set_state_owner", "set_state_controller", "add_state_core", "add_state_claim",
    "remove_state_core", "remove_state_claim", "transfer_state", "controls_state", "owns_state",
    "has_full_control_of_state", "state", "target_state", "add_core_of_state",
}
TAG_VALUE_KEYS = {
    "tag", "original_tag", "country_exists", "puppet", "annex_country", "has_war_with",
    "is_in_faction_with", "is_subject_of", "add_to_faction", "white_peace", "target",
    "is_puppet_of", "is_ally_with", "has_war_together_with", "set_state_owner",
    "set_state_controller", "add_core_of", "add_claim_by", "remove_core_of", "remove_claim_by",
    "give_guarantee", "diplomatic_relation", "producer", "exporter", "declare_war_on",
    "has_opinion_modifier", "influencer", "is_guaranteed_by", "has_non_aggression_pact_with",
}
EQUIPMENT_PARENTS = {"add_equipment_to_stockpile", "add_equipment_production", "has_equipment",
                     "send_equipment", "equipment_stockpile"}

# Directories whose script is scanned for the vocabulary. Vanilla is scanned in
# full; a mod's version also, but only where it exists.
_VOCAB_DIRS = ("common/national_focus", "events", "common/decisions", "common/on_actions",
               "common/scripted_effects", "common/scripted_triggers", "common/scripted_guis",
               "common/ideas", "common/dynamic_modifiers")


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def iter_keys(text: str):
    """Yield ``(key, parent_key, value)`` for every ``key = …`` statement at any
    depth; ``value`` is the scalar string, or None when the value is a block.
    ``parent_key`` is the key of the enclosing block (None at top level)."""
    text = _COMMENT_RE.sub("", text)
    stack: list = [None]
    last_word = None
    awaiting = None
    for tok in _TOKEN_RE.findall(text):
        if tok in ("=", "<", ">", "<=", ">=", "!=", "=="):
            awaiting = last_word
            last_word = None
            continue
        if tok == "{":
            if awaiting is not None:
                yield awaiting, stack[-1], None
                stack.append(awaiting)
            else:
                stack.append(stack[-1])  # anonymous block keeps the parent context
            awaiting = None
            last_word = None
            continue
        if tok == "}":
            if len(stack) > 1:
                stack.pop()
            awaiting = None
            last_word = None
            continue
        word = tok[1:-1] if tok.startswith('"') else tok
        if awaiting is not None:
            yield awaiting, stack[-1], word
            awaiting = None
            last_word = None
        else:
            last_word = word


def _top_level_block_names(path: str) -> set:
    return {k for k, parent, v in iter_keys(_read(path)) if parent is None and v is None}


def _scan_dir_keys(root: str, sub: str) -> set:
    out: set = set()
    base = os.path.join(root, sub.replace("/", os.sep))
    if not os.path.isdir(base):
        return out
    for dirpath, _dirs, files in os.walk(base):
        for fn in files:
            if fn.lower().endswith(".txt"):
                for k, _p, _v in iter_keys(_read(os.path.join(dirpath, fn))):
                    if k:
                        out.add(k)
    return out


@functools.lru_cache(maxsize=8)
def _vocabulary_cached(roots_key: tuple) -> frozenset:
    roots = list(roots_key)
    vocab: set = set()
    for root in roots:
        for sub in _VOCAB_DIRS:
            vocab |= _scan_dir_keys(root, sub)
    # Scripted effect/trigger NAMES: what exists after replace_path. A vanilla
    # helper that MD's replacement folder no longer defines does not exist.
    for sub in ("common/scripted_effects", "common/scripted_triggers"):
        defined_all: set = set()
        defined_eff: set = set()
        for root in roots:
            base = os.path.join(root, sub.replace("/", os.sep))
            if not os.path.isdir(base):
                continue
            names = set()
            for fn in os.listdir(base):
                if fn.lower().endswith(".txt"):
                    names |= _top_level_block_names(os.path.join(base, fn))
            defined_all |= names
            if root in effective_roots_for_path(roots, sub):
                defined_eff |= names
        vocab -= (defined_all - defined_eff)
        vocab |= defined_eff
    vocab.discard("")
    return frozenset(vocab)


def build_script_vocabulary(roots) -> frozenset:
    """Every script key the game/MD uses (see module doc). Memoised per roots."""
    return _vocabulary_cached(tuple(roots or ()))




@functools.lru_cache(maxsize=8)
def _states_cached(roots_key: tuple) -> dict:
    # Reuse the state parser the pickers already use (core.state_index); only
    # the roots after replace_path count, so a vanilla-only state MD dropped
    # is correctly "missing".
    from .state_index import build_state_index as _build
    roots = list(roots_key)
    raw = _build(effective_roots_for_path(roots, "history/states"))
    return {sid: {"name": info.get("name_key", f"STATE_{sid}"), "owner": info.get("owner", "")}
            for sid, info in raw.items()}


def build_state_index(roots) -> dict:
    """``{state_id: {"name", "owner"}}`` for every state defined after replace_path."""
    return _states_cached(tuple(roots or ()))


def states_owned_by(roots, tag: str) -> set:
    t = (tag or "").upper()
    return {sid for sid, d in build_state_index(roots).items() if d["owner"] == t}


@functools.lru_cache(maxsize=8)
def _equipment_cached(roots_key: tuple) -> frozenset:
    roots = list(roots_key)
    names: set = set()
    for root in effective_roots_for_path(roots, "common/units/equipment"):
        base = os.path.join(root, "common", "units", "equipment")
        if not os.path.isdir(base):
            continue
        for fn in os.listdir(base):
            if not fn.lower().endswith(".txt"):
                continue
            for k, parent, v in iter_keys(_read(os.path.join(base, fn))):
                if parent == "equipments" and v is None:
                    names.add(k)
    return frozenset(names)


def build_equipment_types(roots) -> frozenset:
    """Archetype and equipment names defined under ``equipments = { }``."""
    return _equipment_cached(tuple(roots or ()))


@functools.lru_cache(maxsize=8)
def _archetypes_cached(roots_key: tuple) -> tuple:
    roots = list(roots_key)
    out: set = set()
    for root in effective_roots_for_path(roots, "common/units/equipment"):
        base = os.path.join(root, "common", "units", "equipment")
        if not os.path.isdir(base):
            continue
        for fn in os.listdir(base):
            if not fn.lower().endswith(".txt"):
                continue
            current = None
            for k, parent, v in iter_keys(_read(os.path.join(base, fn))):
                if parent == "equipments" and v is None:
                    current = k
                elif k == "is_archetype" and v == "yes" and parent == current and current:
                    out.add(current)
    return tuple(sorted(out, key=str.lower))


def build_equipment_archetypes(roots) -> list:
    """Equipment ARCHETYPE names (``is_archetype = yes``) — what add_equipment_to_
    stockpile / production pickers should offer; the edition renames these (main
    ``Inf_equipment`` vs beta ``infantry_weapons_type``)."""
    return list(_archetypes_cached(tuple(roots or ())))


def clear_script_index_cache() -> None:
    _vocabulary_cached.cache_clear()
    _states_cached.cache_clear()
    _equipment_cached.cache_clear()
    _archetypes_cached.cache_clear()


# ---------------------------------------------------------------------------
# Scanning a project's raw script
# ---------------------------------------------------------------------------
def _is_transparent(parent) -> bool:
    if parent in _TRANSPARENT:
        return True
    if _NUMBER_RE.match(parent) or _TAG_RE.match(parent):
        return True
    return bool(_SCOPE_RE.match(parent))


def scan_raw_script(lines) -> dict:
    """Walk raw script lines and report what they reference:
    ``{"keys": [effect/trigger keys at statement level], "states": [ids],
    "tags": [TAGs], "equipment": [type names]}`` (each list de-duplicated, in
    order of appearance). Parameters of non-transparent blocks (``type = …``
    inside add_building_construction, variable names inside set_temp_variable)
    are deliberately NOT treated as effects."""
    text = "\n".join(str(ln) for ln in (lines or []) if ln is not None)
    keys, states, tags, equipment = [], [], [], []
    claim_only: list = []          # state ids only ever given cores/claims
    children: dict = {}            # numeric scope -> set of direct child keys

    def add(lst, v):
        if v not in lst:
            lst.append(v)

    parsed = list(iter_keys(text))
    for key, parent, value in parsed:
        if parent is not None and _NUMBER_RE.match(parent) and "." not in parent:
            children.setdefault(int(parent), set()).add(key)
    for key, parent, value in parsed:
        if not key:
            continue
        if _NUMBER_RE.match(key):
            if _is_transparent(parent) or parent == "random_list":
                if parent != "random_list" and "." not in key and not key.startswith("-"):
                    add(states, int(key))
            continue
        if key in _TRANSPARENT:            # NOT / AND / OR look like tags but aren't
            continue
        if _TAG_RE.match(key) and _is_transparent(parent):
            add(tags, key)
            continue
        if _is_transparent(parent) and not _SCOPE_RE.match(key) and not any(c in key for c in ":.@^"):
            add(keys, key)
        if value is not None:
            if key in STATE_VALUE_KEYS and _NUMBER_RE.match(value) and "." not in value:
                add(states, int(value))
            elif key in TAG_VALUE_KEYS and _TAG_RE.match(value):
                add(tags, value)
            elif key == "type" and parent in EQUIPMENT_PARENTS:
                add(equipment, value)
            if key in _CLAIM_VALUE_KEYS and _NUMBER_RE.match(value) and "." not in value:
                add(claim_only, int(value))
    for sid in states:
        kids = children.get(sid)
        if kids is not None and kids <= _CLAIM_EFFECTS:
            add(claim_only, sid)
    return {"keys": keys, "states": states, "tags": tags, "equipment": equipment,
            "claim_only": [s for s in claim_only if s in states]}


# Effects that make sense on a state the country does NOT own (so "not owned at
# start" is expected there, not a mistake).
_CLAIM_EFFECTS = {"add_core_of", "add_claim_by", "remove_core_of", "remove_claim_by",
                  "set_state_owner", "set_state_controller", "transfer_state", "add_state_core"}
_CLAIM_VALUE_KEYS = {"add_state_core", "add_state_claim", "remove_state_core", "remove_state_claim",
                     "transfer_state", "set_state_owner", "set_state_controller"}
