"""Background warm-up for the lazy game-data providers.

Each provider builds its caches from the HOI4/MD files on first use — which
lands on the UI thread the first time a dropdown opens (tech picker, building
list, trait chips, …). Warming them on one background thread at startup
removes those first-click freezes. All builders are pure file I/O + parsing;
no Qt GUI objects are touched off-thread.

If the icon roots change mid-warm, the possibly-stale caches are invalidated
so the next lookup rebuilds from the new roots.
"""
from __future__ import annotations

import threading

from .country_provider import country_provider
from .icon_provider import provider as icon_provider
from .state_provider import state_provider
from .tech_provider import tech_provider
from .trait_provider import trait_provider

_thread = None


def warm_game_data_async(country_tag: str = "") -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    roots = icon_provider().roots()
    if not roots:
        return
    tag = (country_tag or "").strip().upper()
    # Construct the singletons on the MAIN thread: a QObject created on the
    # worker would get the worker's (short-lived) thread affinity and its
    # roots-changed signal connection would never deliver.
    tech, traits, states, countries = (
        tech_provider(), trait_provider(), state_provider(), country_provider())

    def build():
        try:
            tech.tech_groups()
            tech.tech_categories()
            tech.buildings()
            tech.building_types()
            tech.opinion_modifiers()
            tech.idea_modifier_groups()
            traits.trait_tooltips()  # builds the trait index too
            if tag:
                traits.trait_groups(tag)
                states.states_for_country(tag)
                countries.starting_politics(tag)
                countries.parties(tag)
                countries.leaders(tag)
        finally:
            if icon_provider().roots() != roots:
                # Roots changed while we were scanning — drop anything stale.
                tech._invalidate()
                traits._invalidate()
                states._invalidate()
                countries._invalidate()

    _thread = threading.Thread(target=build, name="focusforge-data-warmup", daemon=True)
    _thread.start()
