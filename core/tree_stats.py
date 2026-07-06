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
    # Iterative DFS (explicit stack) — recursion crashed on ~1000-deep chains
    # (AI-generated trees) with RecursionError.
    days_memo: dict = {}
    steps_memo: dict = {}

    def chain(start: str):
        if start in days_memo:
            return days_memo[start], steps_memo[start]

        def _preds(fid: str) -> list:
            f = by_id[fid]
            return [p for p in iter_prereq_ids(f.prerequisites)
                    if p in by_id and p != fid]

        on_path: set = {start}
        # frame: [fid, pred-iterator, best_days, best_steps]
        stack: list = [[start, iter(_preds(start)), 0.0, 0]]
        while stack:
            frame = stack[-1]
            fid, pred_iter = frame[0], frame[1]
            descended = False
            for p in pred_iter:
                if p in on_path:
                    continue                      # back-edge (cycle) — ignore
                if p in days_memo:
                    if days_memo[p] > frame[2]:
                        frame[2] = days_memo[p]
                    if steps_memo[p] > frame[3]:
                        frame[3] = steps_memo[p]
                    continue
                on_path.add(p)
                stack.append([p, iter(_preds(p)), 0.0, 0])
                descended = True
                break
            if not descended:
                f = by_id[fid]
                days = frame[2] + float(f.cost or 0) * DAYS_PER_COST
                steps = frame[3] + 1
                days_memo[fid] = days
                steps_memo[fid] = steps
                on_path.discard(fid)
                stack.pop()
                if stack:
                    parent = stack[-1]
                    if days > parent[2]:
                        parent[2] = days
                    if steps > parent[3]:
                        parent[3] = steps
        return days_memo[start], steps_memo[start]

    longest_days = 0.0
    max_depth = 0
    for f in focuses:
        d, s = chain(f.id)
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

        def root_of(start: str) -> set:
            # Iterative like `chain` above — same RecursionError on deep chains.
            if start in roots_memo:
                return roots_memo[start]
            on_path: set = {start}

            def _frame(fid: str) -> list:
                f = by_id[fid]
                preds = [p for p in iter_prereq_ids(f.prerequisites)
                         if p in by_id and p != fid and p not in on_path]
                out = set() if preds else ({fid} if fid in reach else set())
                return [fid, iter(preds), out]

            stack: list = [_frame(start)]
            while stack:
                frame = stack[-1]
                fid, pred_iter, out = frame[0], frame[1], frame[2]
                descended = False
                for p in pred_iter:
                    if p in roots_memo:
                        out |= roots_memo[p]
                        continue
                    on_path.add(p)
                    stack.append(_frame(p))
                    descended = True
                    break
                if not descended:
                    roots_memo[fid] = out
                    on_path.discard(fid)
                    stack.pop()
                    if stack:
                        stack[-1][2] |= out
            return roots_memo[start]

        membership: dict = {r.id: [] for r in roots}
        for f in focuses:
            for rid in root_of(f.id):
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
