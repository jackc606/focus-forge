"""Prompt building for assistant-generated focus icons — Qt-free.

Why a fixed template: the wording was tuned by hand against
``microsoft/mai-image-2.6-flash`` until it reliably produced on-style HOI4 /
Millennium Dawn focus art on a flat magenta key. The model calling
``generate_icons`` only supplies the *subject* (one or two concrete objects);
palette and accent are looked up from the focus's filters and the project's
country tag so every icon in a branch shares one look.
"""
from __future__ import annotations

ICON_PROMPT_TEMPLATE = """\
A national focus icon in the style of Hearts of Iron IV and the Millennium Dawn mod.

Only {OBJECT_COUNT} object(s) and nothing else: {SUBJECT}. No background scenery of any kind:
no buildings behind, no landscape, no ground plane, no sky detail, no people, no motion lines.
The subject forms one compact, roughly square silhouette that fills about 80 percent of the
canvas, centered, with nothing touching the edges.

Single emblem, no frame, no laurels, no border, no circle, no shield, no text, no letters,
no numbers.

Style: semi-realistic painted illustration with clean dark outlines, flat shading with one soft
light from the upper left, exaggerated chunky proportions the way small game icons are drawn,
muted desaturated palette ({PALETTE}, one accent of {ACCENT}), slight grain. It must read
clearly at 100 by 88 pixels: strong silhouette, no fine detail, no thin lines.

Plain solid flat background in pure magenta (#FF00FF) for keying: no gradient, no shadow on
the background, no vignette, no ground shadow.

Square image, 1024 by 1024.
"""

PALETTES = {
    "economy": "steel grey, faded navy, warm concrete tan",
    "military": "olive drab, gunmetal, dust",
    "politics": "parchment, maroon, dark wood",
    "research": "slate blue, brass, white",
}
PALETTES["default"] = PALETTES["economy"]

# Starter set of flag-colour accents; anything else falls back to a phrase the
# image model resolves itself.
ACCENTS = {
    "MEX": "Mexican green", "USA": "flag red", "GER": "black", "FRA": "tricolour blue",
    "ENG": "royal blue", "RUS": "deep red", "CHI": "red", "BRA": "green and yellow",
    "ARG": "sky blue", "EGY": "red", "TUR": "red", "NIG": "green", "JAP": "red",
    "IND": "saffron", "SAU": "green", "ISR": "blue", "CAN": "red", "ITA": "green",
    "SPA": "red and yellow", "POL": "red",
}
FALLBACK_ACCENT = "the country's flag colour"

_MILITARY_FILTERS = ("ARMY", "NAVY", "AIRCRAFT", "EQUIPMENT", "MILITARY_LAWS")
_POLITICS_FILTERS = ("POLITICAL", "DIPLOMACY", "FOREIGN_POLICY")


def _filter_key(name: str) -> str:
    """``FOCUS_FILTER_ARMY`` -> ``ARMY`` (case-insensitive; a bare key passes through)."""
    key = str(name or "").strip().upper()
    prefix = "FOCUS_FILTER_"
    return key[len(prefix):] if key.startswith(prefix) else key


def theme_for_filters(filters) -> str:
    """The palette key for a focus's ``FOCUS_FILTER_*`` list. First match wins in
    the order the filters are given, so a focus tagged POLITICAL + ARMY reads as
    politics — the leading filter is the one modders treat as the theme."""
    for name in filters or []:
        key = _filter_key(name)
        if key in _MILITARY_FILTERS:
            return "military"
        if key in _POLITICS_FILTERS or key.startswith("INTERNAL_"):
            return "politics"
        if key == "RESEARCH":
            return "research"
    return "economy"


def palette_for(theme) -> str:
    return PALETTES.get(str(theme or "").strip().lower(), PALETTES["default"])


def accent_for(country_tag) -> str:
    return ACCENTS.get(str(country_tag or "").strip().upper(), FALLBACK_ACCENT)


def build_icon_prompt(subject: str, *, object_count: int = 2, palette: str,
                      accent: str) -> str:
    """Fill the template. ``object_count`` is clamped to 1..2 because three or
    more objects never read at 100×88; ``subject`` is collapsed to one clean
    sentence so a stray newline from the model can't break the prompt."""
    try:
        count = int(object_count)
    except (TypeError, ValueError):
        count = 2
    count = max(1, min(2, count))
    text = " ".join(str(subject or "").split()).strip().rstrip(".")
    return ICON_PROMPT_TEMPLATE.format(OBJECT_COUNT=count, SUBJECT=text,
                                       PALETTE=palette, ACCENT=accent)


def default_subject(focus) -> str:
    """Fallback subject when the model omits one: the title plus the first
    sentence of the description. The model is expected to pass a concrete
    subject ("a control tower and a passenger jet"); this only keeps the op
    usable when it doesn't."""
    title = " ".join(str(getattr(focus, "title", "") or "").split())
    desc = " ".join(str(getattr(focus, "description", "") or "").split())
    first = desc.split(". ")[0].rstrip(".") if desc else ""
    if title and first:
        return f"{title}: {first}"
    return title or first or str(getattr(focus, "id", "") or "a national focus")
