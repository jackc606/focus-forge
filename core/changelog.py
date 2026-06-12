"""Dev log / changelog — single source of truth for the in-app release history.

Newest first. Shown by the Dev Log dialog when the user clicks the version label
in the status bar. Keep entries short and player-facing (what changed for them),
not commit-level detail.
"""
from __future__ import annotations

# [{version, date (YYYY-MM-DD), title, changes: [str, …]}, …] — newest first.
CHANGELOG = [
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
