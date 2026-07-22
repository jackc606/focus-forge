"""Parse raw availability/bypass trigger lines into structured condition items.

The availability twin of ``core/reward_script.py``: recognized raw trigger
script is lifted into the SAME item kinds the condition presets build, each
acceptance gated by a round-trip — rebuilding the item through the preset
builder must yield token-identical script. Unrecognized statements stay raw,
in order.
"""
from __future__ import annotations

import re

from .availability_presets import MD_RULING_PARTIES, build_availability_item_lines
from .reward_script import _joined, _statements
from .types import RewardItem

_ID = r"([A-Za-z0-9_.\-]+)"
_NUM = r"(-?\d+(?:\.\d+)?)"

# joined-statement regex -> (kind, params builder)
_MATCHERS = [
    (re.compile(rf"^has_completed_focus = {_ID}$"),
     "has_completed_focus", lambda m: {"focus": m.group(1)}),
    (re.compile(rf"^NOT = \{{ has_completed_focus = {_ID} \}}$"),
     "not_completed_focus", lambda m: {"focus": m.group(1)}),
    (re.compile(rf"^has_country_flag = {_ID}$"),
     "has_country_flag", lambda m: {"flag": m.group(1)}),
    (re.compile(rf"^NOT = \{{ has_country_flag = {_ID} \}}$"),
     "lacks_country_flag", lambda m: {"flag": m.group(1)}),
    (re.compile(rf"^has_government = {_ID}$"),
     "government", lambda m: {"ideology": m.group(1)}),
    (re.compile(rf"^has_idea = {_ID}$"),
     "has_idea", lambda m: {"idea": m.group(1)}),
    (re.compile(r"^has_elections = (yes|no)$"),
     "elections", lambda m: {"value": m.group(1)}),
    (re.compile(rf"^is_in_faction_with = {_ID}$"),
     "in_faction_with", lambda m: {"tag": m.group(1)}),
    (re.compile(rf"^is_subject_of = {_ID}$"),
     "is_subject_of", lambda m: {"tag": m.group(1)}),
    (re.compile(rf"^NOT = \{{ is_subject_of = {_ID} \}}$"),
     "not_subject_of", lambda m: {"tag": m.group(1)}),
    (re.compile(rf"^country_exists = {_ID}$"),
     "country_exists", lambda m: {"tag": m.group(1)}),
    (re.compile(rf"^has_opinion = \{{ target = {_ID} value > {_NUM} \}}$"),
     "has_opinion", lambda m: {"tag": m.group(1), "value": m.group(2)}),
    (re.compile(r"^has_war = yes$"), "at_war", lambda m: {}),
    (re.compile(r"^has_war = no$"), "at_peace", lambda m: {}),
    (re.compile(rf"^has_war_with = {_ID}$"),
     "war_with", lambda m: {"tag": m.group(1)}),
    (re.compile(rf"^NOT = \{{ has_war_with = {_ID} \}}$"),
     "not_war_with", lambda m: {"tag": m.group(1)}),
    (re.compile(r'^has_country_leader = \{ name = "([^"]+)" ruling_only = yes \}$'),
     "country_leader_name", lambda m: {"name": m.group(1)}),
    (re.compile(rf"^date > {_ID}$"), "date_after", lambda m: {"date": m.group(1)}),
    (re.compile(rf"^date < {_ID}$"), "date_before", lambda m: {"date": m.group(1)}),
    (re.compile(rf"^check_variable = \{{ gdp_total > {_NUM} \}}$"),
     "gdp_threshold", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^has_stability > {_NUM}$"),
     "stability", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^has_war_support > {_NUM}$"),
     "war_support", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^has_political_power > {_NUM}$"),
     "political_power", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^has_tech = {_ID}$"),
     "has_tech", lambda m: {"tech": m.group(1)}),
    (re.compile(rf"^(\d+) = \{{ is_owned_and_controlled_by = {_ID} \}}$"),
     "state_controlled", lambda m: {"state": m.group(1), "tag": m.group(2)}),
]

_RULING_PARTY_RX = re.compile(rf"^{_ID} = yes$")


def _item(kind: str, params: dict) -> dict:
    return {"kind": kind, "enabled": True, "params": dict(params)}


def _verify(item: dict, source_lines) -> bool:
    return _joined(build_availability_item_lines(item)) == _joined(source_lines)


def parse_condition_lines(lines):
    """→ ``(items, remainder_lines)`` — same contract as
    ``reward_script.parse_reward_lines``."""
    items: list = []
    remainder: list = []
    for stmt in _statements(lines):
        joined = _joined(stmt)
        matched = None
        for rx, kind, params_of in _MATCHERS:
            m = rx.match(joined)
            if m:
                candidate = _item(kind, params_of(m))
                if _verify(candidate, stmt):
                    matched = candidate
                break
        if matched is None:
            m = _RULING_PARTY_RX.match(joined)
            if m and m.group(1) in MD_RULING_PARTIES:
                candidate = _item("ruling_party", {"party": m.group(1)})
                if _verify(candidate, stmt):
                    matched = candidate
        if matched is not None:
            items.append(matched)
        else:
            remainder.extend(stmt)
    return items, remainder


def structure_availability_rule(rule) -> int:
    """All-or-nothing lift of ``rule.rawLines`` into ``rule.items``. Returns
    the number of items created; 0 (and no changes) when any statement fails
    to parse — raw trigger order must survive exactly."""
    raw = list(getattr(rule, "rawLines", None) or [])
    if not raw:
        return 0
    parsed, remainder = parse_condition_lines(raw)
    if remainder or not parsed:
        return 0
    rule.items = list(rule.items or []) + [
        RewardItem(kind=it["kind"], params=dict(it["params"]), enabled=True)
        for it in parsed]
    rule.rawLines = None
    return len(parsed)


def structure_all_conditions(project):
    """Structure raw availability AND bypass triggers across the project.
    → ``(converted_rule_count, lifted_condition_count, skipped_focus_ids)``."""
    converted = 0
    conditions = 0
    skipped: list = []
    for f in project.focuses:
        touched_skip = False
        for rule in (f.available, getattr(f, "bypass", None)):
            if rule is None or not (rule.rawLines or []):
                continue
            n = structure_availability_rule(rule)
            if n:
                converted += 1
                conditions += n
            else:
                touched_skip = True
        if touched_skip:
            skipped.append(f.id)
    return converted, conditions, skipped
