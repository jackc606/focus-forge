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

# Empirically-grounded conventions (measured from a real 227-focus MD submod). Load
# this before authoring focuses so output matches Millennium Dawn idioms instead of
# generic defaults. Exposed as both a prompt (author_md_focuses) and a tool
# (md_focus_guide); reference_data carries the machine-readable cost/filter data.
MD_FOCUS_GUIDE = """\
# Authoring Millennium Dawn focuses via the Focus Forge bridge

Real MD trees follow tight conventions. Match them — generic defaults read as AI slop.

## Cost (never uniform)
- `10` is the MD default (~70 days) — use for spine / branch-head / capstone focuses.
- `5` for granular leaf or follow-up focuses.
- `1`–`3` for trivial, near-free picks.
Roughly: early backbone trends to 10, deep sub-branches to 5. Don't inflate capstones above 10.

## Icons (distinct & thematic)
One specific icon PER focus — real trees are ~1:1 unique. Reuse ONLY inside a tight
thematic cluster (e.g. several nuclear focuses sharing a nuclear icon is fine). Prefer
specific, evocative names over generic ones. Check `reference_data.iconPresets` and
existing focus icons via `get_focus` before picking.

## Search filters (almost always present)
~80% of focuses carry 1–2 `FOCUS_FILTER_*` tags matching their theme. Pick from:
POLITICAL, INDUSTRY, INFLUENCE, RESEARCH, INTERNAL_FACTION, STABILITY, ANNEXATION,
MANPOWER, RESOURCE, FOREIGN_POLICY, WAR_SUPPORT, ECONOMY, EXPENDITURE. (Pass via the
focus `filters` list.)

## Structure (lean into choice)
- ~⅔ of focuses have an `available` gate; ~⅓ are part of a `mutually_exclusive` fork.
- Prerequisites are a list of blocks. A plain id is one required block; several
  blocks are AND-ed (`["a","b"]` = need both). A nested list is one OR block
  (`[["a","b"]]` = need either). Use OR to let mutually-exclusive paths reconverge
  (e.g. a peace-OR-war fork merging back); separate AND blocks of mutex focuses
  are unreachable.
- Pay off a `set_country_flag` with a downstream `available = { has_country_flag = X }`.

## Rewards
Use structured presets for common bonuses (political power, stability, flags, ideas,
tech bonus — see `list_reward_presets`). For MD-specific effects use the focus
`completionReward.rawLines`, e.g.:
- treasury: `set_temp_variable = { treasury_change = N }` + `modify_treasury_effect = yes`
- party shifts: `add_popularity = { ... }`, ruling-party / coalition arrays
- construction: `add_building_construction = { type = X level = N instant_build = yes }`
- add a `custom_effect_tooltip = KEY` to scripted / `hidden_effect` blocks.

## Namespaces & tone
Events: `<localisationPrefix>.<n>` (e.g. SYR.1). Ideas: `<TAG>_<slug>`.
Write terse, dry, flavorful prose — a sentence or two of description per focus.
"""


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
    resp = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    if not resp.get("ok"):
        raise BridgeError(resp.get("error", "Unknown bridge error."))
    return resp.get("result")


def _compact(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


# ======================= read tools =======================

@mcp.tool()
def ping() -> dict:
    """Check the connection. Returns app version, protocol, and a project summary."""
    return _call("hello")


@mcp.tool()
def get_project() -> dict:
    """Return the entire current project as JSON (metadata, focuses, ideas, events,
    exportSettings, country). This is the canonical .focusforge.json shape."""
    return _call("get_project")


@mcp.tool()
def list_focuses() -> list:
    """List focuses: id, title, position (x,y), icon, cost, prerequisites, mutuallyExclusive."""
    return _call("list_focuses")


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
def list_reward_presets() -> list:
    """List the available focus-reward / event-effect presets (kind, label, params).
    Use a preset's kind + params to build a completionReward item or event option effect."""
    return _call("list_reward_presets")


@mcp.tool()
def list_condition_presets() -> list:
    """List the available availability / trigger condition presets (kind, label, params)."""
    return _call("list_condition_presets")


@mcp.tool()
def reference_data() -> dict:
    """Millennium Dawn reference data: country tags, parties, focus filters, icon presets,
    tech categories, resource/equipment/wargoal/building types. Use these for valid values."""
    return _call("reference_data")


# ======================= focus tools =======================

@mcp.tool()
def add_focus(title: str | None = None, x: int | None = None, y: int | None = None,
              focus_id: str | None = None, icon: str | None = None,
              cost: float | None = None, description: str | None = None,
              prerequisites: list | None = None,
              completion_reward: dict | None = None, available: dict | None = None) -> dict:
    """Create a focus and return its id. Provide x and y (grid cells) to place it, or omit
    both to auto-place below the tree. Pass focus_id to set the id explicitly (else it's an
    auto placeholder you can rename). completion_reward/available take the JSON shape from
    get_focus (use list_reward_presets / list_condition_presets to build items).
    prerequisites is a list of blocks: a plain id is required (AND); a nested list is
    an OR group, e.g. [["a","b"]] means a OR b, [["a","b"],"c"] means (a OR b) AND c."""
    args = _compact(title=title, x=x, y=y, id=focus_id, icon=icon, cost=cost,
                    description=description, prerequisites=prerequisites,
                    completionReward=completion_reward, available=available)
    return _call("add_focus", args)


@mcp.tool()
def update_focus(focus_id: str, title: str | None = None, description: str | None = None,
                 icon: str | None = None, cost: float | None = None,
                 x: int | None = None, y: int | None = None, filters: list | None = None,
                 prerequisites: list | None = None, mutually_exclusive: list | None = None,
                 notes: str | None = None, completion_reward: dict | None = None,
                 available: dict | None = None) -> dict:
    """Update fields on an existing focus (id stays the same — use rename_focus to change it).
    To move it, pass BOTH x and y. completion_reward/available replace those blocks entirely.
    prerequisites is a list of blocks: plain ids are AND-ed; a nested list is an OR group
    (e.g. [["a","b"]] = a OR b). Passing prerequisites replaces the focus's prereqs entirely."""
    args = _compact(id=focus_id, title=title, description=description, icon=icon, cost=cost,
                    filters=filters, prerequisites=prerequisites,
                    mutuallyExclusive=mutually_exclusive, notes=notes,
                    completionReward=completion_reward, available=available)
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
