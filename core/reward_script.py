"""Parse raw reward-script lines into structured reward items.

The app has two reward representations: structured items (the preset catalog)
and free-form ``rawLines`` (imports, AI-bridge edits, hand-typed script). This
module lifts recognized raw script into the SAME item kinds the presets build,
so stats, tooltips and the editor understand it — verified per statement by a
round-trip: an item is only accepted when rebuilding it through the preset
builder yields token-identical script (whitespace-insensitive; for a few block
effects whose key order the game ignores, key/value-identical).

``parse_reward_lines(lines)`` → ``(items, remainder)`` where ``items`` are
plain ``{"kind", "enabled", "params"}`` dicts in source order and ``remainder``
holds every line of the statements that didn't parse, also in source order.
"""
from __future__ import annotations

import re

from .reward_presets import build_reward_item_lines
from .types import RewardItem

# Statement-joined regexes assume single-space token separation (see _joined).
_NUM = r"(-?\d+(?:\.\d+)?)"
_ID = r"([A-Za-z0-9_.\-]+)"

# Single-statement effects: joined-text regex -> (kind, param builder)
_SIMPLE = [
    (re.compile(rf"^add_political_power = {_NUM}$"),
     "political_power", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^add_stability = {_NUM}$"),
     "stability", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^add_war_support = {_NUM}$"),
     "war_support", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^add_command_power = {_NUM}$"),
     "command_power", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^army_experience = {_NUM}$"),
     "army_experience", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^air_experience = {_NUM}$"),
     "air_experience", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^navy_experience = {_NUM}$"),
     "navy_experience", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^add_manpower = {_NUM}$"),
     "add_manpower", lambda m: {"amount": m.group(1)}),
    (re.compile(rf"^add_ideas = {_ID}$"),
     "add_idea", lambda m: {"idea": m.group(1)}),
    (re.compile(rf"^remove_ideas = {_ID}$"),
     "remove_idea", lambda m: {"idea": m.group(1)}),
    (re.compile(rf"^set_country_flag = {_ID}$"),
     "set_country_flag", lambda m: {"flag": m.group(1)}),
    (re.compile(rf"^clr_country_flag = {_ID}$"),
     "clear_country_flag", lambda m: {"flag": m.group(1)}),
    (re.compile(rf"^custom_effect_tooltip = {_ID}$"),
     "custom_tooltip", lambda m: {"tooltipId": m.group(1)}),
    (re.compile(rf"^country_event = \{{ id = {_ID} \}}$"),
     "country_event", lambda m: {"eventId": m.group(1), "days": 0}),
    (re.compile(rf"^country_event = \{{ id = {_ID} days = (\d+) \}}$"),
     "country_event", lambda m: {"eventId": m.group(1), "days": m.group(2)}),
    (re.compile(rf"^news_event = \{{ id = {_ID} \}}$"),
     "news_event", lambda m: {"eventId": m.group(1), "days": 0}),
    (re.compile(rf"^news_event = \{{ id = {_ID} days = (\d+) \}}$"),
     "news_event", lambda m: {"eventId": m.group(1), "days": m.group(2)}),
    (re.compile(rf"^add_timed_idea = \{{ idea = {_ID} days = (\d+) \}}$"),
     "timed_idea", lambda m: {"idea": m.group(1), "days": m.group(2)}),
    (re.compile(rf"^swap_ideas = \{{ remove_idea = {_ID} add_idea = {_ID} \}}$"),
     "swap_idea", lambda m: {"removeIdea": m.group(1), "addIdea": m.group(2)}),
    (re.compile(rf"^add_opinion_modifier = \{{ target = {_ID} modifier = {_ID} \}}$"),
     "opinion_modifier", lambda m: {"target": m.group(1), "modifier": m.group(2)}),
    (re.compile(rf"^reverse_add_opinion_modifier = \{{ target = {_ID} modifier = {_ID} \}}$"),
     "reverse_opinion_modifier", lambda m: {"target": m.group(1), "modifier": m.group(2)}),
    (re.compile(rf"^add_popularity = \{{ ideology = {_ID} popularity = {_NUM} \}}$"),
     "ideology_popularity", lambda m: {"ideology": m.group(1), "popularity": m.group(2)}),
]

# Block effects whose key order the game ignores — matched as key/value pairs.
# name -> (kind, {script_key: param_key}, required script keys)
_KV_BLOCKS = {
    "add_tech_bonus": ("tech_bonus",
                       {"name": "name", "bonus": "bonus", "uses": "uses",
                        "category": "category"},
                       {"bonus", "uses", "category"}),
    "add_doctrine_cost_reduction": ("doctrine_cost_reduction",
                                    {"name": "name", "category": "category",
                                     "uses": "uses",
                                     "cost_reduction": "costReduction"},
                                    {"category", "uses", "cost_reduction"}),
    "create_wargoal": ("create_wargoal",
                       {"type": "type", "target": "target"},
                       {"type", "target"}),
    "add_equipment_to_stockpile": ("equipment_stockpile",
                                   {"type": "type", "amount": "amount",
                                    "producer": "producer"},
                                   {"type", "amount"}),
}

# MD temp-variable idioms: (variable, following effect line) -> kind/param.
_VAR_IDIOMS = {
    ("treasury_change", "modify_treasury_effect = yes"): ("treasury_change", "amount"),
    ("debt_change", "modify_debt_effect = yes"): ("national_debt", "amount"),
    ("int_investment_change", "modify_international_investment_effect = yes"):
        ("international_investment", "amount"),
    ("rad_change", "modify_radicalization_effect = yes"): ("radicalization", "amount"),
    ("corp_change", "modify_corporate_tax_rate_effect = yes"): ("corporate_tax", "amount"),
    ("pop_change", "modify_population_tax_rate_effect = yes"): ("income_tax", "amount"),
    ("percent_change", "change_domestic_influence_percentage = yes"):
        ("domestic_influence", "percent"),
}

_OPINION_RX = re.compile(rf"^set_temp_variable = \{{ temp_opinion = {_NUM} \}}$")
_OPINION_EFFECT_RX = re.compile(r"^(change_[A-Za-z0-9_]+_opinion) = yes$")
_SET_TEMP_RX = re.compile(rf"^set_temp_variable = \{{ {_ID} = {_NUM} \}}$")

# Bare scripted-effect calls that repeat (N consecutive copies = one item).
_REPEATS = {
    "increase_economic_growth = yes": ("economic_growth", "times"),
    "one_random_agriculture_district = yes": ("agriculture_district", "count"),
}
_BARE = {
    "decrease_corruption = yes": ("corruption", {"direction": "decrease"}),
    "increase_corruption = yes": ("corruption", {"direction": "increase"}),
    "increase_education_budget = yes": ("national_budget",
                                        {"direction": "increase", "budget": "education_budget"}),
    "decrease_education_budget = yes": ("national_budget",
                                        {"direction": "decrease", "budget": "education_budget"}),
    "increase_policing_budget = yes": ("national_budget",
                                       {"direction": "increase", "budget": "policing_budget"}),
    "decrease_policing_budget = yes": ("national_budget",
                                       {"direction": "decrease", "budget": "policing_budget"}),
    "increase_military_spending = yes": ("national_budget",
                                         {"direction": "increase", "budget": "military_spending"}),
    "decrease_military_spending = yes": ("national_budget",
                                         {"direction": "decrease", "budget": "military_spending"}),
}


def _tokens(text: str) -> list:
    return re.sub(r"([{}])", r" \1 ", text).split()


def _joined(lines) -> str:
    return " ".join(_tokens(" ".join(lines)))


def _statements(lines) -> list:
    """Group flat raw lines into brace-balanced statements (each a list of the
    original lines). An unbalanced tail becomes one unparseable statement."""
    stmts, cur, depth = [], [], 0
    for ln in lines or []:
        s = ln.strip()
        if not s:
            continue
        cur.append(ln)
        depth += s.count("{") - s.count("}")
        if depth <= 0:
            stmts.append(cur)
            cur, depth = [], 0
    if cur:
        stmts.append(cur)
    return stmts


def _item(kind: str, params: dict) -> dict:
    return {"kind": kind, "enabled": True, "params": dict(params)}


def _verify(item: dict, source_lines) -> bool:
    """The parse contract: rebuilding the item must reproduce the source —
    token-identical for sequences, key/value-identical for _KV_BLOCKS."""
    built = build_reward_item_lines(item)
    if _joined(built) == _joined(source_lines):
        return True
    # Key-order-insensitive comparison for the kv-block effects.
    name = _tokens(" ".join(source_lines))[0] if source_lines else ""
    if name in _KV_BLOCKS:
        return _kv_pairs(built) == _kv_pairs(source_lines)
    return False


def _kv_pairs(lines):
    toks = _tokens(" ".join(lines))
    if len(toks) < 4 or toks[1] != "=" or toks[2] != "{" or toks[-1] != "}":
        return None
    body = toks[3:-1]
    pairs = set()
    i = 0
    while i + 2 < len(body) + 1:
        if i + 2 > len(body) or body[i + 1] != "=":
            return None
        pairs.add((body[i], body[i + 2]))
        i += 3
    return (toks[0], frozenset(pairs))


def _parse_kv_block(stmt) -> dict:
    toks = _tokens(" ".join(stmt))
    if len(toks) < 4 or toks[1] != "=" or toks[2] != "{" or toks[-1] != "}":
        return None
    name = toks[0]
    spec = _KV_BLOCKS.get(name)
    if spec is None:
        return None
    kind, key_map, required = spec
    body = toks[3:-1]
    if "{" in body or "}" in body:
        return None  # nested blocks are never these effects
    params, seen = {}, set()
    i = 0
    while i < len(body):
        if i + 2 >= len(body) + 1 or i + 2 > len(body) or body[i + 1] != "=":
            return None
        key, value = body[i], body[i + 2]
        if key not in key_map or key in seen:
            return None
        seen.add(key)
        params[key_map[key]] = value
        i += 3
    if not required.issubset(seen):
        return None
    return _item(kind, params)


def parse_reward_lines(lines):
    """→ ``(items, remainder_lines)``. Items appear in source order; every
    statement that fails to parse (or fails round-trip verification) lands in
    ``remainder_lines`` unchanged, also in source order."""
    stmts = _statements(lines)
    items: list = []
    remainder: list = []
    i = 0
    while i < len(stmts):
        stmt = stmts[i]
        joined = _joined(stmt)

        # --- multi-statement idioms (look ahead) ---
        matched = False

        # Foreign influence: 3 temp vars + change_influence_percentage.
        if joined.startswith("set_temp_variable = { percent_change") and i + 3 < len(stmts):
            group = stmts[i:i + 4]
            g = [_joined(s) for s in group]
            m_pct = re.match(rf"^set_temp_variable = \{{ percent_change = {_NUM} \}}$", g[0])
            m_tag = re.match(rf"^set_temp_variable = \{{ tag_index = {_ID} \}}$", g[1])
            m_tgt = re.match(rf"^set_temp_variable = \{{ influence_target = {_ID} \}}$", g[2])
            if (m_pct and m_tag and m_tgt
                    and g[3] == "change_influence_percentage = yes"):
                item = _item("foreign_influence",
                             {"percent": m_pct.group(1),
                              "influencerTag": m_tag.group(1),
                              "targetTag": m_tgt.group(1)})
                if _verify(item, [ln for s in group for ln in s]):
                    items.append(item)
                    i += 4
                    matched = True
        if matched:
            continue

        # Two-statement temp-var idioms (treasury, debt, taxes, influence, …).
        m = _SET_TEMP_RX.match(joined)
        if m and i + 1 < len(stmts):
            nxt = _joined(stmts[i + 1])
            spec = _VAR_IDIOMS.get((m.group(1), nxt))
            if spec:
                kind, param = spec
                item = _item(kind, {param: m.group(2)})
                if _verify(item, stmt + stmts[i + 1]):
                    items.append(item)
                    i += 2
                    continue

        # Interest-group opinion: temp_opinion + change_<group>_opinion.
        m = _OPINION_RX.match(joined)
        if m and i + 1 < len(stmts):
            m2 = _OPINION_EFFECT_RX.match(_joined(stmts[i + 1]))
            if m2:
                item = _item("interest_group_opinion",
                             {"amount": m.group(1), "effect": m2.group(1)})
                if _verify(item, stmt + stmts[i + 1]):
                    items.append(item)
                    i += 2
                    continue

        # Consecutive bare repeats (economic growth, agriculture districts).
        if joined in _REPEATS:
            kind, param = _REPEATS[joined]
            n = 1
            while i + n < len(stmts) and _joined(stmts[i + n]) == joined:
                n += 1
            item = _item(kind, {param: n})
            if _verify(item, [ln for s in stmts[i:i + n] for ln in s]):
                items.append(item)
                i += n
                continue

        # Bare one-liners with fixed params.
        if joined in _BARE:
            kind, params = _BARE[joined]
            item = _item(kind, params)
            if _verify(item, stmt):
                items.append(item)
                i += 1
                continue

        # Key/value block effects (order-insensitive).
        kv = _parse_kv_block(stmt)
        if kv is not None and _verify(kv, stmt):
            items.append(kv)
            i += 1
            continue

        # Single-statement regex effects.
        for rx, kind, params_of in _SIMPLE:
            m = rx.match(joined)
            if m:
                item = _item(kind, params_of(m))
                if _verify(item, stmt):
                    items.append(item)
                    matched = True
                    break
        if matched:
            i += 1
            continue

        remainder.extend(stmt)
        i += 1
    return items, remainder


def structure_completion_reward(reward) -> int:
    """All-or-nothing lift of ``reward.rawLines`` into ``reward.items``.
    Mutates the reward and returns the number of items created; returns 0 and
    changes nothing when any statement fails to parse (the raw script's exact
    order must survive)."""
    raw = list(getattr(reward, "rawLines", None) or [])
    if not raw:
        return 0
    parsed, remainder = parse_reward_lines(raw)
    if remainder or not parsed:
        return 0
    reward.items = list(reward.items or []) + [
        RewardItem(kind=it["kind"], params=dict(it["params"]), enabled=True)
        for it in parsed]
    reward.rawLines = None
    return len(parsed)


def structure_all_rewards(project):
    """Structure the raw reward script of every focus that fully parses.
    → ``(converted_focus_count, lifted_effect_count, skipped_focus_ids)``
    where skipped focuses had raw script that was only partially (or not at
    all) recognized and were left untouched."""
    converted = 0
    effects = 0
    skipped: list = []
    for f in project.focuses:
        reward = f.completionReward
        if reward is None or not (reward.rawLines or []):
            continue
        n = structure_completion_reward(reward)
        if n:
            converted += 1
            effects += n
        else:
            skipped.append(f.id)
    return converted, effects, skipped
