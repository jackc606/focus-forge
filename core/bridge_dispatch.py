"""Command dispatch for the AI bridge — the single op vocabulary an agent uses.

``dispatch(model, op, args)`` maps a JSON command to a ``ProjectModel`` operation (or a
core read function) and returns a JSON-serializable result. It receives the model object,
so this module stays Qt-free and is fully testable with a headless ``ProjectModel()`` (the
same way ``tests/test_events.py`` drives the model with no QApplication).

Every op reuses the model's own mutation methods (dedupe / cycle-refusal / reference-rewrite)
and the existing serializers, so the agent edits the project with exactly the invariants the
GUI enforces.

Fail-fast philosophy: the bridge is driven by models that may not read carefully or run
``validate`` unprompted, so anything a write op can tell is wrong *before* touching the
project (misspelt args, bad ids, occupied cells, unknown preset kinds, dangling references,
unresolved icons) is rejected with a message that says what was wrong AND what to do.
Every successful write also returns the validation issues touching the edited focuses.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from .availability_presets import AVAILABILITY_PRESETS, get_availability_preset
from .bridge_specs import GUI_ONLY_OPS, OP_SPECS, accepted_arg_names, alias_map, describe
from .bridge_specs import tool_schemas  # noqa: F401  (re-exported for the future in-app agent)
from .country_tags import MD_COUNTRY_TAGS, country_tags_for_roots
from .exporters import export_project_files
from .md_focus_guide import (
    AI_WEIGHT_AUTHORING_NOTE,
    COST_CONVENTION,
    LAYOUT_CONVENTION,
    MD_FOCUS_GUIDE,
    REWARD_AUTHORING_NOTE,
)
from .md_parties import MD_PARTIES
from .presets import FOCUS_FILTER_PATTERN, MD_FOCUS_FILTERS, MD_ICON_PRESETS, MD_TECH_CATEGORIES
from .reward_presets import (
    BUILDING_TYPES,
    EQUIPMENT_TYPES,
    RESOURCE_TYPES,
    REWARD_PRESETS,
    WARGOAL_TYPES,
    get_reward_preset,
)
from .serialization import (
    _ai_modifier_from_dict,
    _availability_from_dict,
    _completion_reward_from_dict,
    _decision_category_from_dict,
    _decision_from_dict,
    _event_from_dict,
    _idea_from_dict,
    _to_plain,
    project_to_dict,
)
from .types import FocusPosition, iter_prereq_ids, normalize_id_list, normalize_prereq_groups
from .validation import MIN_SAME_ROW_DX

try:
    from .version import __version__ as _APP_VERSION
except Exception:  # pragma: no cover - version module optional
    _APP_VERSION = "0.0.0"

BRIDGE_PROTOCOL = 1

# New / renamed focus ids must be plain HOI4 tokens. (Validation tolerates a
# dot in legacy ids; the bridge is stricter because it is *creating* them.)
_FOCUS_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DYNAMIC_TAG_RE = re.compile(r"^D\d\d$")


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
        "aiWillDo": getattr(f, "aiWillDo", None),
        "aiModifierCount": len(getattr(f, "aiModifiers", None) or []),
    }


_SUMMARY_FIELDS = ("id", "title", "x", "y", "icon", "cost", "prerequisites",
                   "mutuallyExclusive", "aiWillDo", "aiModifierCount")


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


def _param_signature(preset) -> str:
    """'amount:number*, influencerTag:country_tag' — the one-line params shape
    used by compact listings and by every params error message (* = required)."""
    return ", ".join(f"{pr.key}:{pr.type}{'*' if pr.required else ''}" for pr in preset.params) or "(none)"


def _preset_compact(p) -> dict:
    return {"kind": p.kind, "group": p.group, "label": p.label, "params": _param_signature(p)}


def _slug(text: str) -> str:
    """A legal id suggestion for a rejected one: lowercase, runs of anything
    non-alphanumeric collapsed to one underscore, edges stripped."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text).lower()).strip("_")
    if not s:
        return "focus"
    return s if _FOCUS_ID_RE.match(s) else f"f_{s}"


def _closest(word: str, candidates, n: int = 3) -> list:
    """Spelling suggestions: difflib first, then substring hits (a model often
    knows part of the name, e.g. 'popularity' for relative_party_popularity)."""
    word = str(word or "")
    out = difflib.get_close_matches(word, list(candidates), n=n, cutoff=0.5)
    low = word.lower()
    if low:
        for c in candidates:
            if len(out) >= n:
                break
            if low in c.lower() and c not in out:
                out.append(c)
    return out


# ----- arg normalisation -----------------------------------------------------------

def normalize_args(op: str, args) -> dict:
    """Aliases -> canonical names, loose shapes -> strict ones, unknown keys ->
    rejected. Runs before every handler (and for each batch entry) so a
    misspelt arg can never be silently dropped."""
    if op not in OP_SPECS:
        raise ValueError(f"Unknown op '{op}'. Known: {', '.join(sorted(OP_SPECS))}.")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError(f"args for {op} must be a JSON object (got {type(args).__name__}). "
                         f"Call describe_op('{op}') for the shape.")
    out = dict(args)
    for alias, name in alias_map(op).items():
        if alias not in out:
            continue
        val = out.pop(alias)
        if name in out and out[name] is not None and val is not None and out[name] != val:
            raise ValueError(f"Pass either '{name}' or its alias '{alias}' for {op}, not both.")
        if name not in out or out[name] is None:
            out[name] = val
    accepted = accepted_arg_names(op)
    unknown = [k for k in out if k not in accepted]
    if unknown:
        vocab = accepted + list(alias_map(op))
        hints = []
        for k in unknown:
            m = difflib.get_close_matches(str(k), vocab, n=1, cutoff=0.6)
            if m:
                hints.append(f"'{m[0]}'")
        msg = (f"Unknown arg(s) for {op}: {', '.join(repr(k) for k in unknown)}. "
               f"Accepted: {', '.join(accepted)}.")
        if hints:
            msg += f" Did you mean {', '.join(hints)}?"
        raise ValueError(msg)
    if op == "update_focus":
        _fold_xy_into_position(out)
    if isinstance(out.get("filters"), str):
        out["filters"] = [out["filters"]]
    return out


_normalize_args = normalize_args  # spec name


def _fold_xy_into_position(args: dict) -> None:
    has_x, has_y = args.get("x") is not None, args.get("y") is not None
    if not (has_x or has_y):
        return
    if not (has_x and has_y):
        raise ValueError("To move a focus pass BOTH x and y (or position={\"x\": .., \"y\": ..}).")
    x, y = args.pop("x"), args.pop("y")
    pos = args.get("position")
    if pos is not None and (pos.get("x"), pos.get("y")) != (x, y):
        raise ValueError("x/y and position disagree — pass one of them.")
    args["position"] = {"x": x, "y": y}


# ----- fail-fast checks ------------------------------------------------------------

def _check_new_id(value, what: str) -> str:
    fid = str(value)
    if not _FOCUS_ID_RE.match(fid):
        raise ValueError(f"{what} '{fid}' is not a valid focus id: use letters, digits and "
                         f"underscores only, not starting with a digit (^[A-Za-z_][A-Za-z0-9_]*$). "
                         f"Suggested: '{_slug(fid)}'.")
    return fid


def _nearest_free_cells(occupied: dict, x: int, y: int, n: int = 3) -> list:
    """Free cells near (x, y), every one of them legal (free AND dx >= 2 from
    each occupant of its row). Ranked so a sideways shift of one focus width
    costs the same as one row down, and a row up costs a little more — the
    natural order is (x+2, y), (x-2, y), (x, y+1), ..."""
    def ok(cx, cy):
        if (cx, cy) in occupied:
            return False
        return all(abs(cx - ox) >= MIN_SAME_ROW_DX for (ox, oy) in occupied if oy == cy)

    def rank(cell):
        dx, dy = cell[0] - x, cell[1] - y
        return (abs(dx) / MIN_SAME_ROW_DX + abs(dy) + (0.5 if dy < 0 else 0),
                abs(dy), dx < 0, abs(dx))

    cells = [(cx, cy) for cy in range(y - 1, y + 3) for cx in range(x - 6, x + 7) if ok(cx, cy)]
    return sorted(cells, key=rank)[:n]


def _check_cell_free(model, x: int, y: int, allow_overlap, ignore_id=None) -> None:
    if allow_overlap:
        return
    occupied = {(int(f.position.x), int(f.position.y)): f.id
                for f in model.project.focuses if f.id != ignore_id}
    who = occupied.get((x, y))
    if who is None:
        return
    free = ", ".join(f"({cx}, {cy})" for cx, cy in _nearest_free_cells(occupied, x, y))
    raise ValueError(f"Cell ({x}, {y}) is occupied by '{who}'. Nearest free cells: {free}. "
                     "Pass allow_overlap=true to place anyway.")


def _check_filters(filters) -> list:
    if filters is None:
        return []
    if isinstance(filters, str):
        filters = [filters]
    if not isinstance(filters, (list, tuple)) or not all(isinstance(f, str) for f in filters):
        raise ValueError(f"filters must be a list of FOCUS_FILTER_* strings (got {filters!r}).")
    for f in filters:
        if not FOCUS_FILTER_PATTERN.match(f):
            hint = _closest(f, MD_FOCUS_FILTERS, n=2)
            raise ValueError(
                f"Filter '{f}' is not a FOCUS_FILTER_* token (uppercase letters, digits and _)."
                + (f" Did you mean {' or '.join(hint)}?" if hint else "")
                + " See reference_data(sections=['focusFilters']).")
    return list(filters)


_BLOCK_EXAMPLES = {
    "reward": '{"items": [{"kind": "political_power", "params": {"amount": 50}}], "rawLines": ["..."]}',
    "condition": '{"items": [{"kind": "has_country_flag", "params": {"flag": "X"}}], "rawLines": ["..."]}',
}
_REGISTRIES = {
    "reward": (get_reward_preset, [p.kind for p in REWARD_PRESETS], "reward", "list_reward_presets"),
    "condition": (get_availability_preset, [p.kind for p in AVAILABILITY_PRESETS], "condition",
                  "list_condition_presets"),
}
_NUMERIC_PARAM_TYPES = ("number", "state", "party_index")


def _require_block(value, label: str, registry: str) -> None:
    """A reward/condition block must be an object — a model that passes the raw
    script as a string used to leak an AttributeError from the parser."""
    if isinstance(value, dict):
        return
    passed = ("a string" if isinstance(value, str) else "a list" if isinstance(value, list)
              else f"a {type(value).__name__}")
    raise ValueError(f"{label} must be an object: {_BLOCK_EXAMPLES[registry]}. You passed "
                     f"{passed} — put raw script lines in rawLines.")


def _check_items(items, label: str, registry: str) -> None:
    """Reject unknown preset kinds, undeclared/misspelt param keys, missing
    required params and non-numeric numbers BEFORE the item is stored — the
    old path kept 'amt' and silently defaulted 'amount'."""
    if items is None:
        return
    lookup, kinds, noun, list_op = _REGISTRIES[registry]
    if not isinstance(items, list):
        raise ValueError(f'{label}.items must be a list of {{"kind": ..., "params": {{...}}}} objects.')
    for i, item in enumerate(items, start=1):
        where = f"{label}.items[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f'{where} must be an object like {{"kind": ..., "params": {{...}}}}.')
        extra = [k for k in item if k not in ("kind", "params", "enabled")]
        if extra:
            raise ValueError(f"{where}: unknown key(s) {', '.join(repr(k) for k in extra)} — an item is "
                             f'{{"kind", "params", "enabled"?}}; put param values under "params".')
        kind = item.get("kind")
        preset = lookup(kind) if isinstance(kind, str) else None
        if preset is None:
            close = _closest(kind, kinds)
            raise ValueError(f"Unknown {noun} preset '{kind}'. Closest: "
                             f"{', '.join(close) if close else 'none'}. "
                             f"Call {list_op}(compact=true) for the full list.")
        params = item.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError(f"{where} ({kind}): params must be an object. Declared params: "
                             f"{_param_signature(preset)} (* = required).")
        declared = {p.key: p for p in preset.params}
        unknown = [k for k in params if k not in declared]
        if unknown:
            raise ValueError(f"{where} ({kind}): unknown param(s) {', '.join(repr(k) for k in unknown)}. "
                             f"Declared params: {_param_signature(preset)} (* = required).")
        enabled = item.get("enabled", True) is not False
        for p in preset.params:
            v = params.get(p.key)
            s = "" if v is None else str(v).strip()
            if p.required and s == "" and enabled:
                raise ValueError(f"{where} ({kind}): missing required param '{p.key}'. Declared "
                                 f"params: {_param_signature(preset)} (* = required).")
            if p.type in _NUMERIC_PARAM_TYPES and s != "":
                try:
                    float(v)
                except (TypeError, ValueError):
                    raise ValueError(f"{where} ({kind}): param '{p.key}' must be a number (got {v!r}).")


def _check_condition_block(value, label: str) -> None:
    if value is None:
        return
    _require_block(value, label, "condition")
    _check_items(value.get("items"), label, "condition")


def _check_event_items(event, label: str = "event") -> None:
    """Event option effects/triggers go through the same item parser as focus
    rewards, so they get the same fail-fast checks."""
    if not isinstance(event, dict):
        raise ValueError(f"{label} must be an object — call describe_op('add_event') for the shape.")
    _check_condition_block(event.get("trigger"), f"{label}.trigger")
    options = event.get("options")
    if options is None:
        return
    if not isinstance(options, list):
        raise ValueError(f"{label}.options must be a list of option objects.")
    for i, opt in enumerate(options, start=1):
        if not isinstance(opt, dict):
            raise ValueError(f"{label}.options[{i}] must be an object.")
        _check_items(opt.get("items"), f"{label}.options[{i}]", "reward")
        _check_condition_block(opt.get("trigger"), f"{label}.options[{i}].trigger")


# Icon verification. The model's own resolver (the one validate_project uses) is
# reused when present; a UI-installed search hook adds suggestions. Both are
# optional so headless tests and non-Qt callers just get "not verified".
_icon_search_provider = None


def set_icon_search_provider(fn) -> None:
    """``fn() -> [sprite names]`` (installed by the UI; may build the index)."""
    global _icon_search_provider
    _icon_search_provider = fn


def _icon_resolver(model):
    hook = getattr(model, "_icon_exists", None)
    if hook is None:
        return None
    try:
        return hook()
    except Exception:
        return None


def _check_icon(model, icon):
    """None when the icon resolves; a note string when it can't be checked;
    raises when it definitely does not resolve."""
    if not icon:
        return None
    resolver = _icon_resolver(model)
    if resolver is None:
        return "icon not verified (no icon roots configured)"
    exists = resolver(icon)
    if exists is None:
        return "icon not verified (icon index not built yet)"
    if exists:
        return None
    msg = f"Icon '{icon}' does not resolve in your icon sources. Verify with search_icons before assigning."
    if _icon_search_provider is not None:
        try:
            names = list(_icon_search_provider() or [])
        except Exception:
            names = []
        q = icon.lower().replace("gfx_focus_", "").replace("gfx_", "")
        hits = [n for n in names if q and q in n.lower()][:5]
        if hits:
            msg += f" Closest: {', '.join(hits)}."
    raise ValueError(msg)


# Dangling-reference checks. Outside a batch a missing focus is an error right
# away. Inside a batch the check is deferred to the end so a focus may reference
# one created by a later op; anything still missing then rolls the batch back.
_batch_ctx = None   # {"index": int, "op": str, "deferred": [(index, op, subject, [ids])]}


def _check_refs_exist(model, ids, subject: str, what: str) -> None:
    missing = [i for i in ids if not model.find_focus(i)]
    if not missing:
        return
    if _batch_ctx is not None:
        _batch_ctx["deferred"].append((_batch_ctx["index"], _batch_ctx["op"], subject, list(missing)))
        return
    raise ValueError(f"{what} references missing focus '{missing[0]}'. Create it first "
                     f"(or check the id with list_focuses prefix=...).")


def _check_pair_exist(model, *ids) -> None:
    """Link ops mutate BOTH focuses, so both must exist now — even in a batch
    (the model has nothing to link a not-yet-created focus to)."""
    for fid in ids:
        if not model.find_focus(fid):
            hint = (" Inside a batch, add focuses before linking them."
                    if _batch_ctx is not None else "")
            raise ValueError(f"No focus '{fid}'.{hint}")


def _focus_fields_from_args(args: dict) -> dict:
    """Pull the writable focus fields out of a command's args, converting nested
    JSON (position / completionReward / available) into dataclasses. Everything
    is checked before anything is returned, so a caller can validate first and
    mutate second."""
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
        fields["filters"] = _check_filters(fields["filters"])
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
        block = args["completionReward"]
        if block is not None:
            _require_block(block, "completionReward", "reward")
            _check_items(block.get("items"), "completionReward", "reward")
        fields["completionReward"] = _completion_reward_from_dict(block or {})
    if "available" in args:
        _check_condition_block(args["available"], "available")
        fields["available"] = (_availability_from_dict(args["available"])
                               if args["available"] else None)
    if "aiWillDo" in args:
        v = args["aiWillDo"]
        if v is None:
            fields["aiWillDo"] = None
        else:
            try:
                fields["aiWillDo"] = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"aiWillDo must be a number or null (got {v!r}).")
    if "aiModifiers" in args:
        mods = args["aiModifiers"]
        if mods is None or mods == []:
            fields["aiModifiers"] = None
        else:
            if not isinstance(mods, list) or not all(isinstance(m, dict) for m in mods):
                raise ValueError('aiModifiers must be a list of {"factor"|"add": number, '
                                 '"trigger": {"items": [...], "rawLines": [...]}} objects.')
            for i, m in enumerate(mods):
                _check_condition_block(m.get("trigger"), f"aiModifiers[{i}].trigger")
            parsed = [_ai_modifier_from_dict(m) for m in mods]
            for i, (m, p) in enumerate(zip(mods, parsed)):
                for key in ("factor", "add"):
                    if m.get(key) is not None and getattr(p, key) is None:
                        raise ValueError(f"aiModifiers[{i}].{key} must be a number (got {m[key]!r}).")
            fields["aiModifiers"] = parsed
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
        "ops": sorted(OP_SPECS),
        "start_here": "Call guide, then describe_op for any op before first use.",
    }


def _op_guide(model, args):
    return {"text": MD_FOCUS_GUIDE}


def _op_describe_op(model, args):
    return describe(args.get("op"))


def _op_get_project(model, args):
    return project_to_dict(model.project)


def _int_arg(args: dict, key: str):
    v = args.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer (got {v!r}).")


def _op_list_focuses(model, args):
    """Bare list with no args (backward compatible); a filtered envelope
    {focuses, total, returned} as soon as any filter/limit is given."""
    focuses = list(model.project.focuses)
    if not any(args.get(k) is not None for k in OP_SPECS["list_focuses"].args):
        return [_focus_summary(f) for f in focuses]
    prefix = args.get("prefix")
    if prefix is not None:
        focuses = [f for f in focuses if f.id.startswith(str(prefix))]
    if args.get("ids") is not None:
        wanted = set(normalize_id_list(args["ids"]))
        focuses = [f for f in focuses if f.id in wanted]
    bounds = {k: _int_arg(args, k) for k in ("x_min", "x_max", "y_min", "y_max")}
    focuses = [f for f in focuses
               if (bounds["x_min"] is None or f.position.x >= bounds["x_min"])
               and (bounds["x_max"] is None or f.position.x <= bounds["x_max"])
               and (bounds["y_min"] is None or f.position.y >= bounds["y_min"])
               and (bounds["y_max"] is None or f.position.y <= bounds["y_max"])]
    total = len(focuses)
    limit = _int_arg(args, "limit")
    if limit is not None:
        focuses = focuses[:max(0, limit)]
    fields = args.get("fields")
    if fields is not None:
        if isinstance(fields, str):
            fields = [fields]
        bad = [f for f in fields if f not in _SUMMARY_FIELDS]
        if bad:
            raise ValueError(f"Unknown field(s) {', '.join(repr(b) for b in bad)}. "
                             f"Available: {', '.join(_SUMMARY_FIELDS)}.")
        keep = ["id"] + [f for f in _SUMMARY_FIELDS if f in fields and f != "id"]
        rows = [{k: v for k, v in _focus_summary(f).items() if k in keep} for f in focuses]
    else:
        rows = [_focus_summary(f) for f in focuses]
    return {"focuses": rows, "total": total, "returned": len(rows)}


def _op_get_focus(model, args):
    _require(args, "id")
    focus = model.find_focus(args["id"])
    if not focus:
        raise ValueError(f"No focus '{args['id']}'.")
    return _to_plain(focus)


def _op_get_selection(model, args):
    return {"id": model.selected_id}


def _collision_issues(model) -> list:
    """Existing-tree collision errors against the configured roots (empty when
    the UI hasn't installed a roots provider)."""
    from .export_check import collision_issues_for
    roots = _reference_roots()
    if not roots:
        return []
    try:
        return collision_issues_for(model.project, roots)
    except Exception:
        return []


def _op_validate(model, args):
    issues = list(model.issues())
    # The model's own validation includes the collision check once its
    # background index has landed; until then (or headless) add it here so an
    # agent never exports a tree that loads twice in-game.
    seen = {(i.code, i.message) for i in issues}
    issues += [i for i in _collision_issues(model) if (i.code, i.message) not in seen]
    out = {"errors": [], "warnings": []}
    for i in issues:
        rec = {"code": i.code, "message": i.message, "focusId": i.focusId}
        (out["errors"] if i.severity == "error" else out["warnings"]).append(rec)
    out["summary"] = {"errors": len(out["errors"]), "warnings": len(out["warnings"])}
    return out


def _list_presets(presets, args, noun: str):
    kind = args.get("kind")
    if kind:
        match = next((p for p in presets if p.kind == kind), None)
        if match is None:
            close = _closest(kind, [p.kind for p in presets])
            raise ValueError(f"Unknown {noun} preset '{kind}'. Closest: "
                             f"{', '.join(close) if close else 'none'}.")
        return _preset_dict(match)
    if args.get("compact"):
        return [_preset_compact(p) for p in presets]
    return [_preset_dict(p) for p in presets]


def _op_list_reward_presets(model, args):
    return _list_presets(REWARD_PRESETS, args, "reward")


def _op_list_condition_presets(model, args):
    return _list_presets(AVAILABILITY_PRESETS, args, "condition")


# Callable returning the configured game-data roots, or None. This module is
# Qt-free and the model carries no roots, so the UI injects one
# (``ui.country_tags_live.install_country_tag_hooks``); headless/bridge tests
# leave it unset and get the static list.
_roots_provider = None


def set_roots_provider(fn) -> None:
    global _roots_provider
    _roots_provider = fn


def _reference_country_tags() -> list:
    roots = None
    if _roots_provider is not None:
        try:
            roots = list(_roots_provider() or ())
        except Exception:
            roots = None
    return country_tags_for_roots(roots) if roots else MD_COUNTRY_TAGS


def _reference_roots():
    if _roots_provider is None:
        return None
    try:
        roots = list(_roots_provider() or ())
    except Exception:
        return None
    return roots or None


def _reference_equipment_types() -> list:
    """Equipment archetypes of the configured MD edition (they differ between
    main and beta); the static list only when no roots are configured."""
    roots = _reference_roots()
    if roots:
        from .script_index import build_equipment_archetypes
        live = build_equipment_archetypes(roots)
        if live:
            return live
    return list(EQUIPMENT_TYPES)


def _reference_country_states(model) -> list:
    """States the project's country owns at game start: ``[{id, name}]`` — the
    ids state-scoped rewards (buildings, resources) should target."""
    roots = _reference_roots()
    tag = (model.project.countryTag or "").upper() if model is not None else ""
    if not roots or not tag:
        return []
    from .script_index import build_state_index
    return [{"id": sid, "name": d["name"]}
            for sid, d in sorted(build_state_index(roots).items()) if d["owner"] == tag]


def _op_reference_data(model, args):
    """Each section is a thunk so an agent asking for two small sections never
    pays for the 500-tag country list or a state-index build."""
    include_dynamic = bool(args.get("include_dynamic_tags"))

    def country_tags():
        tags = _reference_country_tags()
        if not include_dynamic:
            tags = [t for t in tags if not _DYNAMIC_TAG_RE.match(t.tag)]
        return [{"tag": t.tag, "name": t.name} for t in tags]

    sections = {
        "countryTags": country_tags,
        "parties": lambda: [{"index": idx, "name": name} for idx, name in MD_PARTIES],
        "focusFilters": lambda: list(MD_FOCUS_FILTERS),
        "iconPresets": lambda: list(MD_ICON_PRESETS),
        "techCategories": lambda: list(MD_TECH_CATEGORIES),
        "resourceTypes": lambda: list(RESOURCE_TYPES),
        "equipmentTypes": _reference_equipment_types,
        "countryStates": lambda: _reference_country_states(model),
        "wargoalTypes": lambda: list(WARGOAL_TYPES),
        "buildingTypes": lambda: list(BUILDING_TYPES),
        "layoutConvention": lambda: LAYOUT_CONVENTION,
        # How to author rewards/conditions/AI weights/costs — the SAME strings
        # the guide is built from (core.md_focus_guide), so they cannot drift.
        "rewardAuthoring": lambda: {"note": REWARD_AUTHORING_NOTE},
        "aiWeightAuthoring": lambda: {"note": AI_WEIGHT_AUTHORING_NOTE},
        "costConvention": lambda: dict(COST_CONVENTION),
    }
    wanted = args.get("sections")
    if wanted is None:
        wanted = list(sections)
    elif isinstance(wanted, str):
        wanted = [wanted]
    wanted = resolve_reference_sections(wanted, list(sections))
    out = {name: sections[name]() for name in sections if name in wanted}
    out["sections_available"] = list(sections)
    return out


# What a model actually types when it wants a section. The canonical names are
# camelCase compounds a weak model half-remembers ("filters", "conventions",
# "tags"); failing the whole call over that costs a round trip for nothing.
_SECTION_ALIASES = {
    "filters": ["focusFilters"], "focus_filters": ["focusFilters"],
    "search_filters": ["focusFilters"], "focusfilter": ["focusFilters"],
    "tags": ["countryTags"], "countries": ["countryTags"], "country_tags": ["countryTags"],
    "icons": ["iconPresets"], "icon_presets": ["iconPresets"],
    "tech": ["techCategories"], "technologies": ["techCategories"],
    "resources": ["resourceTypes"], "equipment": ["equipmentTypes"],
    "states": ["countryStates"], "wargoals": ["wargoalTypes"],
    "buildings": ["buildingTypes"], "layout": ["layoutConvention"],
    "spacing": ["layoutConvention"], "rewards": ["rewardAuthoring"],
    "ai": ["aiWeightAuthoring"], "ai_weights": ["aiWeightAuthoring"],
    "cost": ["costConvention"], "costs": ["costConvention"],
    "conventions": ["layoutConvention", "rewardAuthoring", "aiWeightAuthoring",
                    "costConvention"],
    "guide": ["layoutConvention", "rewardAuthoring", "aiWeightAuthoring",
              "costConvention"],
    "notes": ["layoutConvention", "rewardAuthoring", "aiWeightAuthoring",
              "costConvention"],
}


def resolve_reference_sections(wanted, available: list) -> list:
    """Map loose section names onto the canonical ones: exact, case-insensitive,
    alias table, then a close-match guess; only a name that resolves to nothing
    is an error (and the error names the closest candidate)."""
    lower = {a.lower(): a for a in available}
    out, unknown = [], []
    for raw in wanted:
        key = str(raw).strip()
        norm = key.lower().replace("-", "_").replace(" ", "_")
        if key in available:
            hits = [key]
        elif norm in lower:
            hits = [lower[norm]]
        elif norm in _SECTION_ALIASES:
            hits = _SECTION_ALIASES[norm]
        elif norm.rstrip("s") in _SECTION_ALIASES:
            hits = _SECTION_ALIASES[norm.rstrip("s")]
        else:
            close = difflib.get_close_matches(norm.replace("_", ""), list(lower), n=1, cutoff=0.6)
            hits = [lower[close[0]]] if close else []
        if not hits:
            unknown.append(key)
        out.extend(h for h in hits if h not in out)
    if unknown:
        raise ValueError(f"Unknown section(s) {', '.join(repr(u) for u in unknown)}. "
                         f"Available: {', '.join(available)}.")
    return out


# ----- focus write ops ---------------------------------------------------------

def _op_add_focus(model, args):
    """Everything is checked before the first mutation: a rejected add must not
    leave a half-built placeholder focus behind."""
    x, y = args.get("x"), args.get("y")
    below = args.get("place_below")
    if below:
        if x is not None or y is not None:
            raise ValueError("place_below and explicit x/y are mutually exclusive.")
        # Placement only — the parent is NOT linked as a prerequisite (pass
        # prerequisites=[parent] explicitly to also link).
        x, y = model.free_cell_below(str(below))
    elif (x is None) != (y is None):
        raise ValueError("Pass BOTH x and y to place a focus (or place_below, or neither).")
    if x is not None:
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            raise ValueError(f"x/y must be integers (got x={x!r}, y={y!r}).")
        _check_cell_free(model, x, y, args.get("allow_overlap"))
    wanted_id = _check_new_id(args["id"], "id") if args.get("id") else None
    fields = _focus_fields_from_args({k: v for k, v in args.items()
                                      if k not in ("x", "y", "id", "place_below", "allow_overlap")})
    subject = wanted_id or "(new focus)"
    _check_refs_exist(model, iter_prereq_ids(fields.get("prerequisites")), subject,
                      f"add_focus '{subject}' prerequisites")
    _check_refs_exist(model, fields.get("mutuallyExclusive") or [], subject,
                      f"add_focus '{subject}' mutuallyExclusive")
    note = _check_icon(model, fields.get("icon"))

    prereqs = fields.pop("prerequisites", None)
    if x is not None:
        fid = model.add_focus_at(x, y, prerequisites=prereqs)
    else:
        fid = model.add_focus()
        if prereqs:
            model.update_focus(fid, prerequisites=prereqs)
    if fields:
        model.update_focus(fid, **fields)
    if wanted_id:
        fid = model.rename_focus(fid, wanted_id)
    out = {"id": fid}
    if note:
        out["note"] = note
    return out


def _op_update_focus(model, args):
    _require(args, "id")
    target = args["id"]
    if not model.find_focus(target):
        raise ValueError(f"No focus '{target}'.")
    fields = _focus_fields_from_args(args)
    if "position" in fields:
        _check_cell_free(model, fields["position"].x, fields["position"].y,
                         args.get("allow_overlap"), ignore_id=target)
    _check_refs_exist(model, iter_prereq_ids(fields.get("prerequisites")), target,
                      f"update_focus '{target}' prerequisites")
    _check_refs_exist(model, fields.get("mutuallyExclusive") or [], target,
                      f"update_focus '{target}' mutuallyExclusive")
    note = _check_icon(model, fields.get("icon"))
    if fields:
        model.update_focus(target, **fields)
    out = _focus_summary(model.find_focus(target))
    if note:
        out["note"] = note
    return out


def _op_rename_focus(model, args):
    _require(args, "id", "new_id")
    if not model.find_focus(args["id"]):
        raise ValueError(f"No focus '{args['id']}'.")
    new_id = _check_new_id(args["new_id"], "new_id")
    return {"id": model.rename_focus(args["id"], new_id)}


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
    _check_pair_exist(model, args["target"], args["prereq"])
    msg = model.add_prerequisite(args["target"], args["prereq"])
    return {"message": msg}


def _op_unlink_prerequisite(model, args):
    _require(args, "target", "prereq")
    _check_pair_exist(model, args["target"], args["prereq"])
    return {"message": model.remove_prerequisite(args["target"], args["prereq"])}


def _op_set_mutually_exclusive(model, args):
    _require(args, "a", "b")
    _check_pair_exist(model, args["a"], args["b"])
    return {"message": model.set_mutually_exclusive(args["a"], args["b"])}


def _op_remove_mutex(model, args):
    _require(args, "a", "b")
    _check_pair_exist(model, args["a"], args["b"])
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
    _check_event_items(args["event"])
    return {"id": model.add_event(_event_from_dict(args["event"]))}


def _op_update_event(model, args):
    _require(args, "id", "event")
    _check_event_items(args["event"])
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


def _op_list_ideas(model, args):
    """Compact: enough to reference an idea from a reward or reuse its picture,
    without the modifier bodies (get_project has those)."""
    return [{"id": i.id, "title": i.title, "picture": getattr(i, "picture", ""),
             "modifiers": len(getattr(i, "modifierRawLines", None) or [])}
            for i in model.project.ideas]


def _op_list_events(model, args):
    """Compact: id, type, title and option keys — what an agent needs to pick the
    next free event number and to reference an event from a reward."""
    out = []
    for e in model.project.events:
        out.append({"id": e.id, "eventType": getattr(e, "eventType", "country_event"),
                    "title": e.title, "options": [o.key for o in (e.options or [])],
                    "picture": getattr(e, "picture", "")})
    return out


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


def _op_smoke_check(model, args):
    """Parse every file the export WOULD write and apply the game's load-time
    structural rules (see core.export_check). Nothing is written."""
    from .export_check import smoke_check
    files = export_project_files(model.project)
    issues = smoke_check(files) + _collision_issues(model)
    out = {"files": len(files), "errors": [], "warnings": []}
    for i in issues:
        rec = {"code": i.code, "message": i.message, "focusId": i.focusId}
        (out["errors"] if i.severity == "error" else out["warnings"]).append(rec)
    out["summary"] = {"errors": len(out["errors"]), "warnings": len(out["warnings"])}
    return out


def _op_scan_error_log(model, args):
    """Lines of HOI4's error.log (after a launch) that mention this mod, each
    with the focus it maps to. Args: optional `path` (log file), `mod_dir`
    (defaults to the project's export folder), `since` ('HH:MM:SS')."""
    from .export_check import default_error_log, log_is_stale, scan_error_log
    path = args.get("path") or default_error_log()
    if not Path(path).is_file():
        return {"log": path, "exists": False, "hits": [],
                "note": "No error.log yet — launch HOI4 with the mod enabled, quit, and rerun."}
    mod_dir = args.get("mod_dir") or (model.project.exportDir or "")
    files = export_project_files(model.project)
    hits = scan_error_log(files, model.project, path, mod_dir=mod_dir, since=args.get("since") or "")
    return {
        "log": path, "exists": True,
        "stale": log_is_stale(path, mod_dir),
        "hits": [{"time": h.time, "message": h.message, "file": h.file, "line": h.line,
                  "focusId": h.focusId, "matched": h.matched} for h in hits],
    }


# ----- inline validation issues -------------------------------------------------

# Write ops whose result carries the validation issues touching the edited focuses.
_ISSUE_OPS = {"add_focus", "update_focus", "rename_focus", "link_prerequisite",
              "unlink_prerequisite", "set_mutually_exclusive", "remove_mutex"}
# Project-level graph issues name the focuses in their message, not in focusId.
_GRAPH_CODES = {"focus.graph.cycle", "focus.prerequisite.unreachable"}


def _touched_ids(op: str, args: dict, result) -> list:
    if op == "add_focus" or op == "rename_focus":
        return [result["id"]]
    if op == "update_focus":
        return [args["id"]]
    if op in ("link_prerequisite", "unlink_prerequisite"):
        return [args["target"], args["prereq"]]
    if op in ("set_mutually_exclusive", "remove_mutex"):
        return [args["a"], args["b"]]
    return []


def _mentions(message: str, fid: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_.]){re.escape(fid)}(?![A-Za-z0-9_.])", message) is not None


def _issues_for(model, ids) -> list:
    """Validation issues filtered to ``ids``: those tagged with one of them, plus
    project-level cycle/unreachable issues whose message names one. focusId is
    dropped from the entries (the caller knows which focus it edited)."""
    ids = [i for i in dict.fromkeys(ids) if i]
    issues_fn = getattr(model, "issues", None)
    if not ids or not callable(issues_fn):
        return []
    out, seen = [], set()
    for issue in issues_fn():
        hit = issue.focusId in ids or (issue.code in _GRAPH_CODES
                                       and any(_mentions(issue.message, i) for i in ids))
        key = (issue.severity, issue.code, issue.message)
        if hit and key not in seen:
            seen.add(key)
            out.append({"severity": issue.severity, "code": issue.code, "message": issue.message})
    return out


def _issue_summary(issues: list) -> dict:
    return {"errors": sum(1 for i in issues if i["severity"] == "error"),
            "warnings": sum(1 for i in issues if i["severity"] != "error")}


# ----- batch ---------------------------------------------------------------------

_BATCH_MAX_OPS = 200
# IO / undo-stack-destroying ops can't be atomic; `batch` itself can't nest.
_BATCH_DISALLOWED = {"batch", "load_project", "save", "export"}


def _op_batch(model, args):
    """Run a list of ops atomically: one undo step, one change notification.
    Any failure rolls the whole batch back (via ``model.batch()``). Dangling
    focus references are checked once at the end so ops may reference focuses
    created later in the same batch."""
    global _batch_ctx
    _require(args, "ops")
    ops = args["ops"]
    if not isinstance(ops, list) or not ops or not all(isinstance(o, dict) for o in ops):
        raise ValueError('ops must be a non-empty list of {"op": str, "args": dict} objects.')
    if len(ops) > _BATCH_MAX_OPS:
        raise ValueError(f"Too many ops ({len(ops)}); max {_BATCH_MAX_OPS} per batch.")
    if _batch_ctx is not None:
        raise ValueError("Op 'batch' isn't allowed inside a batch.")
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
        try:
            op_args = normalize_args(name, entry.get("args") or {})
        except ValueError as exc:
            raise ValueError(f"Batch rejected at op {i} ({name}): {exc} Nothing was applied.")
        plan.append((name, handler, op_args))
    results, touched = [], []
    _batch_ctx = {"index": 0, "op": "", "deferred": []}
    try:
        with model.batch():
            for i, (name, handler, op_args) in enumerate(plan):
                _batch_ctx["index"], _batch_ctx["op"] = i, name
                try:
                    result = handler(model, op_args)
                except Exception as exc:
                    raise ValueError(f"Batch failed at op {i} ({name}): {exc}. "
                                     "Nothing was applied.") from exc
                results.append(result)
                touched.extend(_touched_ids(name, op_args, result))
            for index, name, subject, missing in _batch_ctx["deferred"]:
                still = [m for m in missing if not model.find_focus(m)]
                if still:
                    raise ValueError(f"Batch failed: op {index} ({name} '{subject}') references "
                                     f"missing focus '{still[0]}'. Nothing was applied.")
    finally:
        _batch_ctx = None
    issues = _issues_for(model, touched)
    return {"results": results, "count": len(results),
            "issues": issues, "summary": _issue_summary(issues)}


# ----- registry ----------------------------------------------------------------

_OPS = {
    "hello": _op_hello,
    "guide": _op_guide,
    "describe_op": _op_describe_op,
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
    "list_ideas": _op_list_ideas,
    "list_events": _op_list_events,
    "load_project": _op_load_project,
    "save": _op_save,
    "export": _op_export,
    "smoke_check": _op_smoke_check,
    "scan_error_log": _op_scan_error_log,
    "batch": _op_batch,
}

OP_NAMES = sorted(_OPS)

# Sanity: the spec registry and the handler table must agree (GUI-only ops have
# specs but no core handler). Fails at import so a forgotten spec is loud.
_missing_specs = set(_OPS) - set(OP_SPECS)
_missing_handlers = set(OP_SPECS) - set(_OPS) - set(GUI_ONLY_OPS)
if _missing_specs or _missing_handlers:  # pragma: no cover
    raise RuntimeError(f"OP_SPECS out of sync: no spec for {sorted(_missing_specs)}, "
                       f"no handler for {sorted(_missing_handlers)}")


def _error_text(op: str, exc: BaseException) -> str:
    """Never leak a Python class name to the agent — it reads as noise and
    tempts a weak model into 'fixing' the wrong thing."""
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        text = str(exc)
        if isinstance(exc, KeyError):
            text = f"Missing key {text}."
        return text
    return (f"Internal error in {op}: {exc}. Call describe_op('{op}') for the "
            "expected arg shapes.")


def dispatch(model, op: str, args: "dict | None" = None) -> dict:
    """Run one bridge op against a ProjectModel. Always returns a JSON-serializable
    ``{"ok": True, "result": …}`` or ``{"ok": False, "error": …}`` (never raises)."""
    args = args or {}
    handler = _OPS.get(op)
    if handler is None:
        return {"ok": False, "error": f"Unknown op '{op}'. Known: {', '.join(OP_NAMES)}."}
    try:
        norm = normalize_args(op, args)
        result = handler(model, norm)
        if op in _ISSUE_OPS and isinstance(result, dict):
            result["issues"] = _issues_for(model, _touched_ids(op, norm, result))
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": _error_text(op, exc)}
