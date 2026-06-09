"""Build the grouped leader options for the "Put Leader in Power" reward:
the country's preset Millennium Dawn leaders + the project's custom leaders.
Each option's value is an encoded blob the reward builder decodes."""
from __future__ import annotations

from core.exporters import _is_portrait_path, _leader_slug, _portrait_sprite_name
from core.reward_presets import encode_leader

from .country_provider import country_provider


def _custom_leader_picture(tag: str, leader) -> str:
    """The picture string create_country_leader should use for a custom leader —
    mirrors export_country_history so it resolves to the exported asset/sprite."""
    if leader.pictureData:
        return f"{_leader_slug(leader)}.dds"
    if _is_portrait_path(leader.pictureRef):
        return _portrait_sprite_name(tag, leader)
    return leader.pictureRef or ""


def build_leader_refs(project) -> list:
    """[(group_label, [(encoded_value, display_name)])] — preset MD leaders first,
    then the project's custom leaders. Groups with no leaders are omitted."""
    tag = (project.countryTag or "").strip().upper()
    groups = []

    preset = country_provider().leaders(tag) if tag else []
    if preset:
        groups.append(("Preset MD leaders", [
            (encode_leader(d["name"], d.get("ideology", ""), d.get("picture", ""),
                           d.get("traits")), d["name"])
            for d in preset]))

    country = getattr(project, "country", None)
    custom = []
    for leader in (country.leaders if country else []) or []:
        name = (leader.name or "").strip()
        if not name:
            continue
        custom.append((encode_leader(name, leader.ideology,
                                     _custom_leader_picture(tag, leader), leader.traits), name))
    if custom:
        groups.append(("Custom leaders", custom))
    return groups
