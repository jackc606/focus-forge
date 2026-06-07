"""Design tokens — single source of truth for the 'Refined Command Console' theme.

Both the QSS builder (``ui/style.py``) and the QPainter code
(``graph_background``, ``focus_node_item``, ``edge_item``) import from here so
colors, fonts and spacing never drift between the stylesheet and the canvas.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Palette — cold blue-steel base + one signal-green accent
# ---------------------------------------------------------------------------
BG_BASE = "#0b0e13"        # window / canvas void
BG_PANEL = "#151b24"       # panels, toolbar, tabs
BG_ELEVATED = "#1b2330"    # inputs, cards, node body
BG_INSET = "#0d1117"       # text / preview / list fields
BG_HOVER = "#222c3a"       # hover fill for controls/rows

BORDER_SUBTLE = "#232c38"  # dividers, default borders
BORDER_STRONG = "#33404f"  # input borders, node outline
BORDER_HOVER = "#465465"   # hovered borders / scrollbar handle hover

TEXT_PRIMARY = "#e8edf3"   # titles, body
TEXT_SECONDARY = "#aab4c2"  # labels, secondary
TEXT_MUTED = "#7c8896"     # hints, tertiary
TEXT_DISABLED = "#566273"  # disabled controls

ACCENT = "#4fd08a"         # signal green — selection, focus ring, primary
ACCENT_HOVER = "#63e29d"   # brighter accent (hover)
ACCENT_DIM = "#2f6e4d"     # accent fills / borders
ACCENT_SOFT = "#1d2b22"    # selected list/row tint

# Focus-tree (HOI4 WYSIWYG) — frame brackets + connector lines
FOCUS_FRAME = "#5a6675"      # icon frame border (grey = available, in-game default)
FOCUS_BRACKET = "#9aa6b4"    # corner brackets on the icon frame
FOCUS_PLATE = "#11161f"      # name plate behind the title
PREREQ_LINE = "#6f8aa8"      # prerequisite connector (light steel-blue = incomplete)
MUTEX_LINE = "#c75b5b"       # mutually-exclusive red link
SEARCH_HL = "#f0b54f"        # amber highlight for search matches

STATUS_ERROR = "#f0908f"
STATUS_ERROR_BG = "#2a1517"
STATUS_ERROR_BORDER = "#6d3434"
STATUS_WARN = "#e3bd83"
STATUS_WARN_BG = "#241d12"
STATUS_WARN_BORDER = "#5b4328"
STATUS_OK = "#4fd08a"

# ---------------------------------------------------------------------------
# Typography — distinctive system fonts with graceful fallback chains.
# Bahnschrift (DIN-style industrial grotesque, ships with Win11) for the UI;
# Cascadia Mono (ships with modern Windows) for IDs / coordinates / code.
# ---------------------------------------------------------------------------
FONT_UI = "'Bahnschrift', 'Segoe UI Variable Text', 'Segoe UI', sans-serif"
FONT_MONO = "'Cascadia Mono', 'Cascadia Code', 'Consolas', monospace"

# First-choice families as plain names, for QFont() construction in painters.
FONT_UI_FAMILY = "Bahnschrift"
FONT_MONO_FAMILY = "Cascadia Mono"

# ---------------------------------------------------------------------------
# Scales
# ---------------------------------------------------------------------------
# Spacing (px)
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# Radii (px)
RADIUS_INPUT = 4
RADIUS_CARD = 6
RADIUS_NODE = 8

# Type scale (px)
TEXT_MICRO = 11   # mono ids, meta
TEXT_BODY = 12
TEXT_LABEL = 13
TEXT_TITLE = 15   # section / node title
TEXT_HEADER = 18  # panel header

# Weights
WEIGHT_REGULAR = 400
WEIGHT_SEMIBOLD = 600
WEIGHT_BOLD = 700
