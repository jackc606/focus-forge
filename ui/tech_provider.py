"""App-wide provider of MD technologies grouped by research folder, for the
"Has technology" availability dropdown. Mirrors state_provider/icon_provider."""
from __future__ import annotations

from PySide6.QtCore import QObject

from core.decision_index import build_decision_categories
from core.modifier_index import build_modifier_groups, build_modifier_tooltips
import threading

from core.tech_index import (
    build_building_list,
    build_building_types,
    build_known_idea_ids,
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
        self._idea_mod_tooltips = None
        self._decision_categories = None
        self._known_idea_ids = None
        self._idea_ids_building = False
        # Script-token indexes for validation (see core.script_index); each is
        # None until its background build lands.
        self._script_index = {"vocab": None, "states": None, "equipment": None, "archetypes": None}
        self._script_building: set = set()
        icon_provider().roots_changed.connect(self._invalidate)

    def _invalidate(self) -> None:
        from core.script_index import clear_script_index_cache
        clear_script_index_cache()
        self._script_index = {"vocab": None, "states": None, "equipment": None, "archetypes": None}
        self._script_building = set()
        self._groups = None
        self._categories = None
        self._buildings = None
        self._building_list = None
        self._opinion_mods = None
        self._idea_mod_groups = None
        self._idea_mod_tooltips = None
        self._decision_categories = None
        self._known_idea_ids = None
        self._idea_ids_building = False

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

    def idea_modifier_tooltips(self) -> dict:
        """{modifier_name(lower): hover tooltip} from the game's MODIFIER_*
        localisation; cached. Empty if no game files are configured."""
        if self._idea_mod_tooltips is None:
            self._idea_mod_tooltips = build_modifier_tooltips(icon_provider().roots())
        return self._idea_mod_tooltips

    def md_decision_categories(self) -> list:
        """Existing decision-category ids from the configured roots; cached."""
        if self._decision_categories is None:
            self._decision_categories = build_decision_categories(icon_provider().roots())
        return self._decision_categories

    def md_decision_categories_cached(self):
        """The cached list, or None if it hasn't been built yet — for callers
        (validation) that must never trigger a blocking scan."""
        return self._decision_categories

    def known_idea_ids_cached(self):
        """Set of game/MD idea ids, or None while unknown. Self-warming: the
        first call kicks a background scan of common/ideas; validation simply
        skips the base-mod check until the set lands (never blocks)."""
        if self._known_idea_ids is None and not self._idea_ids_building:
            self._idea_ids_building = True
            roots = list(icon_provider().roots())

            def _build() -> None:
                try:
                    ids = build_known_idea_ids(roots)
                except Exception:
                    ids = set()
                self._known_idea_ids = ids
                self._idea_ids_building = False

            threading.Thread(target=_build, daemon=True,
                             name="idea-id-index").start()
        return self._known_idea_ids

    def _script_index_cached(self, which: str):
        """Self-warming background build of one core.script_index index
        ('vocab' | 'states' | 'equipment'); None until it lands."""
        if self._script_index.get(which) is None and which not in self._script_building:
            self._script_building.add(which)
            roots = list(icon_provider().roots())
            from core.script_index import (build_equipment_archetypes, build_equipment_types,
                                           build_script_vocabulary, build_state_index)
            builder = {"vocab": build_script_vocabulary, "states": build_state_index,
                       "equipment": build_equipment_types,
                       "archetypes": build_equipment_archetypes}[which]

            def _build() -> None:
                try:
                    result = builder(roots)
                except Exception:
                    result = None
                self._script_index[which] = result if result is not None else {}
                self._script_building.discard(which)

            threading.Thread(target=_build, daemon=True, name=f"script-index-{which}").start()
        val = self._script_index.get(which)
        # An empty index (no roots / nothing found) must not produce a wall of
        # "unknown" warnings — treat it as "not available".
        return val if val else None

    def script_vocabulary_cached(self):
        return self._script_index_cached("vocab")

    def state_index_cached(self):
        return self._script_index_cached("states")

    def equipment_types_cached(self):
        return self._script_index_cached("equipment")

    def equipment_archetypes_cached(self):
        """Archetype names for pickers (list), or None while building/unavailable."""
        val = self._script_index_cached("archetypes")
        return list(val) if val else None


_INSTANCE = None


def tech_provider() -> TechProvider:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = TechProvider()
    return _INSTANCE
