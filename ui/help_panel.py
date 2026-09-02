"""Right-tab: searchable, categorized in-app help.

Built for someone who has never modded HOI4 before: a step-by-step quick start
sits at the top, every other topic is a collapsed plain-English question that
expands on click, and troubleshooting is written as problem → fix. Searching
expands whatever matches.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import theme as T
from .widgets import ClickableFrame, hint, panel_header, section_header

QUICK_START_TITLE = "Your first mod in 6 steps"
QUICK_START_BODY = """\
1.  Point Focus Forge at your game.
    Settings tab → In-game Icons → Auto-detect. This finds Hearts of Iron IV
    and Millennium Dawn in your Steam folders, so you get real icons,
    portraits, flags and dropdowns everywhere.

2.  Create your mod.
    Toolbar → New Submod. Name it and pick your country — use the real HOI4
    tag (Libya is LBA, not LBY). That's the whole setup.

3.  Add focuses.
    Click +Focus, or right-click the canvas → New Focus Here. With a focus
    selected, fill in its title, icon and rewards in the Inspector — the
    panel on the right.

4.  Connect them.
    Drag the dot at the bottom of a focus onto another focus: that draws the
    line and makes the first one a requirement. Drop the dot on empty canvas
    to spawn a new, already-connected focus.

5.  Check your work.
    The Validation tab lists anything that would break in-game, in plain
    English. Click an issue to jump straight to the focus.

6.  Publish.
    Toolbar → Export to Mod. Your mod appears in the HOI4 launcher — enable
    it alongside Millennium Dawn and play.

Repeat steps 3-6 as you build. Save often (Ctrl+S): saving keeps your
project file, exporting publishes the mod — they are two different things."""

# [(category, [(title, body), …]), …]
HELP_TOPICS = [
    ("Building the focus tree", [
        ("How do I add a focus?",
         "Click +Focus in the toolbar, or right-click anywhere on the canvas and "
         "pick New Focus Here.\n\n"
         "New focuses get an id starting with your country tag (LBA_…) — that's "
         "the HOI4 convention, and it stops your ids colliding with other mods."),
        ("How do I make one focus require another?",
         "Hover a focus — a dot appears at its bottom edge.\n\n"
         "1. Drag that dot onto another focus: it becomes available only after "
         "the first one is done (a 'prerequisite').\n"
         "2. Or drag the dot onto empty canvas: a new focus is created already "
         "connected.\n\n"
         "You can also manage prerequisites as a list in the Inspector. To remove "
         "a connection, right-click the line between the focuses."),
        ("How do I make an either/or choice?",
         "In the Inspector, add the other focus under Mutually Exclusive — "
         "picking one in-game permanently locks the other.\n\n"
         "The canvas shows mutually-exclusive focuses joined by a red link. Put "
         "them side by side on the same row so players read them as a choice."),
        ("How do I pick a focus icon?",
         "Inspector → Icon → Browse… opens a searchable visual grid of every "
         "icon in the game and Millennium Dawn.\n\n"
         "Have your own artwork? Import… takes a .png/.tga/.dds, scales it to "
         "the in-game size (100×88) and generates all the game files for it on "
         "export — including the shine animation. The × button removes a custom "
         "icon again."),
        ("How do I move focuses around?",
         "Just drag them — they snap to the grid. The in-game tree uses the same "
         "layout you see on the canvas: connected focuses flow top-down, one row "
         "per step.\n\n"
         "You can also type exact grid coordinates in the Inspector's Position "
         "fields."),
        ("How do I delete a focus?",
         "Select it and press Delete, or right-click it → Delete Focus. You can "
         "rubber-band-select several and delete them together.\n\n"
         "Focus Forge cleans up after deletions: anything that required or "
         "excluded the deleted focus has that reference removed for you."),
        ("Can I undo a mistake?",
         "Yes — Ctrl+Z undoes, Ctrl+Y (or Ctrl+Shift+Z) redoes, up to 50 steps. "
         "The toolbar has Undo / Redo buttons too.\n\n"
         "A burst of quick edits (like typing a title) counts as ONE step, so "
         "undo takes you back gesture by gesture, not letter by letter. Inside "
         "a text box, Ctrl+Z edits just that text as usual."),
        ("How do I copy or duplicate focuses?",
         "Select focuses on the canvas (click, or drag a box around a branch), "
         "then:\n\n"
         "• Ctrl+C / Ctrl+V — copy and paste (works across projects: copy in "
         "one window, paste in another)\n"
         "• Ctrl+D — duplicate in place\n\n"
         "Pasted focuses get fresh ids automatically, keep the links BETWEEN "
         "the copied focuses, and land one grid cell down-right of the "
         "originals."),
    ]),
    ("Rewards & conditions", [
        ("How do I give rewards when a focus completes?",
         "Select the focus → Inspector → Completion Reward.\n\n"
         "The quick fields (Political Power, Stability, Army XP…) cover the "
         "common cases. For everything else, open the Add reward… dropdown — "
         "it's grouped (Ideas, State and Material, Diplomacy and War, Millennium "
         "Dawn Economy…) and every entry explains itself when you hover it.\n\n"
         "Each reward you add becomes a small card with its own fields, like "
         "which state gets a building, or which country gets a wargoal."),
        ("How do I control when a focus can be taken?",
         "Inspector → Availability. Add conditions the same way you add rewards "
         "— from a grouped dropdown (government, date, GDP, at war, controls a "
         "state, has a technology…).\n\n"
         "All conditions must be true at once for the focus to be selectable "
         "in-game."),
        ("Can a focus be skipped automatically?",
         "Yes — that's the Bypass section under Availability.\n\n"
         "If the bypass conditions are met, the game marks the focus complete "
         "WITHOUT the player taking it or spending the days. Classic example: a "
         "'Join NATO' focus that bypasses if you're already a member, so the "
         "branch behind it isn't blocked."),
        ("What does AI Priority do?",
         "It's how strongly the AI wants this focus when it plays your country "
         "(HOI4's ai_will_do).\n\n"
         "The default is 10. Raise it to make the AI rush a focus, lower it to "
         "make it a late pick, 0 to make the AI avoid it entirely. Players are "
         "unaffected — this only steers the AI."),
        ("Can I write raw HOI4 script?",
         "Yes. Tick “Show raw script && generated blocks” at the top of the "
         "Inspector.\n\n"
         "Every reward and availability section gains a raw-lines box — anything "
         "you type there is exported verbatim, and the preview underneath shows "
         "exactly what the exported block will look like. Great for MD effects "
         "we don't have a picker for yet."),
        ("Why is my Political Power reward not working?",
         "A negative Political Power reward spends PP on completion, but it "
         "can't go below 0 — the game just takes what's there.\n\n"
         "If you want the player to NEED the PP first, also add the 'Political "
         "power above' availability condition."),
    ]),
    ("Ideas, events & decisions", [
        ("How do I create a national spirit (idea)?",
         "Two ways:\n\n"
         "1. While editing a focus reward: Add reward → “✎ New Idea…” creates "
         "the idea and grants it from that focus in one go.\n"
         "2. Toolbar → Ideas → New… to author one on its own.\n\n"
         "The modifier dropdown is searchable and grouped — about a thousand MD "
         "and vanilla modifiers — and you pick the icon from MD's own set."),
        ("How do I create an event?",
         "Toolbar → Events → New…. Give it a title, a picture (visual grid or "
         "import your own), and one or more option buttons.\n\n"
         "Each option can have its own effects — the same picker as focus "
         "rewards — plus an optional condition for when that option shows, and "
         "an AI weighting. The preview at the bottom shows the generated script "
         "live."),
        ("How do I fire an event from a focus?",
         "In the focus's reward: Add reward → Country Event (or News Event for "
         "the world-news popup), then pick your event from the dropdown.\n\n"
         "Add Delay Days if it should arrive a little after the focus finishes — "
         "great for consequences that shouldn't feel instant."),
        ("Can an event fire on an exact date?",
         "Yes. In the event editor, tick “Fire on exact date” and enter it as "
         "year.month.day — e.g. 2003.3.20.\n\n"
         "It lands exactly once, on that date, for your country. Focus Forge "
         "generates all the HOI4 plumbing for this on export; the Events list "
         "shows 'fires 2003.3.20' so scheduled events are easy to spot."),
        ("How do I create a decision?",
         "Toolbar → Decisions → New…. A decision needs:\n\n"
         "1. A title and an icon (visual grid of every decision icon).\n"
         "2. A category — the tab it appears under in-game. Pick one of MD's "
         "existing categories, or click New category… to make your own tab "
         "with its own icon and visibility rules.\n"
         "3. What it does — the On select effect, using the same picker as "
         "focus rewards.\n\n"
         "Cost is in political power. Visible/Available conditions work like "
         "focus availability."),
        ("How do I make a timed decision or a mission?",
         "In the decision editor's Timers & missions section:\n\n"
         "• Active timer (days_remove): the decision runs for N days, applying "
         "the 'Modifiers while active', then the Remove effect fires. Great "
         "for 'reform underway' style decisions.\n"
         "• Cooldown (days_re_enable): how long before it can be taken again.\n"
         "• Mission countdown: shows as a mission with a deadline — if it "
         "expires, the Timeout effect fires. Use the tint to color it as a "
         "goal (green) or a threat (red).\n\n"
         "Anything fancier (targeted decisions, map highlights, custom cost "
         "text) goes in Raw decision fields and is exported verbatim."),
        ("What happens if I rename an idea or event?",
         "Nothing breaks. Renaming an idea or event id automatically rewrites "
         "every focus reward that referenced it.\n\n"
         "Deleting is also safe: you're warned if focuses still reference it, "
         "and Validation flags any leftover dangling references."),
    ]),
    ("Country editor", [
        ("Politics: starting parties and popularity",
         "Toolbar → Country → Politics. It auto-fills your country's REAL "
         "Millennium Dawn starting popularities and ruling party (badged "
         "“in power”).\n\n"
         "Adjust freely — keep the popularities summing to about 100% — and "
         "“Load MD starting values” resets if you want to start over. “Load MD "
         "parties” pulls in the country's existing party names and logos to "
         "tweak."),
        ("Leaders and portraits",
         "Choose… shows your country's actual MD leader portraits; traits are "
         "searchable by category and show their bonuses on hover.\n\n"
         "Importing a custom portrait: use a 156×210 image (.png/.dds) — the "
         "export generates the sprite files for you. You can then put any "
         "leader in power from a focus with the “Put Leader in Power” reward."),
        ("Flags",
         "The preview shows MD's current flag for your tag. Import a custom one "
         "as an 82×52 image (.tga/.png/.dds) — it's converted and scaled to all "
         "three in-game sizes on export. Leave it unset to keep MD's flag. You "
         "can also set per-ideology variant flags."),
    ]),
    ("Checking & publishing", [
        ("What does Validation catch?",
         "Anything that would break or look wrong in-game, including:\n\n"
         "• broken links — missing prerequisites, cycles, dangling references\n"
         "• focuses placed on top of each other, or above their prerequisite\n"
         "• rewards pointing at ideas/events that don't exist or aren't exported\n"
         "• icons that don't resolve in your configured game folders\n"
         "• empty metadata the export needs (tree id, localisation prefix…)\n\n"
         "Errors (red) will likely break the mod; warnings (amber) are worth a "
         "look. Click any issue to jump to the focus it's about."),
        ("How do I publish and test my mod?",
         "1. Toolbar → Export to Mod. If there are validation errors, you'll "
         "see them listed first and can cancel.\n"
         "2. Open the HOI4 launcher → Playsets — your mod is already there. "
         "Enable it together with Millennium Dawn (your mod BELOW MD in the "
         "load order).\n"
         "3. Start a game as your country and open the focus tree.\n\n"
         "Quick testing tip: in-game, open the console with ` (backtick) and "
         "use  focus.nochecks  to take focuses instantly, or  focus.autocomplete "
         " to finish them in one day. Console only works in non-Ironman games."),
        ("How balanced is my tree?",
         "The Stats tab gives you the numbers a player would feel:\n\n"
         "• how many real-time days the longest branch takes\n"
         "• total political power granted vs. spent by your rewards\n"
         "• branch sizes, depth, and focuses that have no reward yet\n\n"
         "Rule of thumb: MD trees run 35-70 days per focus, and a branch over "
         "~2 in-game years should be worth the wait."),
        ("Where do my files actually go?",
         "Save / Save As writes ONE file — your editable project "
         "(.focusforge.json). Keep it; it's your source.\n\n"
         "Export to Mod writes the actual game files (focus tree, localisation, "
         "ideas, events, country history, flags, icons) into your HOI4 mod "
         "folder. The first export also creates the mod's descriptor so the "
         "launcher can see it."),
    ]),
    ("Fixing common problems", [
        ("My tree doesn't show up in-game",
         "Check these, in order:\n\n"
         "1. Did you Export to Mod (not just Save)? They're separate.\n"
         "2. Is the mod enabled in the launcher playset, alongside Millennium "
         "Dawn?\n"
         "3. Is your country tag the real HOI4 tag? Libya is LBA, not LBY — "
         "with the wrong tag the tree attaches to a country that doesn't exist.\n"
         "4. Started a NEW game? Some changes don't apply to an existing save."),
        ("Icons show as 4-letter codes",
         "Focus Forge can't find your game folders, so it draws placeholder "
         "abbreviations instead of real icons.\n\n"
         "Settings tab → In-game Icons → Auto-detect (or Add Folder… and pick "
         "your Hearts of Iron IV install and the Millennium Dawn workshop "
         "folder). Everything refreshes once they're set."),
        ("My event never fires",
         "Event ids must start with your localisation prefix — e.g. prefix "
         "LBA_forge means events are LBA_forge.1, LBA_forge.2, …\n\n"
         "The event editor suggests correct ids automatically, so this mostly "
         "bites hand-renamed events. Validation flags it either way. Also check "
         "the focus that fires it is actually completable!"),
        ("I play the Millennium Dawn BETA, not the main mod",
         "Focus Forge supports both. They are separate Workshop mods: the beta "
         "has a different dependency name, targets a newer HOI4 version, and "
         "renamed or removed a few scripted effects.\n\n"
         "Pick the edition when you create a submod (New Submod → Millennium "
         "Dawn edition), or change it any time in Settings → Millennium Dawn "
         "Edition. Focus Forge then reads icons, parties and techs from that "
         "edition's folder and writes the matching descriptor and effects on "
         "export.\n\n"
         "A mod built for one edition won't load cleanly under the other — "
         "keep separate submods if you play both."),
        ("Millennium Dawn has no tree for my country",
         "Lots of countries (Mexico, Morocco, Portugal…) just use MD's generic "
         "tree.\n\n"
         "Toolbar → Import Tree → “Start from Generic Tree” gives you an "
         "editable copy of it under your tag — replace it branch by branch."),
        ("I changed things but the game looks the same",
         "Export again, and start a new game. Saving the project does not "
         "update the mod files — only Export to Mod does."),
        ("Did I lose work?",
         "Probably not. The title bar shows a * whenever you have unsaved "
         "changes, closing the app asks first, and autosave (Settings → "
         "Autosave) can save every few minutes once the project has a file. "
         "Saves are also crash-safe — an interrupted save can't corrupt your "
         "project."),
    ]),
    ("Using AI to build your tree", [
        ("What the AI Bridge does",
         "It lets an AI assistant (like Claude) build and edit your focus tree FOR you. You ask in "
         "plain English — e.g. 'add a 4-focus economy branch under my political opening' — and the "
         "focuses, ideas, and events appear on the canvas as the AI works. You stay in control: "
         "undo (Ctrl+Z), tweak, or delete anything afterward, and nothing is saved to disk "
         "until you save."),
        ("Setup if you installed Focus Forge (easiest)",
         "If you used the Focus Forge installer, everything you need is already included — no "
         "Python, no commands. Just three clicks:\n\n"
         "1. In Focus Forge, click 'AI Bridge' on the right of the toolbar — the pill at the "
         "bottom-right turns green ('AI Bridge: on').\n"
         "2. Open the Focus Forge install folder in Claude Code. It finds the bundled setup and "
         "offers to connect a server called 'focusforge'.\n"
         "3. Approve it. Done — skip to 'Now just ask' below.\n\n"
         "(Using Claude Desktop instead? See docs/MCP.md for the one-line config — point it at "
         "focusforge-mcp.exe in the install folder.)"),
        ("Setup if you run from source (Python)",
         "Only if you run Focus Forge from the source folder instead of the installer:\n\n"
         "1. Install Python from python.org and TICK 'Add Python to PATH'.\n"
         "2. Open the Focus Forge folder in File Explorer, click the address bar, type  cmd  and "
         "press Enter (a command window opens in the folder).\n"
         "3. Type this and press Enter:\n\n"
         "        pip install mcp\n\n"
         "4. Turn on the bridge (toolbar 'AI Bridge'), then start Claude Code in the folder and "
         "approve the 'focusforge' server."),
        ("Now just ask",
         "With the bridge ON (green pill) and your AI connected, talk to it normally: 'list my "
         "focuses', 'add a war-economy branch with 3 focuses and a mutually-exclusive choice', "
         "'check the tree for errors'. Watch the canvas update live. Tip: tell the AI to 'read the "
         "MD focus guide first' so it follows Millennium Dawn conventions for costs, icons, filters."),
        ("If it won't connect",
         "• The AI says it can't reach Focus Forge → make sure Focus Forge is open and the "
         "'AI Bridge' pill is green.\n"
         "• Claude Code doesn't list 'focusforge' → start it from inside the Focus Forge folder "
         "(installed app: the folder with FocusForge.exe; source: the folder with main.py).\n"
         "• Running from source and 'pip is not recognized' → Python isn't installed, or 'Add "
         "Python to PATH' wasn't ticked. Reinstall from python.org with that box ticked.\n"
         "• Still stuck → docs/MCP.md has the full walkthrough and the list of things the AI can do."),
        ("Turning it off & staying safe",
         "Click 'AI Bridge' again to stop listening. The bridge is off by default and only works "
         "on your own computer — it never goes online. While it's on, each connection must present "
         "a one-time secret that only your own machine's tools can read, so a random program or web "
         "page can't drive it. An AI can't touch your project unless the bridge is on, and anything "
         "it changes counts as unsaved, so closing Focus Forge still asks you to save first — your "
         "work is protected."),
    ]),
]


class _HelpCard(QFrame):
    """One collapsible topic: a clickable question row that reveals the answer."""

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.setObjectName("helpCard")
        self._title_text = title
        self._body_text = body
        # Tracked explicitly — isVisible() is False whenever an ancestor is
        # hidden (other tab active), which would make toggle() one-way.
        self._expanded = False

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_SM)
        v.setSpacing(T.SPACE_XS)

        head = ClickableFrame()
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T.SPACE_SM)
        self._chevron = QLabel("+")
        self._chevron.setObjectName("helpChevron")
        self._chevron.setFixedWidth(14)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("helpTitle")
        title_lbl.setWordWrap(True)
        row.addWidget(self._chevron)
        row.addWidget(title_lbl, 1)
        v.addWidget(head)

        self._body = QLabel(body)
        self._body.setObjectName("helpBody")
        self._body.setWordWrap(True)
        # Plain text so numbered steps and indented commands render literally,
        # and selectable so users can copy commands straight out.
        self._body.setTextFormat(Qt.PlainText)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setVisible(False)
        v.addWidget(self._body)

        head.clicked.connect(self.toggle)

    def matches(self, query: str) -> bool:
        return query in self._title_text.lower() or query in self._body_text.lower()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._chevron.setText("–" if expanded else "+")

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)


def _quick_start_card() -> QFrame:
    card = QFrame()
    card.setObjectName("helpQuickStart")
    v = QVBoxLayout(card)
    v.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_MD)
    v.setSpacing(T.SPACE_XS)
    t = QLabel(QUICK_START_TITLE)
    t.setObjectName("helpTitle")
    b = QLabel(QUICK_START_BODY)
    b.setObjectName("helpBody")
    b.setWordWrap(True)
    b.setTextFormat(Qt.PlainText)
    b.setTextInteractionFlags(Qt.TextSelectableByMouse)
    v.addWidget(t)
    v.addWidget(b)
    return card


class HelpPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        holder = QWidget()
        scroll.setWidget(holder)
        v = QVBoxLayout(holder)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Help"))
        v.addWidget(hint("New here? Follow the quick start below. Click any question "
                         "to expand it, or search to jump straight to a topic."))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search help — try “icon”, “event”, “export”…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        v.addWidget(self._search)

        self._quick_start = _quick_start_card()
        v.addWidget(self._quick_start)

        self._sections = []  # [(header_label, [cards])]
        for category, topics in HELP_TOPICS:
            header = section_header(category)
            v.addWidget(header)
            cards = []
            for title, body in topics:
                card = _HelpCard(title, body)
                v.addWidget(card)
                cards.append(card)
            self._sections.append((header, cards))
        v.addStretch(1)

    def _filter(self, text: str) -> None:
        q = (text or "").strip().lower()
        qs_match = (not q) or q in QUICK_START_TITLE.lower() or q in QUICK_START_BODY.lower()
        self._quick_start.setVisible(qs_match)
        for header, cards in self._sections:
            visible_any = False
            for card in cards:
                match = (not q) or card.matches(q)
                card.setVisible(match)
                # Searching opens the matches; clearing folds everything back up.
                card.set_expanded(bool(q) and match)
                visible_any = visible_any or match
            header.setVisible(visible_any)
