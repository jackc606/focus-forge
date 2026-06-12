"""Project validation — ported from validation.ts."""
from __future__ import annotations

import re
from typing import Iterable

from .availability_presets import validate_availability_item
from .ideologies import TOP_IDEOLOGIES, all_sub_ideologies
from .reward_presets import get_reward_preset, validate_reward_item
from .types import FocusForgeProject, ValidationIssue

ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")   # focus_tree id, loc namespace
_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")       # safe export filename
_TAG_PATTERN = re.compile(r"^[A-Z0-9]{3}$")                 # HOI4 country tag


def validate_project(project: FocusForgeProject, icon_exists=None,
                     known_decision_categories=None) -> list:
    """``icon_exists`` is an optional callable(icon_name) -> bool | None used to
    warn about icons that don't resolve in the user's configured sources (None
    = unknown, e.g. the sprite index isn't built yet — no warning emitted).
    ``known_decision_categories`` is an optional set of existing game/MD
    decision-category ids; when provided, unknown category references warn."""
    issues: list = []
    focus_ids: set = set()
    seen_positions: dict = {}

    for focus in project.focuses:
        if not (focus.id or "").strip():
            issues.append(ValidationIssue(severity="error", code="focus.id.empty", message="Focus is missing an ID."))
            continue
        if not ID_PATTERN.match(focus.id):
            issues.append(ValidationIssue(severity="error", code="focus.id.invalid", focusId=focus.id, message=f"{focus.id} is not a valid HOI4-style ID."))
        if focus.id in focus_ids:
            issues.append(ValidationIssue(severity="error", code="focus.id.duplicate", focusId=focus.id, message=f"{focus.id} is duplicated."))
        focus_ids.add(focus.id)
        if not (focus.title or "").strip():
            issues.append(ValidationIssue(severity="warning", code="focus.title.empty", focusId=focus.id, message=f"{focus.id} has no title."))
        if not (focus.description or "").strip():
            issues.append(ValidationIssue(severity="warning", code="focus.description.empty", focusId=focus.id, message=f"{focus.id} has no description."))
        if not (focus.icon or "").strip():
            issues.append(ValidationIssue(severity="warning", code="focus.icon.empty", focusId=focus.id, message=f"{focus.id} has no icon."))
        elif (icon_exists is not None and not getattr(focus, "iconData", "")
              and icon_exists(focus.icon) is False):
            issues.append(ValidationIssue(
                severity="warning", code="focus.icon.unresolved", focusId=focus.id,
                message=f"{focus.id} icon '{focus.icon}' isn't found in your configured "
                        f"icon sources — in-game it will fall back to a placeholder."))
        pos_key = f"{focus.position.x},{focus.position.y}"
        existing = seen_positions.get(pos_key)
        if existing:
            issues.append(ValidationIssue(severity="error", code="focus.position.overlap", focusId=focus.id, message=f"{focus.id} overlaps {existing} at {pos_key}."))
        else:
            seen_positions[pos_key] = focus.id

    by_id = {f.id: f for f in project.focuses}
    for focus in project.focuses:
        for prereq in focus.prerequisites:
            if prereq not in focus_ids:
                issues.append(ValidationIssue(severity="error", code="focus.prerequisite.missing", focusId=focus.id, message=f"{focus.id} references missing prerequisite {prereq}."))
            elif prereq == focus.id:
                issues.append(ValidationIssue(severity="error", code="focus.prerequisite.self", focusId=focus.id, message=f"{focus.id} cannot require itself."))
            elif focus.position.y <= by_id[prereq].position.y:
                issues.append(ValidationIssue(
                    severity="warning", code="focus.position.above_prereq", focusId=focus.id,
                    message=f"{focus.id} is not below its prerequisite {prereq} — the in-game tree draws top-down and will render oddly."))
        for exclusive in focus.mutuallyExclusive:
            other = by_id.get(exclusive)
            if other is None:
                issues.append(ValidationIssue(severity="error", code="focus.mutual.missing", focusId=focus.id, message=f"{focus.id} references missing mutual exclusion {exclusive}."))
            elif focus.id not in (other.mutuallyExclusive or []):
                issues.append(ValidationIssue(
                    severity="warning", code="focus.mutual.onesided", focusId=focus.id,
                    message=f"{focus.id} is mutually exclusive with {exclusive}, but not the other way round."))
        for rule, label in ((focus.available, "availability"), (getattr(focus, "bypass", None), "bypass")):
            if not rule:
                continue
            for required in (rule.completedFocuses or []):
                if required not in focus_ids:
                    issues.append(ValidationIssue(severity="error", code="focus.available.completed.missing", focusId=focus.id, message=f"{focus.id} {label} references missing focus {required}."))
            for index, item in enumerate(rule.items or []):
                for message in validate_availability_item(item):
                    issues.append(ValidationIssue(severity="error", code="focus.available.invalid", focusId=focus.id, message=f"{focus.id} {label} condition {index + 1}: {message}"))
        items = (focus.completionReward.items or []) if focus.completionReward else []
        for index, item in enumerate(items):
            for message in validate_reward_item(item):
                issues.append(ValidationIssue(severity="error", code="focus.reward.invalid", focusId=focus.id, message=f"{focus.id} reward {index + 1}: {message}"))

    _validate_reward_references(project, issues)
    _detect_cycles(project, issues)
    _validate_metadata(project, issues, known_decision_categories)
    return issues


def _validate_reward_references(project: FocusForgeProject, issues: list) -> None:
    """Catch focus rewards pointing at project ideas/events that don't exist or
    won't be exported. Only ids that look project-owned (the project's event
    namespace / country-tag prefix) are flagged — references to MD's own
    content stay legal."""
    settings = project.exportSettings
    idea_ids = {i.id for i in project.ideas}
    event_ids = {e.id for e in project.events}
    loc_prefix = (settings.localisationPrefix or "").strip()
    tag = (project.countryTag or "").strip().upper()

    def check_event(focus_id: str, value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        if v in event_ids:
            if not settings.includeEvents:
                _warn_focus(issues, "focus.reward.event.unexported", focus_id,
                            f"{focus_id} fires event {v}, but “Include events” is off — it won't be exported.")
        elif loc_prefix and v.startswith(f"{loc_prefix}."):
            _err_focus(issues, "focus.reward.event.missing", focus_id,
                       f"{focus_id} fires missing project event {v}.")

    def check_idea(focus_id: str, value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        if v in idea_ids:
            if not settings.includeIdeas:
                _warn_focus(issues, "focus.reward.idea.unexported", focus_id,
                            f"{focus_id} grants idea {v}, but “Include ideas” is off — it won't be exported.")
        elif tag and v.upper().startswith(f"{tag}_"):
            # WARNING, not error: Millennium Dawn itself defines tag-prefixed
            # ideas, so this can be a perfectly valid base-mod reference.
            _warn_focus(issues, "focus.reward.idea.missing", focus_id,
                        f"{focus_id} grants idea {v}, which isn't one of this project's "
                        f"ideas — fine if it exists in MD, a problem if it was deleted here.")

    for focus in project.focuses:
        reward = focus.completionReward
        if not reward:
            continue
        for ev in (reward.events or []):
            check_event(focus.id, ev.id)
        for idea in (reward.addIdeas or []):
            check_idea(focus.id, idea)
        for idea in (reward.removeIdeas or []):
            check_idea(focus.id, idea)
        for item in (reward.items or []):
            if getattr(item, "enabled", True) is False:
                continue
            preset = get_reward_preset(getattr(item, "kind", ""))
            if not preset:
                continue
            params = getattr(item, "params", {}) or {}
            for p in preset.params:
                if p.type == "event_ref":
                    check_event(focus.id, params.get(p.key))
                elif p.type == "idea_ref":
                    check_idea(focus.id, params.get(p.key))


def _err_focus(issues, code, focus_id, msg):
    issues.append(ValidationIssue(severity="error", code=code, focusId=focus_id, message=msg))


def _warn_focus(issues, code, focus_id, msg):
    issues.append(ValidationIssue(severity="warning", code=code, focusId=focus_id, message=msg))


def _err(issues, code, msg):
    issues.append(ValidationIssue(severity="error", code=code, message=msg))


def _warn(issues, code, msg):
    issues.append(ValidationIssue(severity="warning", code=code, message=msg))


def _validate_metadata(project: FocusForgeProject, issues: list,
                       known_decision_categories=None) -> None:
    """Project/export metadata: tree id, export filenames, loc prefix, country
    settings, and idea/event/decision export consistency."""
    settings = project.exportSettings

    # ----- focus tree + country tag -----
    tree_id = (project.treeId or "").strip()
    if not tree_id:
        _err(issues, "project.treeId.empty", "Focus tree has no id (treeId).")
    elif not _TOKEN_PATTERN.match(tree_id):
        _err(issues, "project.treeId.invalid", f"Focus tree id '{tree_id}' is not a valid HOI4 id.")

    tag = (project.countryTag or "").strip()
    if not tag:
        _err(issues, "project.tag.empty", "Country tag is empty.")
    elif not _TAG_PATTERN.match(tag):
        _warn(issues, "project.tag.format", f"Country tag '{tag}' should be 3 uppercase letters/digits (e.g. USA).")

    if not (project.projectName or "").strip():
        _warn(issues, "project.name.empty", "Project has no name (used in the history file name).")

    # ----- export filenames / loc namespace -----
    focus_file = (settings.focusFileName or "").strip()
    if not focus_file:
        _err(issues, "export.focusFile.empty", "Export focus filename is empty.")
    elif not _FILENAME_PATTERN.match(focus_file):
        _warn(issues, "export.focusFile.invalid", f"Export focus filename '{focus_file}' has unusual characters.")

    loc_prefix = (settings.localisationPrefix or "").strip()
    if not loc_prefix:
        _err(issues, "export.locPrefix.empty", "Localisation prefix is empty (breaks loc file names and add_namespace).")
    elif not _TOKEN_PATTERN.match(loc_prefix):
        _err(issues, "export.locPrefix.invalid", f"Localisation prefix '{loc_prefix}' is not a valid namespace.")

    # ----- country export settings -----
    if settings.includeCountry:
        _validate_country(project.country, issues)

    # ----- ideas / events export -----
    if settings.includeIdeas:
        _validate_collection(project.ideas, issues, "idea", "Idea", check_invalid_id=True,
                             empty_code="ideas.empty", empty_msg="“Include ideas” is on but the project has no ideas.")
    if settings.includeEvents:
        # event ids must be <namespace>.<n>, where the namespace = add_namespace
        # = localisationPrefix. Only enforce it when that prefix is itself valid
        # (an empty/invalid prefix is already its own error above).
        event_ns = loc_prefix if (loc_prefix and _TOKEN_PATTERN.match(loc_prefix)) else ""
        _validate_collection(project.events, issues, "event", "Event", check_invalid_id=False,
                             empty_code="events.empty", empty_msg="“Include events” is on but the project has no events.",
                             namespace=event_ns)
        _validate_events(project.events, issues)
    if settings.includeDecisions:
        _validate_decisions(project, issues, known_decision_categories)


def _validate_decisions(project, issues: list, known_categories=None) -> None:
    if not project.decisions and not project.decisionCategories:
        _warn(issues, "decisions.empty",
              "“Include decisions” is on but the project has no decisions.")
        return
    custom_categories = set()
    seen_cat_ids = set()
    for cat in project.decisionCategories:
        cid = (cat.id or "").strip()
        if not cid:
            _err(issues, "decision.category.id.empty", "A decision category has no id.")
            continue
        if not _TOKEN_PATTERN.match(cid):
            _err(issues, "decision.category.id.invalid",
                 f"Decision category id '{cid}' is not a valid HOI4 id.")
        if cid in seen_cat_ids:
            _err(issues, "decision.category.id.duplicate",
                 f"Decision category id '{cid}' is duplicated.")
        seen_cat_ids.add(cid)
        custom_categories.add(cid)
        if not (cat.title or "").strip():
            _warn(issues, "decision.category.title.empty",
                  f"Decision category '{cid}' has no title.")

    seen_ids = set()
    for d in project.decisions:
        did = (d.id or "").strip() or "?"
        if did == "?":
            _err(issues, "decision.id.empty", "A decision has no id.")
        elif not _TOKEN_PATTERN.match(did):
            _err(issues, "decision.id.invalid", f"Decision id '{did}' is not a valid HOI4 id.")
        if did in seen_ids:
            _err(issues, "decision.id.duplicate", f"Decision id '{did}' is duplicated.")
        seen_ids.add(did)
        if not (d.title or "").strip():
            _warn(issues, "decision.title.empty", f"Decision '{did}' has no title.")
        category = (d.category or "").strip()
        if not category:
            _err(issues, "decision.category.missing",
                 f"Decision '{did}' has no category — it can't appear in the decisions panel.")
        elif not _TOKEN_PATTERN.match(category):
            _err(issues, "decision.category.invalid",
                 f"Decision '{did}' category '{category}' is not a valid HOI4 id "
                 f"(letters, digits and _ only).")
        elif (category not in custom_categories
              and known_categories is not None and category not in known_categories):
            _warn(issues, "decision.category.unknown",
                  f"Decision '{did}' category '{category}' is neither one of your "
                  f"categories nor any known game/MD category — check for a typo.")
        for key in ("daysRemove", "daysReEnable", "daysMissionTimeout"):
            val = getattr(d, key, None)
            if val is not None and float(val) < 0:
                _err(issues, "decision.days.negative",
                     f"Decision '{did}' has a negative {key}.")
        if d.daysMissionTimeout is not None and d.timeoutEffect is None:
            _warn(issues, "decision.timeout.unused",
                  f"Decision '{did}' has a mission timeout but no timeout effect.")
        for rule, label in ((d.visible, "visible"), (d.available, "available")):
            for index, item in enumerate((rule.items if rule else None) or []):
                for message in validate_availability_item(item):
                    _err(issues, "decision.trigger.invalid",
                         f"Decision '{did}' {label} condition {index + 1}: {message}")
        for reward, label in ((d.completeEffect, "complete"), (d.removeEffect, "remove"),
                              (d.timeoutEffect, "timeout")):
            for index, item in enumerate((reward.items if reward else None) or []):
                for message in validate_reward_item(item):
                    _err(issues, "decision.effect.invalid",
                         f"Decision '{did}' {label} effect {index + 1}: {message}")


_HOI4_DATE = re.compile(r"^\d{1,4}\.(\d{1,2})\.(\d{1,2})$")


def _validate_events(events, issues: list) -> None:
    for event in (events or []):
        eid = (event.id or "").strip() or "?"
        if not (event.picture or "").strip():
            _warn(issues, "event.picture.empty", f"Event '{eid}' has no picture.")
        fire_date = (getattr(event, "fireOnDate", "") or "").strip()
        if fire_date:
            m = _HOI4_DATE.match(fire_date)
            if not m or not (1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31):
                _err(issues, "event.fireOnDate.invalid",
                     f"Event '{eid}' fire date '{fire_date}' isn't a HOI4 date "
                     f"(year.month.day, e.g. 2003.3.20).")
        options = event.options or []
        # A non-hidden event needs at least one option (the button the player clicks).
        if not options and not getattr(event, "hidden", False):
            _warn(issues, "event.options.empty", f"Event '{eid}' has no options (players can't dismiss it).")
        seen_keys: set = set()
        for i, opt in enumerate(options):
            key = (opt.key or "").strip()
            if not key:
                _err(issues, "event.option.key.empty", f"Event '{eid}' option {i + 1} has no key.")
                continue
            if not _TOKEN_PATTERN.match(key):
                _err(issues, "event.option.key.invalid",
                     f"Event '{eid}' option key '{key}' has invalid characters "
                     f"(letters, digits and _ only — it becomes a localisation key).")
            if key in seen_keys:
                _err(issues, "event.option.key.duplicate",
                     f"Event '{eid}' has duplicate option key '{key}'.")
            seen_keys.add(key)


def _validate_country(country, issues: list) -> None:
    if country is None:
        _warn(issues, "country.missing", "“Include country” is on but no country data is set.")
        return
    ruling = (country.rulingParty or "").strip()
    if ruling not in TOP_IDEOLOGIES:
        _err(issues, "country.rulingParty.invalid", f"Ruling party '{ruling or '(empty)'}' is not a valid ideology.")
    pops = country.popularities or {}
    if not pops:
        _warn(issues, "country.popularities.empty", "Country has no starting popularities set.")
    else:
        total = sum(float(v) for v in pops.values())
        if not (98 <= total <= 102):
            _warn(issues, "country.popularities.sum", f"Starting popularities sum to {total:g}% (should be ~100%).")
    # MD keys each party on its SUB-ideology (a country can run several parties
    # under one top ideology), so collisions are per sub-ideology — or per top
    # ideology for parties that have no sub-ideology (vanilla set_party_name).
    seen_sub, seen_top_nosub = {}, {}
    for i, party in enumerate(country.parties or []):
        ideo = party.ideology or ""
        sub = (party.subIdeology or "").strip()
        if ideo not in TOP_IDEOLOGIES:
            _warn(issues, "country.party.ideology", f"Party {i + 1} has an invalid ideology '{party.ideology}'.")
        if not (party.name or "").strip():
            _warn(issues, "country.party.name", f"Party {i + 1} ({party.ideology or '?'}) has no name.")
        # A description (or logo) is keyed on the sub-ideology; without one it can't
        # be written and would be silently dropped on export.
        if (getattr(party, "description", "") or "").strip() and not sub:
            _warn(issues, "country.party.description.nosub",
                  f"Party {i + 1} ({party.ideology or '?'}) has a description but no "
                  f"sub-ideology, so it won't be exported. Pick a sub-ideology.")
        if sub:
            if sub in seen_sub:
                _warn(issues, "country.party.collision",
                      f"Parties {seen_sub[sub] + 1} and {i + 1} both use the '{sub}' "
                      f"sub-ideology — they overwrite each other on export. Use it once.")
            else:
                seen_sub[sub] = i
        elif ideo in TOP_IDEOLOGIES:
            if ideo in seen_top_nosub:
                _warn(issues, "country.party.collision",
                      f"Parties {seen_top_nosub[ideo] + 1} and {i + 1} are both '{ideo}' "
                      f"with no sub-ideology — they overwrite each other. Give each a "
                      f"distinct sub-ideology.")
            else:
                seen_top_nosub[ideo] = i
    subs = set(all_sub_ideologies())
    for i, leader in enumerate(country.leaders or []):
        if not (leader.name or "").strip():
            _warn(issues, "country.leader.name", f"Leader {i + 1} has no name.")
        if (leader.ideology or "") not in subs:
            _warn(issues, "country.leader.ideology", f"Leader {i + 1} ({leader.name or '?'}) has an invalid ideology '{leader.ideology}'.")


def _validate_collection(items, issues: list, code: str, label: str, *,
                         check_invalid_id: bool, empty_code: str, empty_msg: str,
                         namespace: str = "") -> None:
    if not items:
        _warn(issues, empty_code, empty_msg)
        return
    seen: set = set()
    for i, item in enumerate(items):
        iid = (item.id or "").strip()
        if not iid:
            _err(issues, f"{code}.id.empty", f"{label} {i + 1} has no id.")
            continue
        if check_invalid_id and not ID_PATTERN.match(iid):
            _err(issues, f"{code}.id.invalid", f"{label} id '{iid}' is not a valid HOI4 id.")
        if namespace and not iid.startswith(namespace + "."):
            _err(issues, f"{code}.namespace",
                 f"{label} id '{iid}' is not in the '{namespace}' namespace "
                 f"(must be {namespace}.<n> to match add_namespace).")
        if iid in seen:
            _err(issues, f"{code}.id.duplicate", f"{label} id '{iid}' is duplicated.")
        seen.add(iid)
        if not (item.title or "").strip():
            _warn(issues, f"{code}.title.empty", f"{label} '{iid}' has no title.")


def _detect_cycles(project: FocusForgeProject, issues: list) -> None:
    visiting: set = set()
    visited: set = set()
    by_id = {focus.id: focus for focus in project.focuses}

    def visit(node_id: str, path: list) -> None:
        if node_id in visiting:
            issues.append(ValidationIssue(
                severity="error",
                code="focus.graph.cycle",
                focusId=node_id,
                message=f"Prerequisite cycle detected: {' -> '.join(path + [node_id])}.",
            ))
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        focus = by_id.get(node_id)
        for prereq in (focus.prerequisites if focus else []):
            if prereq in by_id:
                visit(prereq, path + [node_id])
        visiting.discard(node_id)
        visited.add(node_id)

    for focus in project.focuses:
        visit(focus.id, [])


def get_blocking_issues(project: FocusForgeProject) -> list:
    return [issue for issue in validate_project(project) if issue.severity == "error"]
