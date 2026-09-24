"""Bring a project's script up to Millennium Dawn 2.0 names.

MD 2.0 renamed a handful of tokens that raw script copied from 1.x trees (or
written against 1.x) still uses. Each rename here is one-to-one and verified
against MD 2.0's own files — the new name takes the same inputs / means the same
thing — so it is safe to apply mechanically:

* the relative party-popularity helper (``add_…`` → ``change_…``);
* the infantry / utility-vehicle equipment archetypes;
* two country tags (Norway, Greenland).

What 2.0 *removed* (the radicalization system, dropped tags, helpers MD deleted)
has no replacement and is left for the user — validation points at each one.

Pure: no Qt. ``migrate_project`` mutates the project in place; the UI wraps it
in ``ProjectModel.batch()`` so it is one undo step.
"""
from __future__ import annotations

import re
from collections import Counter

from .availability_presets import get_availability_preset
from .md_edition import (
    LEGACY_EQUIPMENT_RENAMES,
    LEGACY_MAIN,
    LEGACY_TAG_RENAMES,
    active_edition,
)
from .reward_presets import get_reward_preset


def md2_renames(edition=None) -> dict:
    """``{old_token: new_token}`` for the target edition (default: active)."""
    e = edition or active_edition()
    out = {}
    if LEGACY_MAIN.party_popularity_effect != e.party_popularity_effect:
        out[LEGACY_MAIN.party_popularity_effect] = e.party_popularity_effect
    out.update(LEGACY_EQUIPMENT_RENAMES)
    out.update(LEGACY_TAG_RENAMES)
    return out


def own_legacy_tags(project) -> set:
    """1.x tags that are the project's OWN identity (its country tag, or its
    localisation prefix = event namespace). Renaming those inside script would
    break the project's own event ids (NOR.3) and leave the tree's country
    block on the old tag, so the migration skips them; the user changes the
    project's tag instead (validation says so)."""
    from .base_tree import normalize_country_tag
    own = {normalize_country_tag(getattr(project, "countryTag", "") or "")}
    settings = getattr(project, "exportSettings", None)
    own.add((getattr(settings, "localisationPrefix", "") or "").strip().upper())
    return {t for t in LEGACY_TAG_RENAMES if t in own}


def _project_renames(project, edition) -> dict:
    renames = md2_renames(edition)
    for t in own_legacy_tags(project):
        renames.pop(t, None)
    return renames


def _pattern(renames: dict):
    if not renames:
        return None
    # Whole tokens only: NOR must not touch NOR_flag or TNOR; `\b` still lets a
    # scope like NOR.some_var through, which is the same tag.
    alts = "|".join(re.escape(k) for k in sorted(renames, key=len, reverse=True))
    return re.compile(rf"\b({alts})\b")


# NOR.3 / NOR.3.t is an event id or its loc key, not the country.
_EVENT_ID_AFTER = re.compile(r"\.\d")


def _rename_line(line: str, pat, renames: dict, counts: Counter) -> str:
    def sub(m):
        tok = m.group(1)
        if tok in LEGACY_TAG_RENAMES and _EVENT_ID_AFTER.match(m.string, m.end()):
            return tok
        counts[tok] += 1
        return renames[tok]
    return pat.sub(sub, line)


# ----- where script lives in a project ------------------------------------------

def _rule_raw(rule):
    return getattr(rule, "rawLines", None) if rule is not None else None


def _raw_sites(project):
    """Every raw effect/trigger line list in the project (the list objects
    themselves, so callers can rewrite them in place)."""
    for f in project.focuses:
        if f.completionReward is not None:
            yield f.completionReward.rawLines
        yield _rule_raw(f.available)
        yield _rule_raw(getattr(f, "bypass", None))
        for mod in getattr(f, "aiModifiers", None) or []:
            yield _rule_raw(mod.trigger)
    for ev in project.events:
        yield _rule_raw(ev.trigger)
        for opt in ev.options or []:
            yield opt.effectRawLines
            yield _rule_raw(opt.trigger)
    for d in getattr(project, "decisions", None) or []:
        for attr in ("visible", "available", "completeEffect", "removeEffect", "timeoutEffect"):
            yield _rule_raw(getattr(d, attr, None))
        yield d.rawLines
        yield d.modifierRawLines          # targeted_modifier = { tag = NOR … }
    for idea in getattr(project, "ideas", None) or []:
        yield idea.modifierRawLines
    for c in getattr(project, "decisionCategories", None) or []:
        yield _rule_raw(c.visible)
        yield c.rawLines
    for s in getattr(project, "shortcuts", None) or []:
        yield s.triggerRawLines


def _item_sites(project):
    """``(items, preset_lookup)`` for every list of structured cards."""
    reward, cond = get_reward_preset, get_availability_preset

    def rule_items(rule):
        return (getattr(rule, "items", None) or []) if rule is not None else []

    for f in project.focuses:
        if f.completionReward is not None:
            yield f.completionReward.items or [], reward
        yield rule_items(f.available), cond
        yield rule_items(getattr(f, "bypass", None)), cond
        for mod in getattr(f, "aiModifiers", None) or []:
            yield rule_items(mod.trigger), cond
    for ev in project.events:
        yield rule_items(ev.trigger), cond
        for opt in ev.options or []:
            yield opt.items or [], reward
            yield rule_items(opt.trigger), cond
    for d in getattr(project, "decisions", None) or []:
        yield rule_items(d.visible), cond
        yield rule_items(d.available), cond
        for attr in ("completeEffect", "removeEffect", "timeoutEffect"):
            yield rule_items(getattr(d, attr, None)), reward
    for c in getattr(project, "decisionCategories", None) or []:
        yield rule_items(c.visible), cond


# Structured params whose value is a single renameable token.
_PARAM_TYPES = {"equipment": LEGACY_EQUIPMENT_RENAMES, "country_tag": LEGACY_TAG_RENAMES}


def migrate_project(project, edition=None, dry_run: bool = False) -> Counter:
    """Rename every MD 1.x token (see module doc) in the project's raw script
    and structured card params. Returns ``Counter({old_token: occurrences})``;
    empty = nothing to do. ``dry_run`` counts without changing anything.
    The project's own tag is never renamed (see ``own_legacy_tags``)."""
    renames = _project_renames(project, edition)
    pat = _pattern(renames)
    counts: Counter = Counter()
    if pat is None:
        return counts
    for lines in _raw_sites(project):
        if not lines:
            continue
        new = [_rename_line(ln, pat, renames, counts) if isinstance(ln, str) else ln
               for ln in lines]
        if not dry_run and new != lines:
            lines[:] = new
    for items, lookup in _item_sites(project):
        for item in items:
            if isinstance(item, dict):
                kind, params = item.get("kind", ""), item.get("params")
            else:
                kind, params = getattr(item, "kind", ""), getattr(item, "params", None)
            preset = lookup(kind)
            if not preset or not isinstance(params, dict):
                continue
            for pdef in preset.params:
                table = _PARAM_TYPES.get(getattr(pdef, "type", ""))
                value = params.get(pdef.key)
                if (table and isinstance(value, str) and value.strip() in table
                        and value.strip() in renames):
                    counts[value.strip()] += 1
                    if not dry_run:
                        params[pdef.key] = table[value.strip()]
    return counts


def describe_counts(counts: Counter, edition=None) -> list:
    """Human lines like ``add_relative_party_popularity → change_… (548×)``."""
    renames = md2_renames(edition)
    return [f"{old} → {renames[old]} ({n}×)" for old, n in counts.most_common()]
