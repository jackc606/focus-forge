"""Project validation — ported from validation.ts."""
from __future__ import annotations

import re
from typing import Iterable

from .availability_presets import get_availability_preset, validate_availability_item
from .exporters import _FILENAME_BAD_RE, sanitize_filename_component
from .ideologies import TOP_IDEOLOGIES, all_sub_ideologies
from .md_edition import active_edition, foreign_helpers
from .md_parties import MD_PARTY_SUBIDEOLOGY_BY_INDEX
from .reward_presets import get_reward_preset, validate_reward_item
from .types import FocusForgeProject, ValidationIssue, iter_prereq_ids

ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")   # focus_tree id, loc namespace
_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")       # safe export filename
_TAG_PATTERN = re.compile(r"^[A-Z0-9]{3}$")                 # HOI4 country tag

# In-game a focus box is wider than one grid column: two focuses on the same y
# row need at least this much x separation or their boxes visually overlap.
# dy=1 vertical steps are fine. (Measured in-game against MD's renderer.)
MIN_SAME_ROW_DX = 2

_QUOTED = re.compile(r'"[^"]*"')


def lint_raw_script(lines) -> str:
    """Structural lint for raw Paradox-script lines: brace balance and quote
    balance. One stray brace corrupts the whole exported file's structure —
    the game then drops or misparses every later block, which presents as
    'my mod stopped working' far from the actual typo. Returns a short
    problem description, or '' when the script is structurally sound."""
    depth = 0
    for n, ln in enumerate(lines or [], start=1):
        if ln.count('"') % 2:
            return f'unbalanced quotes on line {n} ({ln.strip()[:40]}…)'
        s = _QUOTED.sub("", ln)          # braces inside quoted text don't nest
        s = s.split("#", 1)[0]           # nor do braces in comments
        depth += s.count("{") - s.count("}")
        if depth < 0:
            return (f"a '}}' on line {n} closes more blocks than were opened "
                    f"({ln.strip()[:40]}…)")
    if depth > 0:
        return f"{depth} unclosed '{{' block{'s' if depth != 1 else ''}"
    return ""


def validate_project(project: FocusForgeProject, icon_exists=None,
                     known_decision_categories=None,
                     known_idea_ids=None, edition=None,
                     known_country_tags=None, script_vocab=None,
                     state_index=None, equipment_types=None) -> list:
    """``icon_exists`` is an optional callable(icon_name) -> bool | None used to
    warn about icons that don't resolve in the user's configured sources (None
    = unknown, e.g. the sprite index isn't built yet — no warning emitted).
    ``known_decision_categories`` is an optional set of existing game/MD
    decision-category ids; when provided, unknown category references warn.
    ``known_idea_ids`` is an optional set of idea ids defined by the game/MD —
    tag-prefixed idea references found there are legal, not warnings."""
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

    rows: dict = {}
    for focus in project.focuses:
        if (focus.id or "").strip():
            rows.setdefault(focus.position.y, []).append(focus)
    for y, row in rows.items():
        row.sort(key=lambda f: f.position.x)
        for left, right in zip(row, row[1:]):
            dx = right.position.x - left.position.x
            if 0 < dx < MIN_SAME_ROW_DX:
                issues.append(ValidationIssue(
                    severity="warning", code="focus.position.tooClose", focusId=right.id,
                    message=f"{right.id} is only {dx} column from {left.id} on row y={y} — "
                            f"same-row focuses need dx >= {MIN_SAME_ROW_DX} or their boxes "
                            f"overlap in-game."))

    by_id = {f.id: f for f in project.focuses}
    for focus in project.focuses:
        for prereq in iter_prereq_ids(focus.prerequisites):
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
            if exclusive == focus.id:
                issues.append(ValidationIssue(severity="error", code="focus.mutual.self", focusId=focus.id, message=f"{focus.id} cannot be mutually exclusive with itself."))
            elif other is None:
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

    _validate_reward_references(project, issues, known_idea_ids)
    _lint_all_raw_script(project, issues)
    _detect_cycles(project, issues)
    _detect_unreachable(project, issues)
    _validate_shortcuts(project, focus_ids, issues)
    _validate_metadata(project, issues, known_decision_categories)
    _validate_edition(project, issues, edition, known_country_tags)
    _validate_ai_weights(project, issues)
    _validate_script_tokens(project, issues, edition, script_vocab, state_index,
                            equipment_types, known_country_tags)
    return issues


def _raw_script_sites(project: FocusForgeProject):
    """Yield ``(lines, where, focus_id)`` for every raw-script location and
    ``(items, where, focus_id)`` is handled separately — this is the raw side."""
    for focus in project.focuses:
        if focus.completionReward is not None and focus.completionReward.rawLines:
            yield focus.completionReward.rawLines, f"{focus.id} completion reward", focus.id
        for label, rule in (("availability", focus.available), ("bypass", getattr(focus, "bypass", None))):
            if rule is not None and rule.rawLines:
                yield rule.rawLines, f"{focus.id} {label}", focus.id
        for i, mod in enumerate(getattr(focus, "aiModifiers", None) or [], start=1):
            if mod.trigger is not None and mod.trigger.rawLines:
                yield mod.trigger.rawLines, f"{focus.id} AI modifier {i} trigger", focus.id
    for event in project.events:
        if event.trigger is not None and event.trigger.rawLines:
            yield event.trigger.rawLines, f"event {event.id} trigger", None
        for i, opt in enumerate(event.options or [], start=1):
            if opt.effectRawLines:
                yield opt.effectRawLines, f"event {event.id} option {i} effects", None
            if opt.trigger is not None and opt.trigger.rawLines:
                yield opt.trigger.rawLines, f"event {event.id} option {i} trigger", None
    for d in getattr(project, "decisions", None) or []:
        for attr in ("visible", "available", "completeEffect", "removeEffect", "timeoutEffect"):
            rule = getattr(d, attr, None)
            lines = getattr(rule, "rawLines", None) if rule is not None else None
            if lines:
                yield lines, f"decision {d.id} {attr}", None
    for s in getattr(project, "shortcuts", None) or []:
        if getattr(s, "triggerRawLines", None):
            yield s.triggerRawLines, f"shortcut {s.label or s.target} trigger", None


def _validate_script_tokens(project: FocusForgeProject, issues: list, edition=None,
                            script_vocab=None, state_index=None, equipment_types=None,
                            known_country_tags=None) -> None:
    """Check raw script (and the state/equipment params of structured items)
    against what the configured game/MD roots actually define:

    * effect/trigger keys not used anywhere in the game or MD → warning
      (typo, renamed helper, or the other edition's helper);
    * state ids that do not exist → error; states the project's country does
      not own at game start → warning (fine for claims/cores, wrong for
      buildings);
    * equipment types not defined by the edition → warning.

    Every index is optional (None = not built yet) so validation never blocks
    on a background scan."""
    from .script_index import scan_raw_script
    e = edition or active_edition()
    foreign = set(foreign_helpers(e))       # already reported with a better message
    tag = (project.countryTag or "").upper()
    owned = ({sid for sid, d in state_index.items() if d.get("owner") == tag}
             if state_index else None)
    known_tags = set(known_country_tags) if known_country_tags else None

    def report_state(sid, where, focus_id, claim_only=False):
        if state_index is None:
            return
        if sid not in state_index:
            (_err_focus if focus_id else _err)(issues, "script.state.missing", *(
                [focus_id] if focus_id else []),
                f"{where}: state {sid} does not exist in {e.label} — the export would be rejected.")
        elif claim_only:
            return   # cores / claims / transfers on foreign states are the point
        elif owned is not None and owned and sid not in owned:
            name = state_index[sid]["name"]
            (_warn_focus if focus_id else _warn)(issues, "script.state.notOwned", *(
                [focus_id] if focus_id else []),
                f"{where}: state {sid} ({name}) is not owned by {tag or 'this country'} at game "
                f"start — fine for claims/cores, wrong for buildings.")

    def report_equipment(name, where, focus_id):
        if equipment_types is None or not name or name in equipment_types:
            return
        (_warn_focus if focus_id else _warn)(issues, "script.equipment.unknown", *(
            [focus_id] if focus_id else []),
            f"{where}: equipment type {name} is not defined in {e.label} "
            f"(common/units/equipment) — pick one from the list.")

    for lines, where, focus_id in _raw_script_sites(project):
        found = scan_raw_script(lines)
        if script_vocab is not None:
            for key in found["keys"]:
                if key in script_vocab or key in foreign:
                    continue
                (_warn_focus if focus_id else _warn)(issues, "script.unknownToken", *(
                    [focus_id] if focus_id else []),
                    f"{where}: `{key}` is not an effect or trigger used anywhere in the game or "
                    f"{e.label} — check the spelling, or it may belong to the other MD edition.")
        for sid in found["states"]:
            report_state(sid, where, focus_id, claim_only=sid in found["claim_only"])
        if known_tags:
            for t in found["tags"]:
                if t not in known_tags:
                    (_warn_focus if focus_id else _warn)(issues, "script.tag.unknown", *(
                        [focus_id] if focus_id else []),
                        f"{where}: country tag {t} does not exist in {e.label}.")
        for eq in found["equipment"]:
            report_equipment(eq, where, focus_id)

    # Structured items: state / equipment params.
    def structured_items(focus):
        items = (focus.completionReward.items or []) if focus.completionReward else []
        for index, item in enumerate(items, start=1):
            yield item, f"{focus.id} reward {index}"

    for focus in project.focuses:
        for item, where in structured_items(focus):
            preset = get_reward_preset(item.kind)
            for p in (preset.params if preset else []):
                v = (item.params or {}).get(p.key)
                if v in (None, ""):
                    continue
                if getattr(p, "type", "") == "state":
                    try:
                        report_state(int(float(v)), where, focus.id)
                    except (TypeError, ValueError):
                        pass
                elif getattr(p, "type", "") == "equipment":
                    report_equipment(str(v), where, focus.id)


def _validate_ai_weights(project: FocusForgeProject, issues: list) -> None:
    """ai_will_do sanity: a negative base or factor makes the AI avoid the focus
    in a way modders rarely intend; a modifier with neither factor nor add does
    nothing; a modifier with no trigger applies unconditionally (probably a
    mistake — fold it into the base); condition items must be valid."""
    for focus in project.focuses:
        base = getattr(focus, "aiWillDo", None)
        if base is not None and base < 0:
            _warn_focus(issues, "focus.ai.negativeBase", focus.id,
                        f"{focus.id}: ai_will_do base {base:g} is negative — use 0 to make the AI skip it.")
        for i, mod in enumerate(getattr(focus, "aiModifiers", None) or [], start=1):
            has_weight = mod.factor is not None or mod.add is not None
            if not has_weight:
                _warn_focus(issues, "focus.ai.modifier.noWeight", focus.id,
                            f"{focus.id} AI modifier {i} has neither a factor nor an add — it does nothing.")
            if mod.factor is not None and mod.factor < 0:
                _warn_focus(issues, "focus.ai.modifier.negative", focus.id,
                            f"{focus.id} AI modifier {i}: factor {mod.factor:g} is negative.")
            trig = mod.trigger
            has_trigger = bool(trig and ((trig.completedFocuses or []) or (trig.flagsRequired or [])
                                         or (trig.flagsBlocked or []) or (trig.items or [])
                                         or (trig.rawLines or [])))
            if has_weight and not has_trigger:
                _warn_focus(issues, "focus.ai.modifier.unconditional", focus.id,
                            f"{focus.id} AI modifier {i} has no trigger, so it always applies — fold it into the base weight.")
            for index, item in enumerate(trig.items or [], start=1) if trig else []:
                for message in validate_availability_item(item):
                    _err_focus(issues, "focus.ai.modifier.invalid", focus.id,
                               f"{focus.id} AI modifier {i} condition {index}: {message}")


_TAG_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")


def _validate_edition(project: FocusForgeProject, issues: list, edition=None,
                      known_country_tags=None) -> None:
    """Things that break when a project targets a different Millennium Dawn
    edition than it was written for:

    * raw script calling a helper that only exists in the OTHER edition (the
      structured presets adapt by themselves; raw lines are exported verbatim);
    * country tags that the active edition does not define (the beta renamed
      about fifteen) — checked when the live tag list is available."""
    e = edition or active_edition()
    foreign = foreign_helpers(e)
    pat = re.compile(r"\b(" + "|".join(re.escape(h) for h in foreign) + r")\b") if foreign else None

    def scan(lines, code, where, focus_id=None):
        if not pat:
            return
        hits = sorted({m.group(1) for ln in (lines or []) for m in pat.finditer(ln)})
        for h in hits:
            issues.append(ValidationIssue(
                severity="warning", code=code, focusId=focus_id,
                message=f"{where}: raw script calls {h} — {foreign[h]}."))

    for focus in project.focuses:
        if focus.completionReward is not None:
            scan(focus.completionReward.rawLines, "focus.reward.editionHelper",
                 f"{focus.id} completion reward", focus.id)
    for event in project.events:
        for i, opt in enumerate(event.options or [], start=1):
            scan(opt.effectRawLines, "event.option.editionHelper",
                 f"event {event.id} option {i} effects")

    if known_country_tags is None:
        return
    known = set(known_country_tags)
    if not known:
        return

    def tag_params(preset):
        return [p.key for p in (preset.params if preset else []) if getattr(p, "type", "") == "country_tag"]

    def check_tag(value, code, where, focus_id=None):
        v = (value or "").strip()
        if v and _TAG_RE.match(v) and v not in known:
            issues.append(ValidationIssue(
                severity="warning", code=code, focusId=focus_id,
                message=f"{where}: country tag {v} does not exist in {e.label} "
                        f"(tags differ between MD editions — pick it again from the list)."))

    check_tag(project.countryTag, "project.countryTag.unknown", "Project country tag")
    for focus in project.focuses:
        items = (focus.completionReward.items or []) if focus.completionReward else []
        for index, item in enumerate(items, start=1):
            for key in tag_params(get_reward_preset(item.kind)):
                check_tag((item.params or {}).get(key), "focus.reward.tag.unknown",
                          f"{focus.id} reward {index}", focus.id)
        for label, rule in (("availability", focus.available), ("bypass", getattr(focus, "bypass", None))):
            for index, item in enumerate((rule.items or []) if rule else [], start=1):
                for key in tag_params(get_availability_preset(item.kind)):
                    check_tag((item.params or {}).get(key), "focus.available.tag.unknown",
                              f"{focus.id} {label} condition {index}", focus.id)
    for event in project.events:
        for i, opt in enumerate(event.options or [], start=1):
            for index, item in enumerate(opt.items or [], start=1):
                for key in tag_params(get_reward_preset(item.kind)):
                    check_tag((item.params or {}).get(key), "event.option.tag.unknown",
                              f"event {event.id} option {i} effect {index}")


def _validate_shortcuts(project: FocusForgeProject, focus_ids: set, issues: list) -> None:
    """Focus-tree branch shortcuts (bottom-left bookmarks): each must target a
    real focus, and the game only renders the first 8 slots."""
    shortcuts = getattr(project, "shortcuts", None) or []
    for i, sc in enumerate(shortcuts):
        label = (getattr(sc, "label", "") or "").strip()
        target = (getattr(sc, "target", "") or "").strip()
        who = label or target or f"#{i + 1}"
        if not target:
            _err(issues, "shortcut.target.empty",
                 f"Tree shortcut '{who}' has no target focus.")
        elif target not in focus_ids:
            _err(issues, "shortcut.target.missing",
                 f"Tree shortcut '{who}' targets missing focus '{target}'.")
        if not label:
            _warn(issues, "shortcut.label.empty",
                  f"Tree shortcut targeting '{target or '(none)'}' has no label.")
    if len(shortcuts) > 8:
        _warn(issues, "shortcut.count.exceeds",
              "HOI4 shows at most 8 shortcut slots; extras beyond the first 8 won't appear.")


def _lint_all_raw_script(project: FocusForgeProject, issues: list) -> None:
    """Run the structural raw-script lint over every place free-form script
    lives: focus rewards/availability/bypass, idea modifiers, event triggers
    and option effects. Errors, not warnings — a stray brace corrupts the
    exported file for everything after it."""

    def check(lines, code: str, where: str, focus_id: str = "") -> None:
        problem = lint_raw_script(lines)
        if problem:
            issues.append(ValidationIssue(
                severity="error", code=code, focusId=focus_id or None,
                message=f"{where}: raw script has {problem}."))

    for focus in project.focuses:
        reward = focus.completionReward
        if reward is not None:
            check(reward.rawLines, "focus.reward.script",
                  f"{focus.id} completion reward", focus.id)
        for label, rule in (("availability", focus.available),
                            ("bypass", getattr(focus, "bypass", None))):
            if rule is not None:
                check(rule.rawLines, "focus.available.script",
                      f"{focus.id} {label}", focus.id)
        for i, mod in enumerate(getattr(focus, "aiModifiers", None) or [], start=1):
            if mod.trigger is not None:
                check(mod.trigger.rawLines, "focus.ai.script",
                      f"{focus.id} AI modifier {i} trigger", focus.id)
    for idea in project.ideas:
        check(idea.modifierRawLines, "idea.modifier.script",
              f"idea {idea.id} modifiers")
    for event in project.events:
        if event.trigger is not None:
            check(event.trigger.rawLines, "event.trigger.script",
                  f"event {event.id} trigger")
        for i, opt in enumerate(event.options or [], start=1):
            check(opt.effectRawLines, "event.option.script",
                  f"event {event.id} option {i} effects")
            if opt.trigger is not None:
                check(opt.trigger.rawLines, "event.option.script",
                      f"event {event.id} option {i} trigger")


def _validate_reward_references(project: FocusForgeProject, issues: list,
                                known_idea_ids=None) -> None:
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
            # The game/MD defines plenty of tag-prefixed ideas — a reference
            # found there is legal, not a warning (a converted base tree
            # grants dozens of them).
            if known_idea_ids is not None and v in known_idea_ids:
                return
            # WARNING, not error: without a game index we can't be sure.
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
    elif _FILENAME_BAD_RE.search(project.projectName):
        safe = sanitize_filename_component(project.projectName, project.countryTag or "TAG")
        _warn(issues, "project.name.filename",
              f"Project name contains characters Windows can't use in file names "
              f"(< > : \" / \\ | ? *) — the country history file will be written "
              f"as '{tag or 'TAG'} - {safe}.txt' instead.")

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
        total = 0.0
        any_invalid = False
        for key, v in pops.items():
            try:
                total += float(v)
            except (TypeError, ValueError):
                # A raising float() here made validate_project crash on every
                # change — the project became uneditable. Report it instead.
                any_invalid = True
                _err(issues, "country.popularities.invalid",
                     f"Popularity for '{key}' is not a number ({v!r}).")
        if not any_invalid and not (98 <= total <= 102):
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
    for i, assignment in enumerate(getattr(country, "electionLeaders", None) or []):
        label = f"Election leader {i + 1}"
        try:
            party_index = int(getattr(assignment, "partyIndex", 14))
        except (TypeError, ValueError):
            party_index = -1
        if party_index not in MD_PARTY_SUBIDEOLOGY_BY_INDEX:
            _err(issues, "country.electionLeader.party",
                 f"{label} uses invalid MD party index '{getattr(assignment, 'partyIndex', '')}'.")
        start_date = (getattr(assignment, "startDate", "") or "").strip()
        m = _HOI4_DATE.match(start_date)
        if not start_date:
            _err(issues, "country.electionLeader.date.empty", f"{label} has no start date.")
        elif not m or not (1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31):
            _err(issues, "country.electionLeader.date.invalid",
                 f"{label} start date '{start_date}' isn't a HOI4 date "
                 f"(year.month.day, e.g. 2021.1.20).")
        leader = getattr(assignment, "leader", None)
        if leader is None:
            _warn(issues, "country.electionLeader.name", f"{label} has no leader.")
            continue
        if not (leader.name or "").strip():
            _warn(issues, "country.electionLeader.name", f"{label} has no leader name.")
        if (leader.ideology or "") not in subs:
            _warn(issues, "country.electionLeader.ideology",
                  f"{label} ({leader.name or '?'}) has an invalid ideology '{leader.ideology}'.")


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
    """Iterative DFS (explicit stack) — a recursive walk hit Python's recursion
    limit on ~1000-deep prerequisite chains (AI-generated trees) and crashed
    validation on project load. Output is identical to the old recursive form."""
    visiting: set = set()
    visited: set = set()
    by_id = {focus.id: focus for focus in project.focuses}

    def _prereqs(node_id: str) -> list:
        focus = by_id.get(node_id)
        return [p for p in iter_prereq_ids(focus.prerequisites if focus else [])
                if p in by_id]

    for start in project.focuses:
        if start.id in visited:
            continue
        visiting.add(start.id)
        path = [start.id]                      # mirrors the recursion path
        stack = [(start.id, iter(_prereqs(start.id)))]
        while stack:
            node_id, prereq_iter = stack[-1]
            descended = False
            for prereq in prereq_iter:
                if prereq in visiting:
                    issues.append(ValidationIssue(
                        severity="error",
                        code="focus.graph.cycle",
                        focusId=prereq,
                        message=f"Prerequisite cycle detected: {' -> '.join(path + [prereq])}.",
                    ))
                    continue
                if prereq in visited:
                    continue
                visiting.add(prereq)
                path.append(prereq)
                stack.append((prereq, iter(_prereqs(prereq))))
                descended = True
                break
            if not descended:
                stack.pop()
                path.pop()
                visiting.discard(node_id)
                visited.add(node_id)


def _detect_unreachable(project: FocusForgeProject, issues: list) -> None:
    """Flag focuses that can never be completed because their *forced* ancestors
    include both halves of a mutually-exclusive pair.

    A prerequisite is forced when it's a plain (single-focus) block — you must
    take it. Members of an OR group are choices, not forced, so they're excluded:
    that keeps this check *sound* (no false positives). It's deliberately not
    complete — it won't catch a focus whose every OR branch independently dead-
    ends — but it precisely catches the common AND-across-mutex mistake (and goes
    quiet the moment such a node is converted to an OR group)."""
    by_id = {f.id: f for f in project.focuses}
    mutex = set()
    for f in project.focuses:
        for m in (f.mutuallyExclusive or []):
            # m == f.id would collapse the frozenset to one element and crash
            # the conflict[1] lookup below; self-mutex is reported separately.
            if m in by_id and m != f.id:
                mutex.add(frozenset((f.id, m)))
    if not mutex:
        return

    def forced_ancestors(start_id: str) -> set:
        result: set = set()
        stack = [start_id]
        while stack:
            cur = stack.pop()
            focus = by_id.get(cur)
            if not focus:
                continue
            for element in (focus.prerequisites or []):
                # Only plain (non-group) prerequisites are mandatory.
                if isinstance(element, str) and element in by_id and element not in result:
                    result.add(element)
                    stack.append(element)
        return result

    for focus in project.focuses:
        required = forced_ancestors(focus.id) | {focus.id}
        conflict = next((tuple(sorted(pair)) for pair in mutex
                         if pair <= required), None)
        if conflict:
            issues.append(ValidationIssue(
                severity="error", code="focus.prerequisite.unreachable", focusId=focus.id,
                message=f"{focus.id} can never be completed: reaching it forces both "
                        f"{conflict[0]} and {conflict[1]}, which are mutually exclusive. "
                        f"Did you mean an OR group instead of separate prerequisites?"))


def get_blocking_issues(project: FocusForgeProject) -> list:
    return [issue for issue in validate_project(project) if issue.severity == "error"]
