"""UI-side glue for the live country-tag list.

``core.country_tags`` is Qt-free and takes roots as a parameter; this module
is the one place that knows the roots come from ``ui.icon_provider.provider()``.
It also installs the two one-time hooks that keep core in sync with the UI:
``roots_changed`` invalidates the tag cache, and ``core.bridge_dispatch`` gets
a roots callable so the AI bridge's ``reference_data`` reports the live list.
"""
from __future__ import annotations

from core import bridge_dispatch
from core.country_tags import (
    CountryTagPreset,
    clear_country_tag_cache,
    country_tags_for_roots,
)

_hooked = False


def install_country_tag_hooks() -> None:
    """Connect ``roots_changed`` -> cache clear and hand the bridge a roots
    provider. Idempotent — every caller of ``current_country_tags`` runs it, so
    the guard is what stops the signal being connected N times."""
    global _hooked
    if _hooked:
        return
    # Lazy: ui.icon_provider pulls in QSettings/QPixmap machinery and this
    # module is imported by widget modules — keep the import cycle risk out.
    from ui.icon_provider import provider

    provider().roots_changed.connect(clear_country_tag_cache)
    bridge_dispatch.set_roots_provider(lambda: provider().roots())
    _hooked = True


def current_country_tags() -> list[CountryTagPreset]:
    """The tag list for the currently configured game-data roots (cached in
    core until the roots change)."""
    install_country_tag_hooks()
    from ui.icon_provider import provider

    return country_tags_for_roots(provider().roots())
