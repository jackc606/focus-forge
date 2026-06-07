"""App-wide provider of MD technologies grouped by research folder, for the
"Has technology" availability dropdown. Mirrors state_provider/icon_provider."""
from __future__ import annotations

from PySide6.QtCore import QObject

from core.modifier_index import build_modifier_groups
from core.tech_index import (
    build_building_list,
    build_building_types,
    build_opinion_modifiers,
    build_tech_categories,
    build_tech_groups,
)

from .icon_provider import provider as icon_provider


class TechProvider(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._groups = None
        self._categories = None
        self._buildings = None
        self._building_list = None
        self._opinion_mods = None
        self._idea_mod_groups = None
        icon_provider().changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._groups = None
        self._categories = None
        self._buildings = None
        self._building_list = None
        self._opinion_mods = None
        self._idea_mod_groups = None

    def tech_groups(self) -> list:
        """[(group_label, [(tech_id, display)])]; cached."""
        if self._groups is None:
            self._groups = build_tech_groups(icon_provider().roots())
        return self._groups

    def tech_categories(self) -> list:
        """Sorted CAT_* technology categories (for add_tech_bonus); cached."""
        if self._categories is None:
            self._categories = build_tech_categories(icon_provider().roots())
        return self._categories

    def building_types(self) -> list:
        """Sorted building ids from common/buildings; cached."""
        if self._buildings is None:
            self._buildings = build_building_types(icon_provider().roots())
        return self._buildings

    def buildings(self) -> list:
        """[(building_id, display_name)] with English names; cached."""
        if self._building_list is None:
            self._building_list = build_building_list(icon_provider().roots())
        return self._building_list

    def opinion_modifiers(self) -> list:
        """[(modifier_id, value)] from common/opinion_modifiers; cached."""
        if self._opinion_mods is None:
            self._opinion_mods = build_opinion_modifiers(icon_provider().roots())
        return self._opinion_mods

    def idea_modifier_groups(self) -> list:
        """[(group_label, [modifier_name])] for the idea editor; cached."""
        if self._idea_mod_groups is None:
            self._idea_mod_groups = build_modifier_groups(icon_provider().roots())
        return self._idea_mod_groups


_INSTANCE = None


def tech_provider() -> TechProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = TechProvider()
    return _INSTANCE
