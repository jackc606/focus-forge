"""App-wide provider of HOI4/MD country-leader traits, grouped (and with bonus
tooltips) for the leader editor's trait picker. Same roots as the icon provider,
lazy + cached, cleared when roots change.
"""
from __future__ import annotations

from PySide6.QtCore import QObject

from core.leader_traits import build_trait_index, format_trait_tooltip, group_traits

from .icon_provider import provider as icon_provider


class TraitProvider(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._index = None
        self._by_tag: dict = {}
        self._tooltips = None
        icon_provider().changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._index = None
        self._by_tag = {}
        self._tooltips = None

    def _get_index(self) -> dict:
        if self._index is None:
            self._index = build_trait_index(icon_provider().roots())
        return self._index

    def trait_groups(self, tag: str) -> list:
        """[(group_label, [trait_id])] for the tag (country traits first); cached."""
        t = (tag or "").strip().upper()
        if t not in self._by_tag:
            self._by_tag[t] = group_traits(self._get_index(), t)
        return self._by_tag[t]

    def trait_tooltips(self) -> dict:
        """{trait_id: bonus tooltip}; cached."""
        if self._tooltips is None:
            self._tooltips = {tid: format_trait_tooltip(tid, e["effects"])
                              for tid, e in self._get_index().items()}
        return self._tooltips


_INSTANCE = None


def trait_provider() -> TraitProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = TraitProvider()
    return _INSTANCE
