# Focus Forge — AI agent (MCP) integration

Let an AI agent (Claude Code / Claude Desktop) **edit the project you have open**, live.
Focuses, ideas, and events the agent creates appear on the canvas as it works.

## How it works

```
Claude (MCP client) ──stdio──> focusforge_mcp ──TCP 127.0.0.1:PORT──> Focus Forge (AI Bridge)
```

- The editor hosts a **loopback-only** TCP server (the *AI Bridge*) and writes a small
  discovery file (`bridge.json`) with its port.
- `focusforge_mcp` is launched by your MCP client over stdio; each tool call opens a short-lived
  socket to that port and runs one operation against the **live** project.
- Every mutation reuses the editor's own logic (id de-dupe, prerequisite cycle refusal, reference
  rewriting), so the agent can't produce a state the GUI couldn't.

## Setup — installed app (no Python needed)

The packaged build ships a console **`focusforge-mcp.exe`** next to `FocusForge.exe`,
plus a ready-to-use `.mcp.json`. Nothing to `pip install`.

1. **Enable the bridge** in Focus Forge: click **AI Bridge** in the toolbar (pill turns
   green, `AI Bridge: on :<port>`).
2. **Register the server**:
   - **Claude Code**: start it in the install folder (the one with `FocusForge.exe`); it
     finds the shipped `.mcp.json` and offers the `focusforge` server. Approve it.
   - **Claude Desktop**: add to `claude_desktop_config.json`, using the full path to the
     bundled exe:
     ```json
     {
       "mcpServers": {
         "focusforge": {
           "command": "C:\\Program Files\\Focus Forge\\focusforge-mcp.exe"
         }
       }
     }
     ```

## Setup — from source

> Needs Python plus this repo (with `main.py`, `focusforge_mcp/`, `core/`, `.mcp.json`).

1. **Install the proxy dependency** (once). Open a terminal in the repo folder and run:
   ```
   pip install mcp
   ```
   On Windows: open the folder in File Explorer, click the address bar, type `cmd`, press
   Enter, then run the line above. (`pip install -e ".[agent]"` also works and is equivalent —
   the only extra dependency is `mcp`.)
2. **Enable the bridge** in Focus Forge: click **AI Bridge** in the toolbar. The status pill
   shows `AI Bridge: on :<port>`. It's **off by default** and only listens on `127.0.0.1` — an
   agent can never touch the project unless you turn it on.
3. **Register the MCP server** with your client:
   - **Claude Code**: the repo ships `.mcp.json` — run Claude Code from the repo root and approve
     the `focusforge` server.
   - **Claude Desktop**: add to `claude_desktop_config.json`:
     ```json
     {
       "mcpServers": {
         "focusforge": {
           "command": "python",
           "args": ["-m", "focusforge_mcp"],
           "cwd": "C:\\Users\\jackc\\hoi4-focus-forge-py"
         }
       }
     }
     ```
     (`cwd` must be the repo root so the proxy can import `core`.)

Then ask the agent things like *"add a 3-focus political branch under MEX_forge_national_assessment
and validate."*

## Tools

| Group | MCP tool | Bridge op | Notes |
|---|---|---|---|
| Discovery | `ping` | `hello` | version, project summary, `ops` list, `start_here` |
| | `guide` / `md_focus_guide` | `guide` | MD authoring guide; starts with the **procedure** to follow |
| | `describe_op(op=None)` | `describe_op` | one op's args/aliases/example, or a table of every op |
| Read | `get_project` | `get_project` | whole project — avoid on large trees |
| | `list_focuses(prefix, ids, x_min…y_max, fields, limit)` | `list_focuses` | bare list with no args; `{focuses, total, returned}` when filtered |
| | `get_focus`, `get_selection`, `validate`, `smoke_check`, `scan_error_log` | same | |
| | `list_reward_presets(compact=True, kind=None)` | `list_reward_presets` | compact = ~1/5 the size; `kind=` for one preset in full |
| | `list_condition_presets(compact=True, kind=None)` | `list_condition_presets` | |
| | `reference_data(sections=None, include_dynamic_tags=False)` | `reference_data` | ask for the sections you need; D01..D75 dropped by default |
| | `search_icons`, `canvas_screenshot` | `search_icons`, `screenshot` | GUI-only |
| Focus edits | `add_focus`, `update_focus`, `rename_focus`, `delete_focus` | same | |
| | `link_prerequisite`, `unlink_prerequisite`, `set_mutually_exclusive`, `remove_mutex`, `select_focus` | same | |
| | `apply_batch` | `batch` | atomic, one undo step, up to 200 ops |
| Content | `set_metadata`, `set_export_settings`, `add_idea`/`update_idea`/`delete_idea`, `add_event`/`update_event`/`delete_event` | same | |
| IO | `open_project`, `save_project`, `export_mod` | `load_project`, `save`, `export` | only when the user asks |

### Arg names and aliases

Every op has a spec (`describe_op`). Arg names outside the spec are **rejected** with the
accepted list and a "did you mean" hint — a misspelt arg can never be silently dropped.
Aliases are accepted everywhere: `focus_id` → `id`, `focus`/`prerequisite` → `target`/`prereq`,
`focus_a`/`focus_b` → `a`/`b`, and snake_case `completion_reward` / `mutually_exclusive` /
`ai_will_do` / `ai_modifiers` for the camelCase fields. `update_focus` takes top-level `x` + `y`
(both) as well as `position`. A single string for `filters` is treated as a one-item list.

### Fail-fast checks on writes

`add_focus`, `update_focus`, `rename_focus`, `link_prerequisite`, `set_mutually_exclusive` (and
every batch entry) reject up front, before anything is applied:

- an id that isn't `^[A-Za-z_][A-Za-z0-9_]*$` (a slug is suggested);
- an **occupied cell** (nearest legal free cells are suggested; `allow_overlap=true` overrides);
- an unknown reward/condition preset `kind`, an undeclared param key, a missing required param,
  a non-numeric number, or a reward/condition block passed as a string instead of an object;
- a prerequisite / mutual exclusion / link that names a focus that does not exist — inside a
  batch, forward references to focuses created later in the same batch are fine (checked at the
  end; a still-missing id rolls the whole batch back);
- a filter that isn't a `FOCUS_FILTER_*` token (non-standard ones are allowed but warn);
- an icon that does not resolve, when icon roots are configured (otherwise a `note` says it
  wasn't verified).

### Inline issues

Every successful focus write returns `issues: [{severity, code, message}]` — the validation
issues touching the edited focus(es), including cycle / unreachable issues that mention them.
`apply_batch` returns the deduped `issues` across every touched focus plus
`summary: {errors, warnings}`. Fix every error before moving on.

Tip: `get_focus` shows the JSON shape for `completionReward` / `available`; `list_reward_presets`
and `list_condition_presets` give the valid effect/condition `kind`s and their params.
`search_icons` searches the real sprite index (from your configured icon roots), so the agent
can verify a `GFX_` icon name resolves before assigning it. `add_focus` also accepts
`place_below=<focus_id>` to drop a new focus in the nearest free cell under an existing one
(placement only — prerequisites stay explicit).

### Batching

`apply_batch` runs a list of ops **atomically**: all-or-nothing, one canvas repaint, and a
**single undo step** — so an agent-built 20-focus branch disappears with one Ctrl+Z instead of
twenty. If any op fails, nothing is applied and the error names the failing op. IO ops
(`open_project`, `save_project`, `export_mod`) can't be batched.

## Safety

- **Opt-in**: bridge is off until you enable it; the choice persists per session.
- **Loopback-only**: binds `127.0.0.1`, never a public interface.
- **Your work is protected**: agent edits mark the project dirty, so closing still prompts to save.
- Turn the bridge off and the tools fail cleanly ("AI Bridge is off").
