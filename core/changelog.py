"""Dev log / changelog — single source of truth for the in-app release history.

Newest first. Shown by the Dev Log dialog when the user clicks the version label
in the status bar. Keep entries short and player-facing (what changed for them),
not commit-level detail.
"""
from __future__ import annotations

# [{version, date (YYYY-MM-DD), title, changes: [str, …]}, …] — newest first.
CHANGELOG = [
    {
        "version": "0.4.0",
        "date": "2026-09-02",
        "title": "Millennium Dawn Beta support",
        "changes": [
            "Focus Forge now works with the Millennium Dawn BETA as well as "
            "the main mod. Pick the edition when creating a submod, or switch "
            "it any time in Settings → Millennium Dawn Edition; each project "
            "remembers its target.",
            "Exports match the edition: the right dependency name and game "
            "version in descriptor.mod, and the beta's renamed party-popularity "
            "helper. The Radicalization reward (a system the beta removed) is "
            "hidden for beta projects and flagged by validation if a project "
            "still carries one.",
            "Game data follows the edition too — icons, parties, leaders, techs "
            "and importable focus trees are read from the beta's own folder, "
            "found automatically in your Steam library.",
            "Country tag lists are now read from the mod itself instead of a "
            "built-in copy, so new or renamed beta countries show up in every "
            "country picker.",
        ],
    },
    {
        "version": "0.3.4",
        "date": "2026-07-22",
        "title": "Minimap, lineage tracing, and one language for rewards",
        "changes": [
            "Canvas minimap: the whole tree as a constellation in the corner, "
            "with your viewport marked — click or drag it to jump anywhere. "
            "Big trees stop being a scroll marathon.",
            "Hover a focus to light up its entire ancestry — every "
            "prerequisite path back to the roots, OR-groups included. See "
            "what a capstone really demands at a glance.",
            "Structure raw script: convert raw reward script into editable "
            "reward cards — per focus in the inspector, or the whole project "
            "at once from the \"…\" menu (all-or-nothing per focus, so the "
            "exported mod stays identical; one undo restores everything).",
            "Stats and the political-power economy now understand raw-script "
            "rewards too.",
            "Smarter validation: idea references are checked against the "
            "game/MD's real idea list (no more false alarms on base-mod "
            "ideas), and a new structural check catches unbalanced braces or "
            "quotes in raw script before they corrupt an export.",
            "Opening a project shared from another computer now cleans up "
            "machine-specific paths it carried, instead of exporting to a "
            "folder that doesn't exist here.",
            "New in Settings: Copy Diagnostic Report — app, project, and "
            "recent event log in one paste for bug reports — plus an event "
            "log the app keeps automatically.",
            "Fixed a hidden canvas bug that spammed hundreds of paint "
            "warnings every time a big tree was fitted to the window.",
        ],
    },
    {
        "version": "0.3.3",
        "date": "2026-07-21",
        "title": "A cleaner cockpit — redesigned UI, faster big trees, safer exports",
        "changes": [
            "Redesigned inspector: the selected focus shows as a dossier card "
            "— icon in the canvas-style bracket frame, title and id edited in "
            "place, position/cost chips (cost shown in in-game days), and a "
            "live validation dot. The Idea and Event editors open with the "
            "same card.",
            "New command bar: buttons grouped into labeled banks with one "
            "green Export button; rare and destructive commands moved under "
            "\"…\". The toolbar no longer clips off-screen on smaller windows.",
            "Focuses list: every row shows its focus icon, id, and a "
            "validation dot; warnings underneath are clickable and jump "
            "straight to the focus.",
            "Stats tab: headline tiles plus branch-length and reward-mix "
            "charts — see at a glance if your rewards lean too hard on one "
            "effect.",
            "Welcome screen: recent projects are cards with a constellation "
            "thumbnail of each tree's real shape.",
            "Dragging focuses on big trees (500+) is ~3× smoother.",
            "Export safety: exporting one project can no longer overwrite a "
            "different mod's folder — the destination is remembered per "
            "project, a mismatch warns first, and Export As now offers to "
            "create a proper mod folder (descriptor included) so your mod "
            "actually appears in the launcher.",
            "Retitling an existing focus updates its auto-generated id again.",
            "New validation warning when two same-row focuses are close "
            "enough to overlap in-game.",
            "New reward presets: doctrine cost reduction, corruption, "
            "national budget lines, and ideology popularity.",
        ],
    },
    {
        "version": "0.3.2",
        "date": "2026-07-19",
        "title": "Smoother updates, one crash fixed",
        "changes": [
            "Auto-update no longer shows 'Setup was unable to automatically "
            "close all applications': the installer now waits for Focus Forge "
            "to finish closing before it touches any files. (If you see that "
            "message once more while updating TO this version, click Retry — "
            "it's the last time.)",
            "Fixed a repeating crash when a focus listed itself as mutually "
            "exclusive. That's now reported as a normal validation error "
            "instead of crashing the editor.",
        ],
    },
    {
        "version": "0.3.1",
        "date": "2026-07-06",
        "title": "Big update — a full-audit bug sweep plus new authoring tools",
        "changes": [
            "New: focus tree shortcuts — the clickable branch bookmarks big "
            "trees show in the bottom-left in-game. Add them from the "
            "Shortcuts toolbar button or by right-clicking a focus, point each "
            "at a branch, and they export (and re-import) like vanilla MD.",
            "New: author OR-group prerequisites in-app. Prerequisite chips show "
            "a group as 'a | b'; type that to make one, or right-click a "
            "connection to switch it between required (AND) and an OR "
            "alternative (drawn dashed on the canvas).",
            "New: custom leader descriptions, and vanilla MD party descriptions "
            "now load into the Politics tab.",
            "Multi-select works properly now: Ctrl+click to extend, rubber-band "
            "to select a group, then drag, copy, duplicate or delete them all "
            "together. Selections no longer collapse after every edit.",
            "Your work is much harder to lose: Open/Import/New Submod now warn "
            "about unsaved changes, edits typed right before Ctrl+S are saved, "
            "Cancel in the event/decision editors really cancels, and editors "
            "no longer discard an idea or event with a blank ID silently.",
            "Undo is more precise — deleting a focus or connection right after "
            "typing no longer merges both into one undo step.",
            "OR-group prerequisites now survive save and reopen exactly as "
            "authored (repeated focuses across groups were being rewritten).",
            "Export fixes: project names with ':' no longer produce an empty "
            "country file, empty icons can't corrupt the focus block, quotes "
            "in leader names are escaped, and non-Latin leader names no "
            "longer overwrite each other's portraits.",
            "Faster and steadier: the multi-second freeze on the first "
            "dropdown click after opening a project is gone, and a batch of "
            "crash bugs (huge trees, unusual .dds icons, corrupt project "
            "files, quitting with the AI bridge connected) are fixed.",
        ],
    },
    {
        "version": "0.3.0",
        "date": "2026-07-06",
        "title": "Focus Forge now updates itself",
        "changes": [
            "Focus Forge checks for a new version shortly after startup and "
            "offers to download and install it — release notes included, one "
            "click, and it relaunches when done. Downloads are integrity-"
            "checked before they run.",
            "Not now? Choose Later, or Skip this version to stop being asked "
            "about that release. A small notice stays in the status bar so "
            "you can grab it whenever you're ready.",
            "Check on demand from Settings → Updates → Check for Updates.",
        ],
    },
    {
        "version": "0.2.2",
        "date": "2026-06-12",
        "title": "Crash fix: focus prerequisites",
        "changes": [
            "Fixed a crash that could make a project unopenable — opening or "
            "editing it threw an error and the canvas, inspector, and validation "
            "all stopped working. It was caused by a malformed prerequisite link "
            "(most often written by the AI bridge). Affected projects now repair "
            "themselves automatically the next time you open them.",
        ],
    },
    {
        "version": "0.2.1",
        "date": "2026-06-12",
        "title": "Big-tree performance fix",
        "changes": [
            "Large trees (USA, China, and other 700+ focus trees) are now smooth. "
            "The canvas only redraws what actually changes instead of the whole "
            "tree on every hover or click, so editing a big tree no longer crawls.",
            "Opening a large tree no longer freezes while it loads icons — the "
            "focus art now decodes in the background and fills in as it's ready, "
            "and the app stays responsive the whole time.",
        ],
    },
    {
        "version": "0.2.0",
        "date": "2026-06-12",
        "title": "Decisions, undo, and a lot of polish",
        "changes": [
            "Full decision creator — toolbar → Decisions. Author decisions with "
            "cost, timers, cooldowns, missions, visible/available conditions, "
            "complete/remove/timeout effects, active modifiers, AI weighting, and "
            "custom categories. Drop them into your own category or any Millennium "
            "Dawn one. Import a custom decision icon or pick from the in-game grid.",
            "Undo & redo (Ctrl+Z / Ctrl+Y) across everything — up to 50 steps, with "
            "Undo/Redo buttons on the toolbar.",
            "Copy, paste and duplicate focuses (Ctrl+C / V / D). Paste lands where "
            "your cursor is and keeps the branch's layout and internal links; "
            "right-click → Paste Here drops it at an exact spot.",
            "New Stats tab — branch lengths in days, political-power economy, tree "
            "depth and size at a glance.",
            "Add an exact-date or bypass to focuses, set per-focus AI priority, and "
            "a new State Population reward (adds people to one state).",
            "Hover tooltips on every reward and condition, on idea modifiers (from "
            "the game's own text), plus a Common modifier category of the 20 "
            "most-used. Multi-line descriptions now export cleanly.",
            "Smarter validation: it now catches broken availability conditions, "
            "references to missing ideas/events, unresolved icons, and layout slips "
            "— all before you export.",
            "AI Bridge security hardening: every connection now needs a one-time "
            "secret only your own machine can read, so nothing else can drive it.",
            "Saving is crash-safe, big trees stay snappy while typing, and the game "
            "data (icons, techs, states) loads in the background at startup.",
        ],
    },
    {
        "version": "0.1.9",
        "date": "2026-06-12",
        "title": "Reliability, speed & a verified reward catalog",
        "changes": [
            "Every reward and availability preset was audited against Millennium "
            "Dawn's actual files. Fixed: equipment ids that no longer exist in MD, "
            "the Communist-State leader ideology, naval bases/bunkers now take a "
            "province, hydro dams stack instead of overwriting, the government "
            "check gained Nationalist, leader checks now mean 'in power', and "
            "factories grant a free building slot only when MD says they use one.",
            "New rewards: News Event, Puppet Country, Annex Country — and the "
            "interest-group picker is now a dropdown of MD's real helpers.",
            "Dropdown pickers no longer mis-save when you choose a type-ahead "
            "suggestion, and a missing state id is caught by Validation instead "
            "of exporting a broken block.",
            "Saving is now crash-safe: projects and exported mods are written "
            "atomically, so a crash or full disk can never truncate your work. "
            "A damaged project file shows a clear message instead of an error dump.",
            "Much snappier on big projects: typing no longer re-validates and "
            "re-exports the whole project per keystroke, the canvas only "
            "re-routes connectors that actually moved, and the game-data "
            "scans (icons, techs, states, traits) now happen in the background "
            "at startup instead of freezing the first click.",
            "Corrupt or truncated mod files (.dds, .gfx, localisation) can no "
            "longer crash the app or silently mangle accented text.",
        ],
    },
    {
        "version": "0.1.8",
        "date": "2026-06-11",
        "title": "Date-scheduled events & UI polish",
        "changes": [
            "Events can fire on an exact date — tick “Fire on exact date” in the "
            "event editor and give it a year.month.day (e.g. 2003.3.20). It lands "
            "exactly once, on that date, for your country; the export generates "
            "the HOI4 plumbing (date trigger + on_actions file) for you.",
            "The Events manager shows each scheduled event's date, and Validation "
            "flags malformed dates before you export.",
            "UI consistency pass: spacing and sizes unified across every editor "
            "and dialog, empty-state hints in the Ideas/Events managers and the "
            "Validation tab, and Enter opens the selected idea/event.",
            "Scrolling a panel no longer accidentally changes dropdowns or number "
            "fields the cursor happens to pass over.",
            "Smoother canvas on big trees — node fonts and icons are cached "
            "instead of rebuilt every repaint.",
        ],
    },
    {
        "version": "0.1.7",
        "date": "2026-06-10",
        "title": "Custom focus icons",
        "changes": [
            "Import your own focus icon — Inspector → Icon → Import…. The image is "
            "auto-scaled to the in-game 100×88 size and shows on the canvas instantly.",
            "On export the icon is written as a .dds with its sprite definition "
            "generated for you — including the “shine” the game plays when a focus "
            "becomes completable.",
            "× next to Import… removes a custom icon and returns to the named one.",
            "Inspector layout fix: fields no longer get cut off at the right edge.",
        ],
    },
    {
        "version": "0.1.6",
        "date": "2026-06-09",
        "title": "Importers, custom art & an easier AI bridge",
        "changes": [
            "Import a focus tree from any custom mod folder — Import Tree → “Add Mod "
            "Folder…”, which also loads that mod's custom focus icons for the session.",
            "The folder picker now opens straight to your HOI4 mod folder.",
            "Custom event pictures: choose from a visual grid (no more text rows) or "
            "import your own image — exported as a .dds plus its sprite definition.",
            "Imported images now auto-scale to the correct in-game size (party logos "
            "22×22, leader portraits 156×210, event pictures 420×175).",
            "Party-logo import shows the required dimensions and format.",
            "Rewritten AI Bridge help — simpler one-time setup with copy-paste steps.",
            "The AI Bridge is now bundled into the installed app, so it works without a "
            "separate Python install.",
            "Click the version in the bottom-left corner to open this dev log.",
            "Startup launcher: Focus Forge now opens to a New Submod / Open Project / "
            "Recent menu instead of jumping straight into the sample project.",
            "Import a country's existing Millennium Dawn parties (name, logo, "
            "description) into the Country editor with “Load MD parties”.",
            "Parties now have an editable politics-screen description, and warn when two "
            "share the same sub-ideology slot.",
            "Faster icon/picture pickers — thumbnails load only as you scroll.",
            "New submods now import the country's existing MD focus tree by default "
            "(toggle “Start blank” to opt out).",
            "Red “Clear Focuses” toolbar button (with confirmation) wipes the tree.",
            "Autosave: pick an interval in Settings to auto-save the open project.",
            "New reward “Put Leader in Power” — installs a preset MD or custom leader "
            "(create_country_leader) and makes their party rule.",
            "Country flag preview now shows for every country (robust TGA decoder for "
            "the flag formats Qt couldn't read).",
        ],
    },
    {
        "version": "0.1.5",
        "date": "",
        "title": "Earlier releases",
        "changes": [
            "Core editor: visual focus-tree canvas, structured rewards & availability, "
            "ideas, events, the country editor, validation, and byte-identical HOI4 "
            "export — plus the AI Bridge for building trees with an AI assistant.",
        ],
    },
]
