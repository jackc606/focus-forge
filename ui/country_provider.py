"""App-wide provider of a country's MD STARTING politics (popularities + ruling
party), for auto-filling the Country editor's Politics tab.

Mirrors state_provider: same data roots as the icon provider, lazy + cached per
country tag, cleared when the icon roots change.
"""
from __future__ import annotations

from PySide6.QtCore import QObject

from core.country_history import parse_starting_politics

from .icon_provider import provider as icon_provider


class CountryProvider(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._by_tag: dict = {}
        icon_provider().changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._by_tag = {}

    def starting_politics(self, tag: str):
        """MD starting-politics dict for the tag (or None); cached per tag."""
        t = (tag or "").strip().upper()
        if not t:
            return None
        if t not in self._by_tag:
            self._by_tag[t] = parse_starting_politics(icon_provider().roots(), t)
        return self._by_tag[t]


_INSTANCE = None


def country_provider() -> CountryProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CountryProvider()
    return _INSTANCE
