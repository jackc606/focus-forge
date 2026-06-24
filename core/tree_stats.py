"""Project statistics for the Stats tab — tree shape, time to complete, and
the political-power economy. Pure functions over the project; no Qt.

HOI4 time rule: focus cost 1 = 7 days (MD focuses are usually cost 10 = 70
days), so day figures here are cost × 7.
"""
from __future__ import annotations

from .types import iter_prereq_ids

DAYS_PER_COST = 7


def compute_stats(project) -> dict:
    focuses = project.focuses
    by_id = {f.id: f for f in focuses}

    roots = [f for f in focuses
             if not any(p in by_id for p in iter_prereq_ids(f.prerequisites))]

    # Longest prerequisite chain (in days and steps), memoized; cycles are
    # guarded (validation reports them separately) by ignoring back-edges.
    days_memo: dict = {}
    steps_memo: dict = {}

    def chain(fid: str, stack: frozenset):
        if fid in days_memo:
            return days_memo[fid], steps_memo[fid]
        f = by_id[fid]
        best_days = 0.0
        best_steps = 0
        for p in iter_prereq_ids(f.prerequisites):
            if p in by_id and p != fid and p not in stack:
                d, s = chain(p, stack | {fid})
                if d > best_days:
                    best_days = d
                if s > best_steps:
                    best_steps = s
        days = best_days + float(f.cost or 0) * DAYS_PER_COST
        steps = best_steps + 1
        days_memo[fid] = days
        steps_memo[fid] = steps
        return days, steps

    longest_days = 0.0
    max_depth = 0
    for f in focuses:
        d, s = chain(f.id, frozenset())
        longest_days = max(longest_days, d)
        max_depth = max(max_depth, s)

    # Political-power economy across all completion rewards.
    pp_gained = 0.0
    pp_spent = 0.0

    def add_pp(amount) -> None:
        nonlocal pp_gained, pp_spent
        try:
            v = float(amount or 0)
        except (TypeError, ValueError):
            return
        if v >= 0:
            pp_gained += v
        else:
            pp_spent += -v

    rewards_total = 0
    focuses_without_rewards = 0
    for f in focuses:
        r = f.completionReward
        has_any = False
        if r:
            if r.politicalPower:
                add_pp(r.politicalPower)
                has_any = True
            for item in (r.items or []):
                rewards_total += 1
                has_any = True
                if getattr(item, "kind", "") == "political_power" and getattr(item, "enabled", True) is not False:
                    add_pp((getattr(item, "params", {}) or {}).get("amount"))
            has_any = has_any or bool(r.stability or r.warSupport or r.commandPower
                                      or r.armyExperience or r.airExperience
                                      or r.navyExperience or r.addIdeas or r.removeIdeas
                                      or r.events or r.techBonuses or r.rawLines)
        if not has_any:
            focuses_without_rewards += 1

    mutex_pairs = set()
    for f in focuses:
        for m in f.mutuallyExclusive:
            if m in by_id:
                mutex_pairs.add(tuple(sorted((f.id, m))))

    branches = []
    if by_id:
        # Per-root branch: every focus whose chain bottoms out at that root.
        # A focus can belong to several branches; that's fine for an overview.
        # Memoized — without it, stacked multi-prerequisite diamonds make the
        # path enumeration exponential and hang the Stats refresh.
        reach: dict = {r.id: set() for r in roots}
        roots_memo: dict = {}

        def root_of(fid: str, seen: frozenset) -> set:
            if fid in roots_memo:
                return roots_memo[fid]
            f = by_id[fid]
            preds = [p for p in iter_prereq_ids(f.prerequisites) if p in by_id and p != fid and p not in seen]
            if not preds:
                out = {fid} if fid in reach else set()
            else:
                out = set()
                for p in preds:
                    out |= root_of(p, seen | {fid})
            roots_memo[fid] = out
            return out

        membership: dict = {r.id: [] for r in roots}
        for f in focuses:
            for rid in root_of(f.id, frozenset()):
                membership[rid].append(f)
        for r in roots:
            members = membership.get(r.id, [])
            branches.append({
                "root": r.id,
                "title": r.title or r.id,
                "focuses": len(members),
                "days": max((days_memo.get(f.id, 0.0) for f in members), default=0.0),
            })
        branches.sort(key=lambda b: -b["days"])

    return {
        "focuses": len(focuses),
        "roots": len(roots),
        "max_depth": max_depth,
        "total_days": sum(float(f.cost or 0) * DAYS_PER_COST for f in focuses),
        "longest_path_days": longest_days,
        "pp_gained": pp_gained,
        "pp_spent": pp_spent,
        "reward_items": rewards_total,
        "focuses_without_rewards": focuses_without_rewards,
        "mutex_pairs": len(mutex_pairs),
        "ideas": len(project.ideas),
        "events": len(project.events),
        "branches": branches,
    }
