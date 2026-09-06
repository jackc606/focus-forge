"""FastMCP server proxying tool calls to a running Focus Forge editor's AI Bridge.

Architecture: the editor (GUI) hosts a loopback TCP server (enable **AI Bridge** in its
toolbar) and writes a discovery file with the port. This process is launched by the MCP
client (Claude Code/Desktop) over stdio; each tool opens a short-lived socket to that port,
sends one ``{op, args}`` line, and returns the response. Mutations apply to the **live**
project — focuses/events appear on the canvas as the agent works.
"""
from __future__ import annotations

import json
import socket

from mcp.server.fastmcp import FastMCP

from core.bridge_discovery import read_bridge_info

mcp = FastMCP("focusforge")

_EDITOR_OFF = ("Focus Forge isn't running, or its AI Bridge is off. Open Focus Forge and "
               "click 'AI Bridge' in the toolbar, then retry.")

# The Millennium Dawn authoring guide lives in core (Qt-free) so the bridge's
# own `guide` op and this server serve the SAME text; see core/md_focus_guide.py.
from core.md_focus_guide import MD_FOCUS_GUIDE  # noqa: E402


class BridgeError(Exception):
    pass


def _call(op: str, args: "dict | None" = None):
    """Send one op to the live editor and return its result (raises BridgeError)."""
    info = read_bridge_info()
    if not info or not info.get("port"):
        raise BridgeError(_EDITOR_OFF)
    port = int(info["port"])
    # The editor authenticates each request against the token it published in the
    # (per-user, private) discovery file. Reading that file is what proves this
    # proxy is running as the same user.
    request = {"op": op, "args": args or {}, "token": info.get("token", "")}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=15) as s:
            s.settimeout(15)
            s.sendall((json.dumps(request) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as exc:
        raise BridgeError(f"Couldn't reach Focus Forge on port {port} ({exc}). "
                          "Is the AI Bridge still on?")
    if not buf:
        raise BridgeError("Empty response from the editor.")
    try:
        resp = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        # The socket closed mid-reply (e.g. the editor quit while writing) —
        # surface the same friendly guidance as the other connection failures.
        raise BridgeError("Focus Forge closed the connection mid-reply — "
                          "is the AI Bridge still on?")
    if not resp.get("ok"):
        raise BridgeError(resp.get("error", "Unknown bridge error."))
    return resp.get("result")


def _compact(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


# ======================= read tools =======================

@mcp.tool()
def ping() -> dict:
    """Check the connection. Returns app version, protocol, a project summary, the list
    of bridge op names and where to start (guide, then describe_op)."""
    return _call("hello")


@mcp.tool()
def describe_op(op: str | None = None) -> dict:
    """The spec of one bridge op — description, args (type, required, aliases), returns,
    a complete example — or, with no `op`, a compact table of every op. Call it for any
    op you have not used yet; arg names it does not list are REJECTED by the bridge."""
    return _call("describe_op", _compact(op=op))


@mcp.tool()
def guide() -> str:
    """The Millennium Dawn focus-authoring guide, starting with the procedure to follow
    (hello -> guide -> describe_op; read narrowly; plan cells; build in one batch; fix
    every inline issue; validate + screenshot). Same text as md_focus_guide, served by
    the live editor."""
    return _call("guide")["text"]


@mcp.tool()
def get_project() -> dict:
    """Return the entire current project as JSON (metadata, focuses, ideas, events,
    exportSettings, country). This is the canonical .focusforge.json shape."""
    return _call("get_project")


@mcp.tool()
def list_focuses(prefix: str | None = None, ids: list | None = None,
                 x_min: int | None = None, x_max: int | None = None,
                 y_min: int | None = None, y_max: int | None = None,
                 fields: list | None = None, limit: int | None = None):
    """List focus summaries (id, title, x, y, icon, cost, prerequisites, mutuallyExclusive,
    aiWillDo, aiModifierCount). On a large tree narrow it: `prefix` (id starts with),
    `ids`, inclusive `x_min/x_max/y_min/y_max` bounds, `fields` (subset of summary keys;
    id always included) and `limit`. With no args returns the bare list; with any filter
    returns {focuses, total, returned}."""
    return _call("list_focuses", _compact(prefix=prefix, ids=ids, x_min=x_min, x_max=x_max,
                                          y_min=y_min, y_max=y_max, fields=fields, limit=limit))


@mcp.tool()
def list_ideas() -> list:
    """Compact list of the project's ideas / national spirits (id, title, picture,
    modifier count) — reference one from an add_idea reward or reuse its picture."""
    return _call("list_ideas")


@mcp.tool()
def list_events() -> list:
    """Compact list of the project's events (id, eventType, title, option keys,
    picture) — pick the next free <prefix>.<n> and reference events from rewards."""
    return _call("list_events")


@mcp.tool()
def get_focus(focus_id: str) -> dict:
    """Return one focus in full (including completionReward and available blocks)."""
    return _call("get_focus", {"id": focus_id})


@mcp.tool()
def get_selection() -> dict:
    """Return the id of the focus currently selected in the editor (may be empty)."""
    return _call("get_selection")


@mcp.tool()
def canvas_screenshot(focus_id: str | None = None, focus_ids: list | None = None,
                      whole_tree: bool = False, margin: int = 3) -> dict:
    """Render the focus-tree canvas to a PNG and return its file path so you can SEE the
    actual layout (placement, spacing, overlaps, prerequisite lines). Pass focus_id to
    center on one focus (+ margin cells), focus_ids to frame a set (e.g. a chunk you just
    built), or whole_tree=True for the entire tree (labels get small). The result includes
    `focuses_in_view` with each focus's [x, y]. Open the returned `path` to view it."""
    args = _compact(focus_id=focus_id, focus_ids=focus_ids, margin=margin)
    if whole_tree:
        args["all"] = True
    return _call("screenshot", args)


@mcp.tool()
def validate() -> dict:
    """Validate the project. Returns {errors, warnings, summary} — each issue has
    code/message/focusId. Call this after edits to confirm the tree is sound."""
    return _call("validate")


@mcp.tool()
def smoke_check() -> dict:
    """Parse every file the export would write with the app's own script reader and
    apply the game's load-time rules (balanced braces, focus/event structure, localisation
    header + BOM, every focus/idea/event localised). Nothing is written. Returns
    {files, errors, warnings, summary}. Run it before telling the user the mod is ready."""
    return _call("smoke_check")


@mcp.tool()
def scan_error_log(since: str = "", path: str = "") -> dict:
    """After the user launched Hearts of Iron IV with the mod: the error.log lines that
    mention this mod, each mapped to the focus it comes from (focusId). `since` is an
    optional HH:MM:SS to keep only the latest launch; `path` overrides the default
    Documents/Paradox Interactive/Hearts of Iron IV/logs/error.log. `stale` = the mod was
    exported after the log was written (line references may be off)."""
    return _call("scan_error_log", _compact(since=since or None, path=path or None))


@mcp.tool()
def list_reward_presets(compact: bool = True, kind: str | None = None):
    """compact=True (default): one line per focus-reward / event-effect preset — kind, group,
    label and a params signature like 'amount:number*' (* = required). Pass kind=<name> for
    ONE preset in full (help text, defaults, options); compact=False for everything in full
    (~33 KB). Build completionReward items as {"kind": ..., "params": {...}}; unknown kinds
    and unknown/missing params are rejected by the bridge."""
    return _call("list_reward_presets", _compact(compact=compact or None, kind=kind))


@mcp.tool()
def list_condition_presets(compact: bool = True, kind: str | None = None):
    """compact=True (default): one line per availability / trigger condition preset — kind,
    group, label and a params signature (* = required). kind=<name> for one preset in full;
    compact=False for everything in full. Use these for `available.items` and AI-modifier
    triggers."""
    return _call("list_condition_presets", _compact(compact=compact or None, kind=kind))


@mcp.tool()
def reference_data(sections: list | None = None, include_dynamic_tags: bool = False) -> dict:
    """Millennium Dawn reference data — pass `sections` to fetch only what you need (e.g.
    ["focusFilters", "costConvention"]); the result always lists `sections_available`
    (countryTags, parties, focusFilters, iconPresets, techCategories, resourceTypes,
    equipmentTypes, countryStates, wargoalTypes, buildingTypes, layoutConvention,
    rewardAuthoring, aiWeightAuthoring, costConvention). HOI4's dynamic tags D01..D75 are
    dropped from countryTags unless include_dynamic_tags=True."""
    return _call("reference_data", _compact(sections=sections,
                                            include_dynamic_tags=include_dynamic_tags or None))


@mcp.tool()
def search_icons(query: str, limit: int = 30) -> dict:
    """Search the real sprite index for focus icon names (case-insensitive substring,
    ~5.8k GFX_ names). Returns {icons, total_matches, shown}; if `query` exactly matches
    a sprite name it's listed first with "exact": true — use that to VERIFY an icon name
    resolves before assigning it to a focus. Never guess GFX_ names: a wrong one renders
    blank in-game. Needs icon roots configured in the editor (Settings -> In-game Icons)."""
    return _call("search_icons", {"query": query, "limit": limit})


# ======================= focus tools =======================

@mcp.tool()
def add_focus(title: str | None = None, x: int | None = None, y: int | None = None,
              focus_id: str | None = None, icon: str | None = None,
              cost: float | None = None, description: str | None = None,
              prerequisites: list | None = None, place_below: str | None = None,
              completion_reward: dict | None = None, available: dict | None = None,
              filters: list | None = None, ai_will_do: float | None = None,
              ai_modifiers: list | None = None, mutually_exclusive: list | None = None,
              allow_overlap: bool = False) -> dict:
    """Create a focus and return {id, issues}. Provide x and y (grid cells) to place it, pass
    place_below=<focus_id> to drop it in the nearest free cell on the row under that focus
    (mutually exclusive with x/y), or omit all three to auto-place below the tree.
    place_below is PLACEMENT ONLY — it does not link the parent; also pass
    prerequisites=[parent_id] when you mean a child focus. Pass focus_id to set the id
    explicitly (else it's an auto placeholder you can rename). completion_reward/available
    take the JSON shape from get_focus (use list_reward_presets / list_condition_presets to
    build items). prerequisites is a list of blocks: a plain id is required (AND); a nested
    list is an OR group, e.g. [["a","b"]] means a OR b, [["a","b"],"c"] means (a OR b) AND c.
    REJECTED up front (nothing applied): an occupied cell (unless allow_overlap), an id with
    spaces/punctuation, an unknown preset kind or param, a missing required param, a
    prerequisite that doesn't exist, an icon that doesn't resolve. `issues` lists the
    validation errors/warnings touching the new focus — fix every error."""
    args = _compact(title=title, x=x, y=y, id=focus_id, icon=icon, cost=cost,
                    description=description, prerequisites=prerequisites,
                    place_below=place_below, filters=filters, aiWillDo=ai_will_do,
                    aiModifiers=ai_modifiers, mutuallyExclusive=mutually_exclusive,
                    allow_overlap=allow_overlap or None,
                    completionReward=completion_reward, available=available)
    return _call("add_focus", args)


@mcp.tool()
def update_focus(focus_id: str, title: str | None = None, description: str | None = None,
                 icon: str | None = None, cost: float | None = None,
                 x: int | None = None, y: int | None = None, filters: list | None = None,
                 prerequisites: list | None = None, mutually_exclusive: list | None = None,
                 notes: str | None = None, completion_reward: dict | None = None,
                 available: dict | None = None, ai_will_do: float | None = None,
                 ai_modifiers: list | None = None, allow_overlap: bool = False) -> dict:
    """Update fields on an existing focus (id stays the same — use rename_focus to change it).
    To move it, pass BOTH x and y (an occupied cell is rejected unless allow_overlap).
    completion_reward/available replace those blocks entirely. prerequisites is a list of
    blocks: plain ids are AND-ed; a nested list is an OR group (e.g. [["a","b"]] = a OR b).
    Passing prerequisites replaces the focus's prereqs entirely. Same up-front rejections as
    add_focus; returns the focus summary plus `issues` for this focus."""
    args = _compact(id=focus_id, title=title, description=description, icon=icon, cost=cost,
                    filters=filters, prerequisites=prerequisites,
                    mutuallyExclusive=mutually_exclusive, notes=notes,
                    completionReward=completion_reward, available=available,
                    aiWillDo=ai_will_do, aiModifiers=ai_modifiers,
                    allow_overlap=allow_overlap or None)
    if x is not None and y is not None:
        args["position"] = {"x": x, "y": y}
    return _call("update_focus", args)


@mcp.tool()
def rename_focus(focus_id: str, new_id: str) -> dict:
    """Rename a focus's id. Rewrites every reference (prerequisites, mutual exclusions,
    completed-focus checks) and de-dupes. Returns the final id."""
    return _call("rename_focus", {"id": focus_id, "new_id": new_id})


@mcp.tool()
def delete_focus(focus_id: str) -> dict:
    """Delete a focus and strip all references to it from other focuses."""
    return _call("delete_focus", {"id": focus_id})


@mcp.tool()
def link_prerequisite(target: str, prereq: str) -> dict:
    """Make `target` require `prereq` (prereq becomes a prerequisite of target). Refuses to
    create a cycle (returns a 'Skipped' message in that case)."""
    return _call("link_prerequisite", {"target": target, "prereq": prereq})


@mcp.tool()
def unlink_prerequisite(target: str, prereq: str) -> dict:
    """Remove a prerequisite link from `target`."""
    return _call("unlink_prerequisite", {"target": target, "prereq": prereq})


@mcp.tool()
def set_mutually_exclusive(focus_a: str, focus_b: str) -> dict:
    """Make two focuses mutually exclusive (symmetric)."""
    return _call("set_mutually_exclusive", {"a": focus_a, "b": focus_b})


@mcp.tool()
def remove_mutex(focus_a: str, focus_b: str) -> dict:
    """Remove mutual exclusivity between two focuses."""
    return _call("remove_mutex", {"a": focus_a, "b": focus_b})


@mcp.tool()
def select_focus(focus_id: str) -> dict:
    """Select/highlight a focus in the editor (handy to show what you're working on)."""
    return _call("select_focus", {"id": focus_id})


@mcp.tool()
def apply_batch(ops: list) -> dict:
    """Apply a list of bridge operations ATOMICALLY: all-or-nothing, one canvas repaint,
    and a SINGLE undo step for the user. Whenever you're building or editing more than
    ~3 focuses (a branch, a re-layout, a bulk retag), send ONE apply_batch instead of
    individual calls — the user can then undo your whole change in one Ctrl+Z.
    `ops` = [{"op": "add_focus", "args": {...}}, ...] (max 200), using the same op names
    and args as the underlying bridge ops (add_focus, update_focus, link_prerequisite,
    delete_focus, add_idea, add_event, ...). add_focus place_below may reference a focus
    created earlier in the same batch, and prerequisites/mutuallyExclusive may reference
    focuses created LATER in the batch (checked at the end); link ops need both focuses to
    exist already, so add focuses first, then links. Not allowed inside: batch,
    load_project, save, export. If any op fails, NOTHING is applied and the error names the
    failing op. Returns {"results": [...], "count": N, "issues": [validation issues on
    every touched focus], "summary": {"errors", "warnings"}} — fix every error."""
    return _call("batch", {"ops": ops})


# ======================= project / export =======================

@mcp.tool()
def set_metadata(project_name: str | None = None, country_tag: str | None = None,
                 tree_id: str | None = None, mode: str | None = None) -> dict:
    """Set top-level project metadata."""
    return _call("set_metadata", _compact(projectName=project_name, countryTag=country_tag,
                                          treeId=tree_id, mode=mode))


@mcp.tool()
def set_export_settings(focus_file_name: str | None = None, localisation_prefix: str | None = None,
                        mod_prefix: str | None = None, include_ideas: bool | None = None,
                        include_events: bool | None = None, include_country: bool | None = None) -> dict:
    """Set export settings (output filename, localisation/namespace prefix, include flags)."""
    return _call("set_export_settings", _compact(
        focusFileName=focus_file_name, localisationPrefix=localisation_prefix,
        modPrefix=mod_prefix, includeIdeas=include_ideas, includeEvents=include_events,
        includeCountry=include_country))


# ======================= ideas / events =======================

@mcp.tool()
def add_idea(idea: dict) -> dict:
    """Add an idea/national spirit. `idea` = {id, title, description, picture, modifierRawLines}.
    Returns the final (de-duped) id."""
    return _call("add_idea", {"idea": idea})


@mcp.tool()
def update_idea(idea_id: str, idea: dict) -> dict:
    """Replace the idea with id `idea_id`. Renaming rewrites focus reward references."""
    return _call("update_idea", {"id": idea_id, "idea": idea})


@mcp.tool()
def delete_idea(idea_id: str) -> dict:
    """Delete an idea."""
    return _call("delete_idea", {"id": idea_id})


@mcp.tool()
def add_event(event: dict) -> dict:
    """Add an event. `event` = {id, title, description, picture, eventType, isTriggeredOnly,
    options:[{key,text,items,trigger,aiChance,effectRawLines}], trigger, …}. Event ids must be
    '<localisationPrefix>.<suffix>'. Returns the final (de-duped) id."""
    return _call("add_event", {"event": event})


@mcp.tool()
def update_event(event_id: str, event: dict) -> dict:
    """Replace the event with id `event_id`. Renaming rewrites focus reward references."""
    return _call("update_event", {"id": event_id, "event": event})


@mcp.tool()
def delete_event(event_id: str) -> dict:
    """Delete an event."""
    return _call("delete_event", {"id": event_id})


# ======================= IO =======================

@mcp.tool()
def open_project(path: str) -> dict:
    """Open a .focusforge.json project file in the editor (replaces what's loaded)."""
    return _call("load_project", {"path": path})


@mcp.tool()
def save_project(path: str | None = None) -> dict:
    """Save the project to disk. Uses the editor's current file unless `path` is given."""
    return _call("save", _compact(path=path))


@mcp.tool()
def export_mod(directory: str | None = None) -> dict:
    """Export the HOI4 mod files. Returns the list of relative paths; if `directory` is given,
    also writes them there."""
    return _call("export", _compact(dir=directory))


# ======================= authoring guidance =======================

@mcp.tool()
def md_focus_guide() -> str:
    """Return the Millennium Dawn focus-authoring conventions (cost tiers, icon/filter
    rules, structure, MD reward idioms). Read this before adding or editing focuses so
    output matches real MD trees. Works even if the editor bridge is off."""
    return MD_FOCUS_GUIDE


@mcp.prompt()
def author_md_focuses() -> str:
    """Conventions for authoring Millennium Dawn focuses through the Focus Forge bridge."""
    return MD_FOCUS_GUIDE


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
