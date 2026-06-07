"""Project validation — ported from validation.ts."""
from __future__ import annotations

import re
from typing import Iterable

from .ideologies import TOP_IDEOLOGIES, all_sub_ideologies
from .reward_presets import validate_reward_item
from .types import FocusForgeProject, ValidationIssue

ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")   # focus_tree id, loc namespace
_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")       # safe export filename
_TAG_PATTERN = re.compile(r"^[A-Z0-9]{3}$")                 # HOI4 country tag


def validate_project(project: FocusForgeProject) -> list:
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
        pos_key = f"{focus.position.x},{focus.position.y}"
        existing = seen_positions.get(pos_key)
        if existing:
            issues.append(ValidationIssue(severity="error", code="focus.position.overlap", focusId=focus.id, message=f"{focus.id} overlaps {existing} at {pos_key}."))
        else:
            seen_positions[pos_key] = focus.id

    for focus in project.focuses:
        for prereq in focus.prerequisites:
            if prereq not in focus_ids:
                issues.append(ValidationIssue(severity="error", code="focus.prerequisite.missing", focusId=focus.id, message=f"{focus.id} references missing prerequisite {prereq}."))
            if prereq == focus.id:
                issues.append(ValidationIssue(severity="error", code="focus.prerequisite.self", focusId=focus.id, message=f"{focus.id} cannot require itself."))
        for exclusive in focus.mutuallyExclusive:
            if exclusive not in focus_ids:
                issues.append(ValidationIssue(severity="error", code="focus.mutual.missing", focusId=focus.id, message=f"{focus.id} references missing mutual exclusion {exclusive}."))
        if focus.available:
            for required in (focus.available.completedFocuses or []):
                if required not in focus_ids:
                    issues.append(ValidationIssue(severity="error", code="focus.available.completed.missing", focusId=focus.id, message=f"{focus.id} availability references missing focus {required}."))
        items = (focus.completionReward.items or []) if focus.completionReward else []
        for index, item in enumerate(items):
            for message in validate_reward_item(item):
                issues.append(ValidationIssue(severity="error", code="focus.reward.invalid", focusId=focus.id, message=f"{focus.id} reward {index + 1}: {message}"))

    _detect_cycles(project, issues)
    _validate_metadata(project, issues)
    return issues


def _err(issues, code, msg):
    issues.append(ValidationIssue(severity="error", code=code, message=msg))


def _warn(issues, code, msg):
    issues.append(ValidationIssue(severity="warning", code=code, message=msg))


def _validate_metadata(project: FocusForgeProject, issues: list) -> None:
    """Project/export metadata: tree id, export filenames, loc prefix, country
    settings, and idea/event export consistency."""
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
        _validate_collection(project.events, issues, "event", "Event", check_invalid_id=False,
                             empty_code="events.empty", empty_msg="“Include events” is on but the project has no events.")


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
    for i, party in enumerate(country.parties or []):
        if (party.ideology or "") not in TOP_IDEOLOGIES:
            _warn(issues, "country.party.ideology", f"Party {i + 1} has an invalid ideology '{party.ideology}'.")
        if not (party.name or "").strip():
            _warn(issues, "country.party.name", f"Party {i + 1} ({party.ideology or '?'}) has no name.")
    subs = set(all_sub_ideologies())
    for i, leader in enumerate(country.leaders or []):
        if not (leader.name or "").strip():
            _warn(issues, "country.leader.name", f"Leader {i + 1} has no name.")
        if (leader.ideology or "") not in subs:
            _warn(issues, "country.leader.ideology", f"Leader {i + 1} ({leader.name or '?'}) has an invalid ideology '{leader.ideology}'.")


def _validate_collection(items, issues: list, code: str, label: str, *,
                         check_invalid_id: bool, empty_code: str, empty_msg: str) -> None:
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
