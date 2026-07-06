"""App-wide provider of a country's MD STARTING politics (popularities + ruling
party), for auto-filling the Country editor's Politics tab.

Mirrors state_provider: same data roots as the icon provider, lazy + cached per
country tag, cleared when the icon roots change.
"""
from __future__ import annotations

from PySide6.QtCore import QObject

from core.country_history import parse_starting_politics
from core.md_leaders import parse_country_leaders
from core.md_parties import parse_country_parties

from .icon_provider import provider as icon_provider


class CountryProvider(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._by_tag: dict = {}
        self._parties_by_tag: dict = {}
        self._leaders_by_tag: dict = {}
        icon_provider().roots_changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._by_tag = {}
        self._parties_by_tag = {}
        self._leaders_by_tag = {}

    def starting_politics(self, tag: str):
        """MD starting-politics dict for the tag (or None); cached per tag."""
        t = (tag or "").strip().upper()
        if not t:
            return None
        if t not in self._by_tag:
            self._by_tag[t] = parse_starting_politics(icon_provider().roots(), t)
        return self._by_tag[t]

    def parties(self, tag: str) -> list:
        """MD party definitions for the tag (name/longName/subIdeology/logoRef/
        description dicts); cached per tag. Empty list if none found."""
        t = (tag or "").strip().upper()
        if not t:
            return []
        if t not in self._parties_by_tag:
            self._parties_by_tag[t] = parse_country_parties(icon_provider().roots(), t)
        return self._parties_by_tag[t]

    def leaders(self, tag: str) -> list:
        """MD preset leaders for the tag ({name, picture, ideology, traits} dicts);
        cached per tag. Empty list if none found."""
        t = (tag or "").strip().upper()
        if not t:
            return []
        if t not in self._leaders_by_tag:
            self._leaders_by_tag[t] = parse_country_leaders(icon_provider().roots(), t)
        return self._leaders_by_tag[t]


_INSTANCE = None


def country_provider() -> CountryProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CountryProvider()
    return _INSTANCE
