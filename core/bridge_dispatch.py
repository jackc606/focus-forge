"""Command dispatch for the AI bridge — the single op vocabulary an agent uses.

``dispatch(model, op, args)`` maps a JSON command to a ``ProjectModel`` operation (or a
core read function) and returns a JSON-serializable result. It receives the model object,
so this module stays Qt-free and is fully testable with a headless ``ProjectModel()`` (the
same way ``tests/test_events.py`` drives the model with no QApplication).

Every op reuses the model's own mutation methods (dedupe / cycle-refusal / reference-rewrite)
and the existing serializers, so the agent edits the project with exactly the invariants the
GUI enforces.
"""
from __future__ import annotations

from pathlib import Path

from .availability_presets import AVAILABILITY_PRESETS
from .country_tags import MD_COUNTRY_TAGS
from .exporters import export_project_files
from .md_parties import MD_PARTIES
from .presets import MD_FOCUS_FILTERS, MD_ICON_PRESETS, MD_TECH_CATEGORIES
from .reward_presets import (
    BUILDING_TYPES,
    EQUIPMENT_TYPES,
    RESOURCE_TYPES,
    REWARD_PRESETS,
    WARGOAL_TYPES,
)
from .serialization import (
    _availability_from_dict,
    _completion_reward_from_dict,
    _decision_category_from_dict,
    _decision_from_dict,
    _event_from_dict,
    _idea_from_dict,
    _to_plain,
    project_to_dict,
)
from .types import FocusPosition, normalize_id_list, normalize_prereq_groups
from .validation import MIN_SAME_ROW_DX

try:
    from .version import __version__ as _APP_VERSION
except Exception:  # pragma: no cover - version module optional
    _APP_VERSION = "0.0.0"

BRIDGE_PROTOCOL = 1

# Authoring convention surfaced to every bridge client (hello + reference_data)
# so agents place focuses with correct in-game spacing without being told.
LAYOUT_CONVENTION = {
    "minSameRowDx": MIN_SAME_ROW_DX,
    "note": (f"Focuses sharing a y row need x-distance >= {MIN_SAME_ROW_DX}; "
             "dx=1 makes the focus boxes overlap in-game. Vertical steps of "
             "dy=1 are fine. The validator warns via focus.position.tooClose."),
}


# ----- shaping helpers ---------------------------------------------------------

def _focus_summary(f) -> dict:
    return {
        "id": f.id,
        "title": f.title,
        "x": f.position.x,
        "y": f.position.y,
        "icon": f.icon,
        "cost": f.cost,
        "prerequisites": list(f.prerequisites),
        "mutuallyExclusive": list(f.mutuallyExclusive),
    }


def _preset_dict(p) -> dict:
    return {
        "kind": p.kind,
        "group": p.group,
        "label": p.label,
        "description": p.description,
        "params": [
            {
                "key": pr.key, "label": pr.label, "type": pr.type,
                "required": bool(pr.required), "defaultValue": pr.defaultValue,
                "options": pr.options, "placeholder": pr.placeholder,
                "helpText": pr.helpText,
            }
            for pr in p.params
        ],
    }


def _focus_fields_from_args(args: dict) -> dict:
    """Pull the writable focus fields out of a command's args, converting nested
    JSON (position / completionReward / available) into dataclasses."""
    fields: dict = {}
    for k in ("title", "description", "icon", "cost", "filters",
              "prerequisites", "mutuallyExclusive", "notes"):
        if k in args:
            fields[k] = args[k]
    # prerequisites preserve one level of nesting (OR groups: [["a","b"]] = a OR
    # b); mutuallyExclusive is always a flat id list. Both defend against
    # malformed/over-nested input. See core.types.normalize_prereq_groups.
    if "prerequisites" in fields:
        fields["prerequisites"] = normalize_prereq_groups(fields["prerequisites"])
    if "mutuallyExclusive" in fields:
        fields["mutuallyExclusive"] = normalize_id_list(fields["mutuallyExclusive"])
    # Coerce/validate loosely-typed JSON before it reaches the model — a client
    # sending {"x": "9"} or {"cost": "5"} must not poison the project (validation
    # and export both assume real numbers). Un-coercible input raises ValueError,
    # which dispatch() turns into a normal {"ok": False, "error": …} response.
    for key in ("title", "description", "icon", "notes"):
        if key in fields and fields[key] is not None and not isinstance(fields[key], str):
            raise ValueError(f"{key} must be a string (got {fields[key]!r}).")
    if "filters" in fields and fields["filters"] is not None:
        flt = fields["filters"]
        if (isinstance(flt, str) or not isinstance(flt, (list, tuple))
                or not all(isinstance(f, str) for f in flt)):
            raise ValueError(f"filters must be a list of strings (got {flt!r}).")
        fields["filters"] = list(flt)
    if "cost" in fields and fields["cost"] is not None:
        try:
            fields["cost"] = float(fields["cost"])
        except (TypeError, ValueError):
            raise ValueError(f"cost must be a number (got {fields['cost']!r}).")
    if args.get("position") is not None:
        p = args["position"]
        if not isinstance(p, dict):
            raise ValueError(f'position must be an object like {{"x": 3, "y": 5}} (got {p!r}).')
        try:
            fields["position"] = FocusPosition(x=int(p.get("x", 0)), y=int(p.get("y", 0)))
        except (TypeError, ValueError):
            raise ValueError(
                f"position x/y must be integers (got x={p.get('x')!r}, y={p.get('y')!r}).")
    if "completionReward" in args:
        fields["completionReward"] = _completion_reward_from_dict(args["completionReward"] or {})
    if "available" in args:
        fields["available"] = (_availability_from_dict(args["available"])
                               if args["available"] else None)
    return fields


def _require(args: dict, *keys: str) -> None:
    missing = [k for k in keys if args.get(k) in (None, "")]
    if missing:
        raise ValueError(f"Missing required arg(s): {', '.join(missing)}.")


# ----- read ops ----------------------------------------------------------------

def _op_hello(model, args):
    p = model.project
    return {
        "app": "Focus Forge",
        "version": _APP_VERSION,
        "protocol": BRIDGE_PROTOCOL,
        "project": {"name": p.projectName, "tag": p.countryTag,
                    "treeId": p.treeId, "focuses": len(p.focuses),
                    "ideas": len(p.ideas), "events": len(p.events)},
        "layout": LAYOUT_CONVENTION,
    }


def _op_get_project(model, args):
    return project_to_dict(model.project)


def _op_list_focuses(model, args):
    return [_focus_summary(f) for f in model.project.focuses]


def _op_get_focus(model, args):
    _require(args, "id")
    focus = model.find_focus(args["id"])
    if not focus:
        raise ValueError(f"No focus '{args['id']}'.")
    return _to_plain(focus)


def _op_get_selection(model, args):
    return {"id": model.selected_id}


def _op_validate(model, args):
    issues = model.issues()
    out = {"errors": [], "warnings": []}
    for i in issues:
        rec = {"code": i.code, "message": i.message, "focusId": i.focusId}
        (out["errors"] if i.severity == "error" else out["warnings"]).append(rec)
    out["summary"] = {"errors": len(out["errors"]), "warnings": len(out["warnings"])}
    return out


def _op_list_reward_presets(model, args):
    return [_preset_dict(p) for p in REWARD_PRESETS]


def _op_list_condition_presets(model, args):
    return [_preset_dict(p) for p in AVAILABILITY_PRESETS]


def _op_reference_data(model, args):
    return {
        "countryTags": [{"tag": t.tag, "name": t.name} for t in MD_COUNTRY_TAGS],
        "parties": [{"index": idx, "name": name} for idx, name in MD_PARTIES],
        "focusFilters": list(MD_FOCUS_FILTERS),
        "iconPresets": list(MD_ICON_PRESETS),
        "techCategories": list(MD_TECH_CATEGORIES),
        "resourceTypes": list(RESOURCE_TYPES),
        "equipmentTypes": list(EQUIPMENT_TYPES),
        "wargoalTypes": list(WARGOAL_TYPES),
        "buildingTypes": list(BUILDING_TYPES),
        "layoutConvention": LAYOUT_CONVENTION,
        # MD focus-cost convention (measured from real submods) — don't use a uniform cost.
        "costConvention": {
            "default": 10, "leaf": 5, "trivial": 1,
            "note": "10 = standard spine/branch-head/capstone (~70 days); 5 = granular "
                    "leaf/follow-up; 1-3 = trivial. Vary cost by a focus's role.",
        },
    }


# ----- focus write ops ---------------------------------------------------------

def _op_add_focus(model, args):
    x, y = args.get("x"), args.get("y")
    below = args.get("place_below")
    if below:
        if x is not None or y is not None:
            raise ValueError("place_below and explicit x/y are mutually exclusive.")
        # Placement only — the parent is NOT linked as a prerequisite (pass
        # prerequisites=[parent] explicitly to also link).
        x, y = model.free_cell_below(str(below))
    if x is not None and y is not None:
        fid = model.add_focus_at(int(x), int(y), prerequisites=normalize_prereq_groups(args.get("prerequisites")))
    else:
        fid = model.add_focus()
        if args.get("prerequisites"):
            model.update_focus(fid, prerequisites=normalize_prereq_groups(args["prerequisites"]))
    fields = _focus_fields_from_args({k: v for k, v in args.items()
                                      if k not in ("x", "y", "id", "prerequisites", "place_below")})
    if fields:
        model.update_focus(fid, **fields)
    if args.get("id"):
        fid = model.rename_focus(fid, str(args["id"]))
    return {"id": fid}


def _op_update_focus(model, args):
    _require(args, "id")
    target = args["id"]
    if not model.find_focus(target):
        raise ValueError(f"No focus '{target}'.")
    fields = _focus_fields_from_args(args)
    if fields:
        model.update_focus(target, **fields)
    return _focus_summary(model.find_focus(target))


def _op_rename_focus(model, args):
    _require(args, "id", "new_id")
    if not model.find_focus(args["id"]):
        raise ValueError(f"No focus '{args['id']}'.")
    return {"id": model.rename_focus(args["id"], str(args["new_id"]))}


def _op_delete_focus(model, args):
    _require(args, "id")
    model.delete_focus(args["id"])
    return {"deleted": args["id"]}


def _op_delete_focuses(model, args):
    _require(args, "ids")
    ids = list(args["ids"])
    model.delete_focuses(ids)
    return {"deleted": ids}


def _op_link_prerequisite(model, args):
    _require(args, "target", "prereq")
    msg = model.add_prerequisite(args["target"], args["prereq"])
    return {"message": msg}


def _op_unlink_prerequisite(model, args):
    _require(args, "target", "prereq")
    return {"message": model.remove_prerequisite(args["target"], args["prereq"])}


def _op_set_mutually_exclusive(model, args):
    _require(args, "a", "b")
    return {"message": model.set_mutually_exclusive(args["a"], args["b"])}


def _op_remove_mutex(model, args):
    _require(args, "a", "b")
    return {"message": model.remove_mutex(args["a"], args["b"])}


def _op_select_focus(model, args):
    _require(args, "id")
    model.set_selection(args["id"])
    return {"selected": args["id"]}


# ----- project / export settings ----------------------------------------------

_META_KEYS = {"projectName", "countryTag", "treeId", "mode"}
_EXPORT_KEYS = {"modPrefix", "focusFileName", "localisationPrefix",
                "includeIdeas", "includeEvents", "includeCountry"}


def _op_set_metadata(model, args):
    fields = {k: v for k, v in args.items() if k in _META_KEYS}
    if not fields:
        raise ValueError(f"No known metadata fields. Allowed: {sorted(_META_KEYS)}.")
    model.update_project_meta(**fields)
    return {"updated": sorted(fields)}


def _op_set_export_settings(model, args):
    fields = {k: v for k, v in args.items() if k in _EXPORT_KEYS}
    if not fields:
        raise ValueError(f"No known export fields. Allowed: {sorted(_EXPORT_KEYS)}.")
    model.update_export_settings(**fields)
    return {"updated": sorted(fields)}


# ----- ideas / events ----------------------------------------------------------

def _op_add_idea(model, args):
    _require(args, "idea")
    return {"id": model.add_idea(_idea_from_dict(args["idea"]))}


def _op_update_idea(model, args):
    _require(args, "id", "idea")
    return {"id": model.update_idea(args["id"], _idea_from_dict(args["idea"]))}


def _op_delete_idea(model, args):
    _require(args, "id")
    model.delete_idea(args["id"])
    return {"deleted": args["id"]}


def _op_add_event(model, args):
    _require(args, "event")
    return {"id": model.add_event(_event_from_dict(args["event"]))}


def _op_update_event(model, args):
    _require(args, "id", "event")
    return {"id": model.update_event(args["id"], _event_from_dict(args["event"]))}


def _op_delete_event(model, args):
    _require(args, "id")
    model.delete_event(args["id"])
    return {"deleted": args["id"]}


# ----- decisions -----------------------------------------------------------------

def _op_add_decision(model, args):
    _require(args, "decision")
    return {"id": model.add_decision(_decision_from_dict(args["decision"]))}


def _op_update_decision(model, args):
    _require(args, "id", "decision")
    return {"id": model.update_decision(args["id"], _decision_from_dict(args["decision"]))}


def _op_delete_decision(model, args):
    _require(args, "id")
    model.delete_decision(args["id"])
    return {"deleted": args["id"]}


def _op_add_decision_category(model, args):
    _require(args, "category")
    return {"id": model.add_decision_category(_decision_category_from_dict(args["category"]))}


def _op_update_decision_category(model, args):
    _require(args, "id", "category")
    return {"id": model.update_decision_category(
        args["id"], _decision_category_from_dict(args["category"]))}


def _op_delete_decision_category(model, args):
    _require(args, "id")
    model.delete_decision_category(args["id"])
    return {"deleted": args["id"]}


def _op_list_decisions(model, args):
    return {"decisions": [_to_plain(d) for d in model.project.decisions],
            "categories": [_to_plain(c) for c in model.project.decisionCategories]}


# ----- IO ----------------------------------------------------------------------

def _op_load_project(model, args):
    _require(args, "path")
    model.load_from_file(Path(args["path"]))
    return {"loaded": str(args["path"]), "focuses": len(model.project.focuses),
            "name": model.project.projectName}


def _op_save(model, args):
    path = args.get("path") or (str(model.path) if model.path else "")
    if not path:
        raise ValueError("No save path. The project hasn't been saved yet; pass 'path'.")
    model.save_to_file(Path(path))
    return {"saved": str(path)}


def _op_export(model, args):
    files = export_project_files(model.project)
    out = {"files": [f.relativePath for f in files]}
    if args.get("dir"):
        out["count"] = model.export_to_directory(Path(args["dir"]))
        out["written_to"] = str(args["dir"])
    return out


# ----- batch ---------------------------------------------------------------------

_BATCH_MAX_OPS = 200
# IO / undo-stack-destroying ops can't be atomic; `batch` itself can't nest.
_BATCH_DISALLOWED = {"batch", "load_project", "save", "export"}


def _op_batch(model, args):
    """Run a list of ops atomically: one undo step, one change notification.
    Any failure rolls the whole batch back (via ``model.batch()``)."""
    _require(args, "ops")
    ops = args["ops"]
    if not isinstance(ops, list) or not ops or not all(isinstance(o, dict) for o in ops):
        raise ValueError('ops must be a non-empty list of {"op": str, "args": dict} objects.')
    if len(ops) > _BATCH_MAX_OPS:
        raise ValueError(f"Too many ops ({len(ops)}); max {_BATCH_MAX_OPS} per batch.")
    # Validate the whole list BEFORE mutating anything — a bad entry at index k
    # must not leave entries 0..k-1 applied.
    plan = []
    for i, entry in enumerate(ops):
        name = entry.get("op", "")
        if name in _BATCH_DISALLOWED:
            raise ValueError(f"Op '{name}' (at index {i}) isn't allowed inside a batch.")
        handler = _OPS.get(name)
        if handler is None:
            raise ValueError(f"Unknown op '{name}' at index {i}. Known: {', '.join(OP_NAMES)}.")
        plan.append((name, handler, entry.get("args") or {}))
    results = []
    with model.batch():
        for i, (name, handler, op_args) in enumerate(plan):
            try:
                results.append(handler(model, op_args))
            except Exception as exc:
                raise ValueError(f"Batch failed at op {i} ({name}): {exc}. "
                                 "Nothing was applied.") from exc
    return {"results": results, "count": len(results)}


# ----- registry ----------------------------------------------------------------

_OPS = {
    "hello": _op_hello,
    "get_project": _op_get_project,
    "list_focuses": _op_list_focuses,
    "get_focus": _op_get_focus,
    "get_selection": _op_get_selection,
    "validate": _op_validate,
    "list_reward_presets": _op_list_reward_presets,
    "list_condition_presets": _op_list_condition_presets,
    "reference_data": _op_reference_data,
    "add_focus": _op_add_focus,
    "update_focus": _op_update_focus,
    "rename_focus": _op_rename_focus,
    "delete_focus": _op_delete_focus,
    "delete_focuses": _op_delete_focuses,
    "link_prerequisite": _op_link_prerequisite,
    "unlink_prerequisite": _op_unlink_prerequisite,
    "set_mutually_exclusive": _op_set_mutually_exclusive,
    "remove_mutex": _op_remove_mutex,
    "select_focus": _op_select_focus,
    "set_metadata": _op_set_metadata,
    "set_export_settings": _op_set_export_settings,
    "add_idea": _op_add_idea,
    "update_idea": _op_update_idea,
    "delete_idea": _op_delete_idea,
    "add_event": _op_add_event,
    "update_event": _op_update_event,
    "delete_event": _op_delete_event,
    "add_decision": _op_add_decision,
    "update_decision": _op_update_decision,
    "delete_decision": _op_delete_decision,
    "add_decision_category": _op_add_decision_category,
    "update_decision_category": _op_update_decision_category,
    "delete_decision_category": _op_delete_decision_category,
    "list_decisions": _op_list_decisions,
    "load_project": _op_load_project,
    "save": _op_save,
    "export": _op_export,
    "batch": _op_batch,
}

OP_NAMES = sorted(_OPS)


def dispatch(model, op: str, args: "dict | None" = None) -> dict:
    """Run one bridge op against a ProjectModel. Always returns a JSON-serializable
    ``{"ok": True, "result": …}`` or ``{"ok": False, "error": …}`` (never raises)."""
    args = args or {}
    handler = _OPS.get(op)
    if handler is None:
        return {"ok": False, "error": f"Unknown op '{op}'. Known: {', '.join(OP_NAMES)}."}
    try:
        return {"ok": True, "result": handler(model, args)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
