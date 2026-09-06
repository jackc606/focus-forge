"""Machine-readable specs for every AI-bridge op — the single source of truth.

Why a registry: the bridge is meant to be driven by cheap models that don't read
prose carefully. A spec per op lets ``describe_op`` answer "what args does this
take?", lets ``dispatch`` reject misspelt / unknown args *before* anything is
applied (with aliases so ``focus_id`` / ``completion_reward`` just work), and
renders the same data as OpenAI-style function tools for a future in-app agent.

Arg ``type`` values are JSON-schema types (string / number / integer / boolean /
array / object) so the tool renderer needs no mapping table.

``screenshot`` and ``search_icons`` are GUI-only ops whose handlers live in
``ui/agent_bridge.py``; their specs live here so an agent can still discover them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

JSON_TYPES = ("string", "number", "integer", "boolean", "array", "object")


@dataclass
class OpSpec:
    description: str            # 1-2 sentences written for a model
    args: dict                  # name -> {"type", "required", "description", "aliases"}
    returns: str                # short description of the result shape
    example: dict = field(default_factory=dict)   # a complete valid args dict


def _a(type_: str, description: str, required: bool = False, aliases=()) -> dict:
    return {"type": type_, "required": required, "description": description,
            "aliases": list(aliases)}


# Shared arg fragments -------------------------------------------------------------

_ID = _a("string", "Focus id.", required=True, aliases=("focus_id",))
_PREREQS = _a("array", "Prerequisite blocks: plain ids are AND-ed; a nested list is "
              "an OR group ([[\"a\",\"b\"]] = a OR b). Replaces the focus's prerequisites. "
              "Every id must exist (inside a batch it may be created by a later op).")
_MUTEX = _a("array", "Ids this focus is mutually exclusive with (flat list of existing ids).",
            aliases=("mutually_exclusive",))
_REWARD = _a("object", 'Completion reward: {"items": [{"kind": <reward preset>, "params": {...}}], '
             '"rawLines": [...]}. Kinds/params from list_reward_presets(compact=true). '
             "Unknown kinds, unknown param keys and missing required params are rejected.",
             aliases=("completion_reward",))
_AVAILABLE = _a("object", 'Availability gate: {"items": [{"kind": <condition preset>, "params": '
                '{...}}], "rawLines": [...]}. Kinds from list_condition_presets(compact=true).')
_AI_WILL_DO = _a("number", "Base AI weight (10 = HOI4 default, 0 = never). null clears it.",
                 aliases=("ai_will_do",))
_AI_MODS = _a("array", 'AI weight modifiers: [{"factor": n | "add": n, "trigger": {"items": '
              '[condition items], "rawLines": [...]}}]. [] or null clears them.',
              aliases=("ai_modifiers",))
_FILTERS = _a("array", "FOCUS_FILTER_* search filters (a single string is accepted). Each must "
              "match ^FOCUS_FILTER_[A-Z0-9_]+$; non-standard ones warn (focus.filter.nonstandard).")
_ALLOW_OVERLAP = _a("boolean", "Place on an occupied cell anyway (default false: occupied cells "
                    "are rejected with nearest free cells suggested).")
_COMPACT = _a("boolean", "true -> one line per preset: kind, group, label and a params "
              "signature ('amount:number*' — * = required). Roughly 1/5 the size. Default false.")
_KIND = _a("string", "Return the full detail of ONE preset kind (params with help text).")


def _focus_write_args(with_position: bool) -> dict:
    """The writable focus fields shared by add_focus and update_focus, in the
    order the error message lists them."""
    out = {"title": _a("string", "Display title.")}
    if with_position:
        out["x"] = _a("integer", "Grid column. Pass with y.")
        out["y"] = _a("integer", "Grid row. Pass with x.")
    out.update({
        "id": _a("string", "Explicit id (^[A-Za-z_][A-Za-z0-9_]*$; usually <TAG>_<slug>).",
                 aliases=("focus_id",)),
        "icon": _a("string", "Sprite name (GFX_...). Verify with search_icons first; an icon "
                   "that does not resolve is rejected when icon roots are configured."),
        "cost": _a("number", "Focus cost in 7-day units: 10 spine, 5 leaf, 1-3 trivial."),
        "description": _a("string", "Flavour text (a sentence or two)."),
        "prerequisites": _PREREQS,
    })
    return out


# The registry ---------------------------------------------------------------------

OP_SPECS: dict = {
    # ----- discovery -----
    "hello": OpSpec(
        "Handshake: app version, protocol, a project summary, the layout convention, the "
        "list of op names and where to start.",
        {}, "{app, version, protocol, project, layout, ops, start_here}", {}),
    "guide": OpSpec(
        "The Millennium Dawn focus-authoring guide, starting with the procedure to follow. "
        "Read it once per session before writing.",
        {}, "{text}", {}),
    "describe_op": OpSpec(
        "The spec of one op (description, args with types/aliases, returns, example) — or, "
        "with no `op`, a compact table of every op.",
        {"op": _a("string", "Op name. Omit for all ops (no examples).")},
        "{op, description, args, returns, example} or {ops: {name: {description, args}}}",
        {"op": "add_focus"}),

    # ----- reads -----
    "get_project": OpSpec(
        "The entire project as JSON (.focusforge.json shape). Large on big trees — prefer "
        "list_focuses with filters.",
        {}, "project dict", {}),
    "list_focuses": OpSpec(
        "Focus summaries (id, title, x, y, icon, cost, prerequisites, mutuallyExclusive, "
        "aiWillDo, aiModifierCount). With no args: the bare list. With any filter/limit: "
        "{focuses, total, returned}.",
        {
            "prefix": _a("string", "Only ids starting with this."),
            "ids": _a("array", "Only these ids.", aliases=("focus_ids",)),
            "x_min": _a("integer", "Inclusive column bound."),
            "x_max": _a("integer", "Inclusive column bound."),
            "y_min": _a("integer", "Inclusive row bound."),
            "y_max": _a("integer", "Inclusive row bound."),
            "fields": _a("array", "Subset of summary keys to return (id is always included)."),
            "limit": _a("integer", "Return at most this many."),
        },
        "list of summaries, or {focuses, total, returned} when filtered",
        {"prefix": "MEX_", "y_min": 0, "y_max": 3, "fields": ["id", "x", "y"], "limit": 50}),
    "get_focus": OpSpec(
        "One focus in full, including completionReward, available and aiModifiers.",
        {"id": _ID}, "focus dict", {"id": "MEX_forge_national_assessment"}),
    "get_selection": OpSpec(
        "The id of the focus currently selected in the editor (may be empty).",
        {}, "{id}", {}),
    "validate": OpSpec(
        "Validate the whole project. Each issue has code, message and focusId.",
        {}, "{errors, warnings, summary}", {}),
    "list_reward_presets": OpSpec(
        "Reward / effect preset catalogue (kind, params). Use compact=true unless you need "
        "help text; kind=<name> for one preset in full.",
        {"compact": _COMPACT, "kind": _KIND},
        "list of presets (or one preset dict with kind=)", {"compact": True}),
    "list_condition_presets": OpSpec(
        "Availability / trigger condition preset catalogue. Use compact=true unless you "
        "need help text; kind=<name> for one preset in full.",
        {"compact": _COMPACT, "kind": _KIND},
        "list of presets (or one preset dict with kind=)", {"compact": True}),
    "reference_data": OpSpec(
        "Millennium Dawn reference values: country tags, parties, focus filters, icon "
        "presets, tech categories, resource/equipment/wargoal/building types, the country's "
        "states, and the authoring conventions. Ask for `sections` to save tokens.",
        {
            "sections": _a("array", "Section names to include (default all): countryTags, "
                           "parties, focusFilters, iconPresets, techCategories, resourceTypes, "
                           "equipmentTypes, countryStates, wargoalTypes, buildingTypes, "
                           "layoutConvention, rewardAuthoring, aiWeightAuthoring, "
                           "costConvention. Short forms work too (filters, tags, icons, "
                           "conventions). The result always lists sections_available."),
            "include_dynamic_tags": _a("boolean", "Keep HOI4 dynamic tags D01..D75 in "
                                       "countryTags (default false)."),
        },
        "{<section>: ..., sections_available}",
        {"sections": ["focusFilters", "costConvention"], "include_dynamic_tags": False}),
    "search_icons": OpSpec(
        "Case-insensitive substring search over the real focus-icon sprite index. An exact "
        "match is listed first with exact=true — use it to verify a GFX_ name before "
        "assigning it. GUI-only (needs icon roots configured).",
        {"query": _a("string", "At least 2 characters.", required=True),
         "limit": _a("integer", "Max results (1-100, default 30).")},
        "{icons, total_matches, shown, exact?}", {"query": "nuclear", "limit": 10}),
    "screenshot": OpSpec(
        "Render a region of the canvas to a PNG and return its path plus each visible "
        "focus's [x, y]. Pass focus_id (one focus + margin), focus_ids (frame a set) or "
        "all=true (whole tree). GUI-only.",
        {"focus_id": _a("string", "Centre on this focus."),
         "focus_ids": _a("array", "Frame these focuses."),
         "all": _a("boolean", "Whole tree.", aliases=("whole_tree",)),
         "margin": _a("integer", "Grid cells of margin (default 3)."),
         "max_px": _a("integer", "Longest image side in pixels (default 1800).")},
        "{path, width, height, focuses_in_view}", {"focus_ids": ["MEX_a", "MEX_b"], "margin": 2}),

    # ----- focus writes -----
    "add_focus": OpSpec(
        "Create one focus. Place it with x+y, or place_below=<id> (nearest free cell on the "
        "row under that focus; placement only, pass prerequisites too), or neither to "
        "auto-place under the tree. Occupied cells, bad ids, unknown preset kinds, dangling "
        "prerequisites and unresolved icons are rejected. Returns the id and inline issues.",
        {**_focus_write_args(with_position=True),
         "place_below": _a("string", "Id of the focus to place this one under (not with x/y)."),
         "completionReward": _REWARD, "available": _AVAILABLE,
         "aiWillDo": _AI_WILL_DO, "aiModifiers": _AI_MODS, "filters": _FILTERS,
         "notes": _a("string", "Author notes (not exported)."),
         "mutuallyExclusive": _MUTEX, "allow_overlap": _ALLOW_OVERLAP},
        "{id, issues, note?}",
        {"id": "MEX_land_reform", "title": "Land Reform", "x": 2, "y": 3, "cost": 5,
         "icon": "GFX_focus_generic_industry", "description": "Redistribute the ejidos.",
         "prerequisites": ["MEX_forge_national_assessment"],
         "filters": ["FOCUS_FILTER_POLITICAL"],
         "completionReward": {"items": [{"kind": "political_power", "params": {"amount": 50}}]},
         "aiWillDo": 10}),
    "update_focus": OpSpec(
        "Change fields on an existing focus (id stays; use rename_focus for that). Move it "
        "with x+y (both) or position={x,y}. prerequisites / mutuallyExclusive / "
        "completionReward / available REPLACE the existing value. Returns the summary and "
        "inline issues.",
        {"id": _ID, **{k: v for k, v in _focus_write_args(with_position=True).items() if k != "id"},
         "position": _a("object", '{"x": int, "y": int} — same as passing x and y.'),
         "filters": _FILTERS, "mutuallyExclusive": _MUTEX,
         "notes": _a("string", "Author notes (not exported)."),
         "completionReward": _REWARD, "available": _AVAILABLE,
         "aiWillDo": _AI_WILL_DO, "aiModifiers": _AI_MODS, "allow_overlap": _ALLOW_OVERLAP},
        "focus summary + issues",
        {"id": "MEX_land_reform", "cost": 10, "x": 4, "y": 3,
         "available": {"items": [{"kind": "has_country_flag", "params": {"flag": "MEX_reform"}}]}}),
    "rename_focus": OpSpec(
        "Rename a focus id and rewrite every reference to it (prerequisites, mutex, "
        "completed-focus checks). Returns the final id (de-duped) and inline issues.",
        {"id": _ID, "new_id": _a("string", "New id (^[A-Za-z_][A-Za-z0-9_]*$).", required=True)},
        "{id, issues}", {"id": "MEX_new_focus_004", "new_id": "MEX_land_reform"}),
    "delete_focus": OpSpec(
        "Delete one focus and strip references to it from other focuses.",
        {"id": _ID}, "{deleted}", {"id": "MEX_land_reform"}),
    "delete_focuses": OpSpec(
        "Delete several focuses at once (one undo step).",
        {"ids": _a("array", "Focus ids.", required=True, aliases=("focus_ids",))},
        "{deleted}", {"ids": ["MEX_a", "MEX_b"]}),
    "link_prerequisite": OpSpec(
        "Make `target` require `prereq`. Both must exist. Refuses cycles (message starts "
        "with 'Skipped'). Returns the message and inline issues.",
        {"target": _a("string", "The focus that gains a prerequisite.", required=True,
                      aliases=("focus",)),
         "prereq": _a("string", "The focus it will require.", required=True,
                      aliases=("prerequisite",))},
        "{message, issues}", {"target": "MEX_land_reform", "prereq": "MEX_forge_national_assessment"}),
    "unlink_prerequisite": OpSpec(
        "Remove `prereq` from `target`'s prerequisites.",
        {"target": _a("string", "The focus to edit.", required=True, aliases=("focus",)),
         "prereq": _a("string", "The prerequisite to remove.", required=True,
                      aliases=("prerequisite",))},
        "{message, issues}", {"target": "MEX_land_reform", "prereq": "MEX_forge_national_assessment"}),
    "set_mutually_exclusive": OpSpec(
        "Make two existing focuses mutually exclusive (symmetric).",
        {"a": _a("string", "First focus id.", required=True, aliases=("focus_a",)),
         "b": _a("string", "Second focus id.", required=True, aliases=("focus_b",))},
        "{message, issues}", {"a": "MEX_land_reform", "b": "MEX_agribusiness"}),
    "remove_mutex": OpSpec(
        "Remove mutual exclusivity between two focuses.",
        {"a": _a("string", "First focus id.", required=True, aliases=("focus_a",)),
         "b": _a("string", "Second focus id.", required=True, aliases=("focus_b",))},
        "{message, issues}", {"a": "MEX_land_reform", "b": "MEX_agribusiness"}),
    "select_focus": OpSpec(
        "Select / highlight a focus in the editor.",
        {"id": _ID}, "{selected}", {"id": "MEX_land_reform"}),

    # ----- project settings -----
    "set_metadata": OpSpec(
        "Set project metadata (any subset).",
        {"projectName": _a("string", "Project name.", aliases=("project_name",)),
         "countryTag": _a("string", "3-letter country tag.", aliases=("country_tag",)),
         "treeId": _a("string", "Focus tree id.", aliases=("tree_id",)),
         "mode": _a("string", "Project mode.")},
        "{updated}", {"projectName": "Mexico Expanded", "treeId": "mexico_expanded"}),
    "set_export_settings": OpSpec(
        "Set export settings (any subset).",
        {"modPrefix": _a("string", "Mod prefix.", aliases=("mod_prefix",)),
         "focusFileName": _a("string", "Output focus file name.", aliases=("focus_file_name",)),
         "localisationPrefix": _a("string", "Localisation / event namespace prefix.",
                                  aliases=("localisation_prefix",)),
         "includeIdeas": _a("boolean", "Export ideas.", aliases=("include_ideas",)),
         "includeEvents": _a("boolean", "Export events.", aliases=("include_events",)),
         "includeCountry": _a("boolean", "Export country history.", aliases=("include_country",))},
        "{updated}", {"includeEvents": True, "localisationPrefix": "MEX_forge"}),

    # ----- ideas / events / decisions -----
    "add_idea": OpSpec(
        "Add an idea / national spirit. Returns the final (de-duped) id.",
        {"idea": _a("object", "{id, title, description, picture, modifierRawLines}.", required=True)},
        "{id}", {"idea": {"id": "MEX_reform_spirit", "title": "Spirit of Reform",
                          "modifierRawLines": ["stability_factor = 0.05"]}}),
    "update_idea": OpSpec(
        "Replace an idea. Renaming rewrites focus reward references.",
        {"id": _a("string", "Existing idea id.", required=True, aliases=("idea_id",)),
         "idea": _a("object", "The full replacement idea.", required=True)},
        "{id}", {"id": "MEX_reform_spirit", "idea": {"id": "MEX_reform_spirit", "title": "S"}}),
    "delete_idea": OpSpec(
        "Delete an idea.", {"id": _a("string", "Idea id.", required=True, aliases=("idea_id",))},
        "{deleted}", {"id": "MEX_reform_spirit"}),
    "add_event": OpSpec(
        "Add an event. Ids must be <localisationPrefix>.<n>. Option items use reward preset "
        "kinds; option/event triggers use condition preset kinds. Returns the final id.",
        {"event": _a("object", "{id, title, description, picture, isTriggeredOnly, options: "
                     "[{key, text, items, trigger, aiChance, effectRawLines}], trigger}.",
                     required=True)},
        "{id}", {"event": {"id": "MEX_forge.3", "title": "Reform Passed", "isTriggeredOnly": True,
                           "options": [{"key": "a", "text": "Good.",
                                        "items": [{"kind": "stability", "params": {"amount": 0.05}}]}]}}),
    "update_event": OpSpec(
        "Replace an event. Renaming rewrites focus reward references.",
        {"id": _a("string", "Existing event id.", required=True, aliases=("event_id",)),
         "event": _a("object", "The full replacement event.", required=True)},
        "{id}", {"id": "MEX_forge.3", "event": {"id": "MEX_forge.3", "title": "Reform Passed"}}),
    "delete_event": OpSpec(
        "Delete an event.", {"id": _a("string", "Event id.", required=True, aliases=("event_id",))},
        "{deleted}", {"id": "MEX_forge.3"}),
    "add_decision": OpSpec(
        "Add a decision (needs an existing category id).",
        {"decision": _a("object", "{id, title, category, ...} — see list_decisions for the shape.",
                        required=True)},
        "{id}", {"decision": {"id": "MEX_hold_referendum", "title": "Hold a Referendum",
                              "category": "MEX_reform_decisions"}}),
    "update_decision": OpSpec(
        "Replace a decision.",
        {"id": _a("string", "Existing decision id.", required=True, aliases=("decision_id",)),
         "decision": _a("object", "The full replacement decision.", required=True)},
        "{id}", {"id": "MEX_hold_referendum", "decision": {"id": "MEX_hold_referendum", "title": "R"}}),
    "delete_decision": OpSpec(
        "Delete a decision.",
        {"id": _a("string", "Decision id.", required=True, aliases=("decision_id",))},
        "{deleted}", {"id": "MEX_hold_referendum"}),
    "add_decision_category": OpSpec(
        "Add a decision category.",
        {"category": _a("object", "{id, title, icon, ...}.", required=True)},
        "{id}", {"category": {"id": "MEX_reform_decisions", "title": "Reforms"}}),
    "update_decision_category": OpSpec(
        "Replace a decision category.",
        {"id": _a("string", "Existing category id.", required=True, aliases=("category_id",)),
         "category": _a("object", "The full replacement category.", required=True)},
        "{id}", {"id": "MEX_reform_decisions", "category": {"id": "MEX_reform_decisions", "title": "R"}}),
    "delete_decision_category": OpSpec(
        "Delete a decision category.",
        {"id": _a("string", "Category id.", required=True, aliases=("category_id",))},
        "{deleted}", {"id": "MEX_reform_decisions"}),
    "list_decisions": OpSpec(
        "All decisions and decision categories in full.", {}, "{decisions, categories}", {}),

    # ----- IO / checks -----
    "load_project": OpSpec(
        "Open a .focusforge.json file in the editor, REPLACING the loaded project. Only when "
        "the user asks.",
        {"path": _a("string", "Absolute path to the project file.", required=True)},
        "{loaded, focuses, name}", {"path": "C:/mods/mexico.focusforge.json"}),
    "save": OpSpec(
        "Save the project to disk (the editor's current file unless `path`). Only when the "
        "user asks.",
        {"path": _a("string", "Save-as path (optional).")}, "{saved}", {}),
    "export": OpSpec(
        "List the files an export writes; with `dir`, also write them there. Only write when "
        "the user asks.",
        {"dir": _a("string", "Output directory (optional).", aliases=("directory",))},
        "{files, count?, written_to?}", {}),
    "smoke_check": OpSpec(
        "Parse every file the export would write and apply the game's load-time structural "
        "rules. Nothing is written.",
        {}, "{files, errors, warnings, summary}", {}),
    "scan_error_log": OpSpec(
        "After the user launched HOI4: the error.log lines about this mod, each mapped to "
        "its focus.",
        {"path": _a("string", "Log file (default: the game's error.log)."),
         "mod_dir": _a("string", "Exported mod folder (default: the project's export dir)."),
         "since": _a("string", "HH:MM:SS — keep only lines after this time.")},
        "{log, exists, stale, hits}", {"since": "12:00:00"}),

    # ----- batch -----
    "batch": OpSpec(
        "Apply up to 200 ops atomically (all-or-nothing, one undo step). Use it for every "
        "feature of more than ~3 focuses: add focuses first, then links. Forward references "
        "in prerequisites/mutuallyExclusive to focuses created later in the batch are fine; "
        "link ops need both focuses to already exist. Not allowed inside: batch, "
        "load_project, save, export.",
        {"ops": _a("array", '[{"op": name, "args": {...}}, ...]', required=True)},
        "{results, count, issues, summary}",
        {"ops": [{"op": "add_focus", "args": {"id": "MEX_a", "x": 0, "y": 5, "title": "A"}},
                 {"op": "add_focus", "args": {"id": "MEX_b", "x": 0, "y": 6, "title": "B",
                                              "prerequisites": ["MEX_a"]}}]}),
}

# Ops that need the GUI (their handlers live in ui/agent_bridge.py).
GUI_ONLY_OPS = ("screenshot", "search_icons")


def accepted_arg_names(op: str) -> list:
    """Canonical arg names of an op, in declaration order (the order error
    messages list them)."""
    return list(OP_SPECS[op].args)


def alias_map(op: str) -> dict:
    """alias -> canonical name for one op."""
    return {alias: name for name, a in OP_SPECS[op].args.items() for alias in a.get("aliases", ())}


def describe(op=None) -> dict:
    """The describe_op payload: one op in full, or every op without examples."""
    if op:
        spec = OP_SPECS.get(op)
        if spec is None:
            raise ValueError(f"Unknown op '{op}'. Known: {', '.join(sorted(OP_SPECS))}.")
        return {"op": op, "description": spec.description, "args": spec.args,
                "returns": spec.returns, "example": spec.example}
    return {"ops": {name: {"description": s.description, "args": s.args}
                    for name, s in sorted(OP_SPECS.items())}}


def tool_schemas() -> list:
    """OP_SPECS as OpenAI-style function tools. Aliases are deliberately left
    out — a tool schema should teach the canonical spelling."""
    tools = []
    for name, spec in sorted(OP_SPECS.items()):
        props = {}
        required = []
        for arg, a in spec.args.items():
            props[arg] = {"type": a["type"], "description": a["description"]}
            if a["type"] == "array":
                props[arg]["items"] = {}
            if a.get("required"):
                required.append(arg)
        params = {"type": "object", "properties": props, "additionalProperties": False}
        if required:
            params["required"] = required
        tools.append({"type": "function",
                      "function": {"name": name, "description": spec.description,
                                   "parameters": params}})
    return tools
