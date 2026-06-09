"""Dev log / changelog — single source of truth for the in-app release history.

Newest first. Shown by the Dev Log dialog when the user clicks the version label
in the status bar. Keep entries short and player-facing (what changed for them),
not commit-level detail.
"""
from __future__ import annotations

# [{version, date (YYYY-MM-DD), title, changes: [str, …]}, …] — newest first.
CHANGELOG = [
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
