"""App-wide provider of a country's HOI4/MD states for state-scoped rewards.

Uses the same data roots as the icon provider (base game + MD + submods). Builds
the state index lazily, caches the per-country labelled lists, and clears its
cache when the icon roots change.
"""
from __future__ import annotations

from PySide6.QtCore import QObject

from core.state_index import build_state_index, resolve_states

from .icon_provider import provider as icon_provider


class StateProvider(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._index = None
        self._by_tag: dict = {}
        icon_provider().changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._index = None
        self._by_tag = {}

    def states_for_country(self, tag: str) -> list:
        """[(id:int, label:str)] for the country's states; cached per tag."""
        t = (tag or "").strip().upper()
        if not t:
            return []
        if t not in self._by_tag:
            self._by_tag[t] = resolve_states(icon_provider().roots(), t)
        return self._by_tag[t]


_INSTANCE = None


def state_provider() -> StateProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = StateProvider()
    return _INSTANCE
