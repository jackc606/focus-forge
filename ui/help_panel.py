"""Right-tab: searchable, categorized in-app help — common features, how-tos,
and gotchas. Static content; no model interaction."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import theme as T
from .widgets import hint, panel_header, section_header

# [(category, [(title, body), …]), …]
HELP_TOPICS = [
    ("Getting started", [
        ("Set up your game folders",
         "Focus Forge auto-detects Hearts of Iron IV and Millennium Dawn from Steam. "
         "If icons, portraits, or pickers are empty, add the folders in "
         "Settings → In-game Icons → Auto-detect / Add Folder."),
        ("New Submod",
         "Toolbar → New Submod creates a project in your Focus Forge workspace and "
         "sets where Export to Mod will publish (your HOI4 mod folder). The mod folder "
         "is scaffolded on first export."),
        ("Import an existing tree",
         "Toolbar → Import Tree loads a country's Millennium Dawn focus tree as an "
         "editable project. For countries MD has no tree for (Mexico, Morocco, …), use "
         "“Start from Generic Tree” in that dialog to seed an editable copy."),
        ("Save vs Export",
         "Save / Save As writes your editable .focusforge.json project. Export to Mod "
         "writes the actual HOI4 files (focus tree, localisation, ideas, country, flags). "
         "They are separate — exporting does not save the project, and vice-versa."),
    ]),
    ("Building the focus tree", [
        ("Add a focus",
         "Toolbar +Focus, or right-click the canvas → New Focus Here. New focus ids are "
         "auto-prefixed with your country tag (e.g. LBA_…)."),
        ("Link prerequisites",
         "Drag from a focus's bottom port onto another focus to make that focus a "
         "prerequisite. Drag the port onto empty space to spawn a connected child."),
        ("Prerequisites / mutually exclusive / filters",
         "Set these in the Inspector — each is a searchable dropdown of the project's "
         "focuses (or the HOI4 search filters)."),
        ("Delete focuses",
         "Select one (or rubber-band several) and press Delete, or right-click a node → "
         "Delete. Prerequisite / mutex references to deleted focuses are cleaned up."),
        ("Right-click menus",
         "Right-click a node, an edge, or empty canvas for context actions: add child, "
         "new focus here, delete focus, delete connection."),
    ]),
    ("Rewards & availability", [
        ("Structured vs raw",
         "Use the reward / availability pickers for structured effects (political power, "
         "state buildings, ideas, opinion modifiers …). Tick “Show raw script & generated "
         "blocks” to hand-write raw HOI4 lines and preview the generated script."),
        ("Political power",
         "A negative Political Power reward consumes PP on completion (it floors at 0). To "
         "require the PP first, add the “Political power above” availability condition."),
        ("Resources",
         "State Resource adds a flat amount to one of your states (permanent). Timed "
         "Resource does the same with a days limit (e.g. 730). HOI4 has no flat country-to-"
         "country resource gift — name the donor in the focus description."),
        ("Opinion modifier",
         "Pick from MD's named opinion modifiers (each shows its value). The amount lives "
         "in the modifier definition, not in the focus."),
    ]),
    ("Ideas", [
        ("Create an idea",
         "In a focus's reward, pick Add reward → “✎ New Idea…”. The modifier dropdown is "
         "searchable and grouped (~1000 MD + vanilla modifiers); choose an idea icon from "
         "MD's set."),
        ("Edit / delete ideas",
         "Toolbar → Ideas lists every idea you've authored — edit or delete them. Renaming "
         "an idea's id automatically updates the focuses that grant it."),
    ]),
    ("Country editor", [
        ("Politics",
         "The Politics tab auto-fills the country's real Millennium Dawn starting "
         "popularities and ruling party (badged “in power”). Adjust freely; “Load MD "
         "starting values” resets. Keep popularities summing to ~100%."),
        ("Leaders",
         "Choose… shows your country's real MD leader portraits. Traits are searchable, "
         "categorized, and show their bonuses on hover. Import a custom portrait at "
         "156×210 px (.dds/.png) — export auto-generates the sprite for it."),
        ("Flags",
         "The preview shows MD's current flag for your tag. Import a custom flag at "
         "82×52 px (.tga/.png/.dds); leave it unset to keep MD's flag."),
    ]),
    ("Validation & export", [
        ("What gets validated",
         "The Validation tab and warnings sidebar flag focus-graph problems (missing "
         "prerequisites, cycles, overlapping positions) AND metadata problems (empty tree "
         "id, export filename, localisation prefix, country settings, event namespace)."),
        ("Export to Mod",
         "One-click after New Submod. If there are validation errors, Export lists them and "
         "asks before proceeding. First export scaffolds the mod folder (descriptor + "
         "folders) so it shows in the HOI4 launcher."),
    ]),
    ("Gotchas", [
        ("Save is not Export",
         "Saving writes the project file; Export writes the mod files. Do both."),
        ("Use the real HOI4 tag",
         "The country tag must be the actual HOI4 tag — e.g. Libya is LBA (not LBY). State, "
         "portrait, and flag lookups all depend on it."),
        ("Event ids need a namespace",
         "Events must be <localisationPrefix>.<n> (e.g. LBA.1) to match the generated "
         "add_namespace, or the game won't find them."),
        ("No MD tree for your country?",
         "Mexico, Morocco, Portugal and many others use the generic tree. Import Tree → "
         "“Start from Generic Tree” seeds an editable copy under your tag."),
        ("Missing icons / portraits",
         "If the canvas shows 4-letter abbreviations or pickers are empty, add your HOI4 + "
         "Millennium Dawn folders in Settings → In-game Icons."),
        ("Unsaved changes",
         "The title bar shows a * when you have unsaved changes, and closing the app "
         "prompts you to save."),
    ]),
]


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
        v.addWidget(hint("Common features, how-tos, and gotchas. Search to jump to a topic."))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search help…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        v.addWidget(self._search)

        self._sections = []  # [(header_label, [card_widgets])]
        for category, topics in HELP_TOPICS:
            header = section_header(category)
            v.addWidget(header)
            cards = []
            for title, body in topics:
                card = self._make_card(title, body)
                v.addWidget(card)
                cards.append(card)
            self._sections.append((header, cards))
        v.addStretch(1)

    @staticmethod
    def _make_card(title: str, body: str) -> QFrame:
        card = QFrame()
        card.setObjectName("helpCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_SM)
        cv.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("helpTitle")
        t.setWordWrap(True)
        b = QLabel(body)
        b.setObjectName("helpBody")
        b.setWordWrap(True)
        cv.addWidget(t)
        cv.addWidget(b)
        card._title = title  # type: ignore[attr-defined]
        card._body = body    # type: ignore[attr-defined]
        return card

    def _filter(self, text: str) -> None:
        q = (text or "").strip().lower()
        for header, cards in self._sections:
            visible_any = False
            for card in cards:
                match = (not q) or q in card._title.lower() or q in card._body.lower()
                card.setVisible(match)
                visible_any = visible_any or match
            header.setVisible(visible_any)
