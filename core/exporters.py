"""HOI4 / Millennium Dawn export — ported from exporters.ts. Byte-identical to TS output."""
from __future__ import annotations

import re

from .availability_presets import build_availability_item_lines
from .md_parties import MD_PARTY_LABEL_BY_INDEX, MD_PARTY_SUBIDEOLOGY_BY_INDEX
from .reward_presets import build_reward_item_lines
from .types import (
    AvailabilityRule,
    CompletionReward,
    EventData,
    ExportedFile,
    FocusForgeProject,
    FocusNodeData,
    IdeaData,
)

TAB = "\t"

# Characters Windows forbids in file names (plus control chars). A ':' silently
# writes into an NTFS alternate data stream (visible file empty, HOI4 loads
# nothing); '<>|' raise OSError.
_FILENAME_BAD_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_component(name: str, fallback: str = "") -> str:
    """Make one path component safe for Windows/NTFS: strip forbidden characters
    and control chars, collapse whitespace, fall back when nothing is left."""
    cleaned = _FILENAME_BAD_RE.sub("", name or "")
    cleaned = " ".join(cleaned.split())
    return cleaned or fallback


def export_project_files(project: FocusForgeProject) -> list:
    settings = project.exportSettings
    files: list = [
        ExportedFile(
            relativePath=f"common/national_focus/{settings.focusFileName}.txt",
            content=export_focus_tree(project),
        ),
        ExportedFile(
            relativePath=f"localisation/english/{settings.localisationPrefix}_focus_l_english.yml",
            content=export_focus_localisation(project),
            bom=True,
        ),
    ]
    focus_icon_gfx = export_focus_icon_sprites(project)
    if focus_icon_gfx:
        files.append(ExportedFile(
            relativePath=f"interface/{settings.localisationPrefix}_focus_icons.gfx",
            content=focus_icon_gfx,
        ))
    if settings.includeIdeas and project.ideas:
        files.append(ExportedFile(
            relativePath=f"common/ideas/{settings.localisationPrefix}_ideas.txt",
            content=export_ideas(project),
        ))
        files.append(ExportedFile(
            relativePath=f"localisation/english/{settings.localisationPrefix}_ideas_l_english.yml",
            content=export_idea_localisation(project),
            bom=True,
        ))
    if settings.includeEvents and project.events:
        files.append(ExportedFile(
            relativePath=f"events/{settings.localisationPrefix}_events.txt",
            content=export_events(project),
        ))
        files.append(ExportedFile(
            relativePath=f"localisation/english/{settings.localisationPrefix}_events_l_english.yml",
            content=export_event_localisation(project),
            bom=True,
        ))
        event_pic_gfx = export_event_picture_sprites(project)
        if event_pic_gfx:
            files.append(ExportedFile(
                relativePath=f"interface/{settings.localisationPrefix}_event_pictures.gfx",
                content=event_pic_gfx,
            ))
        if scheduled_events(project):
            files.append(ExportedFile(
                relativePath=f"common/on_actions/{settings.localisationPrefix}_on_actions.txt",
                content=export_on_actions(project),
            ))
    if settings.includeDecisions and (project.decisions or project.decisionCategories):
        if project.decisionCategories:
            files.append(ExportedFile(
                relativePath=f"common/decisions/categories/{settings.localisationPrefix}_decision_categories.txt",
                content=export_decision_categories(project),
            ))
        if project.decisions:
            files.append(ExportedFile(
                relativePath=f"common/decisions/{settings.localisationPrefix}_decisions.txt",
                content=export_decisions(project),
            ))
        files.append(ExportedFile(
            relativePath=f"localisation/english/{settings.localisationPrefix}_decisions_l_english.yml",
            content=export_decision_localisation(project),
            bom=True,
        ))
        decision_icon_gfx = export_decision_icon_sprites(project)
        if decision_icon_gfx:
            files.append(ExportedFile(
                relativePath=f"interface/{settings.localisationPrefix}_decision_icons.gfx",
                content=decision_icon_gfx,
            ))
    if settings.includeCountry and project.country:
        history_name = sanitize_filename_component(
            project.projectName, project.countryTag) or project.countryTag
        files.append(ExportedFile(
            relativePath=f"history/countries/{project.countryTag} - {history_name}.txt",
            content=export_country_history(project),
        ))
        files.append(ExportedFile(
            relativePath=f"localisation/english/{settings.localisationPrefix}_country_l_english.yml",
            content=export_country_localisation(project),
            bom=True,
        ))
        portrait_gfx = export_leader_portrait_sprites(project)
        if portrait_gfx:
            files.append(ExportedFile(
                relativePath=f"interface/{settings.localisationPrefix}_portraits.gfx",
                content=portrait_gfx,
            ))
        party_logo_gfx = export_party_logo_sprites(project)
        if party_logo_gfx:
            files.append(ExportedFile(
                relativePath=f"interface/{settings.localisationPrefix}_party_logos.gfx",
                content=party_logo_gfx,
            ))
        if country_election_leader_assignments(project):
            election_base = _election_leader_base(project)
            files.append(ExportedFile(
                relativePath=f"common/scripted_effects/{election_base}_election_leaders.txt",
                content=export_country_election_leader_effects(project),
            ))
            files.append(ExportedFile(
                relativePath=f"events/{election_base}_election_leaders.txt",
                content=export_country_election_leader_events(project),
            ))
            files.append(ExportedFile(
                relativePath=f"common/on_actions/{election_base}_election_leaders_on_actions.txt",
                content=export_country_election_leader_on_actions(project),
            ))
    return files


def _party_key(tag: str, ideology: str) -> str:
    return f"{tag}_{ideology}_party"


def _leader_picture_value(tag: str, leader, country=None) -> str:
    if leader.pictureData:
        return f"{leader_asset_slug(country, leader)}.dds"
    if _is_portrait_path(leader.pictureRef):
        return _portrait_sprite_name(tag, leader, country)
    return leader.pictureRef or ""


def _leader_block_lines(leader, tag: str, depth: int = 0, country=None) -> list:
    prefix = TAB * depth
    inner = TAB * (depth + 1)
    picture = _leader_picture_value(tag, leader, country)
    lines = [f"{prefix}create_country_leader = {{"]
    lines.append(f'{inner}name = "{_escape_loc(leader.name)}"')
    if (getattr(leader, "description", "") or "").strip():
        # desc takes a localisation KEY; the text itself is written by
        # export_country_localisation under the same key.
        lines.append(f'{inner}desc = "{_leader_desc_key(tag, leader, country)}"')
    if picture:
        lines.append(f'{inner}picture = "{picture}"')
    lines.append(f"{inner}ideology = {leader.ideology}")
    if leader.traits:
        lines.append(f"{inner}traits = {{ {' '.join(leader.traits)} }}")
    lines.append(f"{prefix}}}")
    return lines


def _leader_desc_key(tag: str, leader, country) -> str:
    """Loc key for a leader's in-game description — unique per leader via the
    same slug machinery the portrait assets use, so two leaders with the same
    (or non-Latin) names never share a description."""
    return f"{tag}_{leader_asset_slug(country, leader)}_desc"


def export_country_history(project: FocusForgeProject) -> str:
    c = project.country
    tag = project.countryTag
    lines: list = []
    if c.popularities:
        lines.append("set_popularities = {")
        for ideo in ("democratic", "communism", "fascism", "neutrality", "nationalist"):
            if ideo in c.popularities:
                v = c.popularities[ideo]
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue  # non-numeric (corrupt) value — skip rather than crash
                n = int(f) if f.is_integer() else v  # keep MD's decimals, drop .0
                lines.append(f"{TAB}{ideo} = {n}")
        lines.append("}")
    lines.append("set_politics = {")
    lines.append(f"{TAB}ruling_party = {c.rulingParty}")
    if c.lastElection:
        lines.append(f'{TAB}last_election = "{c.lastElection}"')
    lines.append(f"{TAB}election_frequency = {c.electionFrequency}")
    lines.append(f"{TAB}elections_allowed = {'yes' if c.electionsAllowed else 'no'}")
    lines.append("}")
    for party in c.parties:
        if not party.ideology:
            continue
        key = _party_key(tag, party.ideology)
        lines.append("set_party_name = {")
        lines.append(f"{TAB}ideology = {party.ideology}")
        lines.append(f"{TAB}long_name = {key}_long")
        lines.append(f"{TAB}name = {key}")
        lines.append("}")
    for leader in c.leaders:
        lines.extend(_leader_block_lines(leader, tag, country=c))
    return "\n".join(lines) + "\n"


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SAN_RE = re.compile(r"[^A-Za-z0-9]+")


def _leader_slug(leader) -> str:
    return _SLUG_RE.sub("_", (leader.name or "leader").lower()).strip("_") or "leader"


def leader_asset_slugs(country) -> list:
    """One UNIQUE filesystem slug per leader, aligned with
    :func:`_country_leaders_for_assets` order.

    The plain per-leader slug strips non-``[a-z0-9]``, so two all-non-Latin
    names (Cyrillic, Arabic, …) both slug to the same string and the second
    leader's .dds silently overwrites the first's. Here an empty slug falls
    back to ``leader_<index>`` (position in the combined leader list) and
    duplicates get a deterministic ``_2`` / ``_3`` suffix, so sprite/picture
    references (exporters) and asset filenames (ui.country_export) always
    agree AND never collide."""
    slugs: list = []
    used: set = set()
    for i, leader in enumerate(_country_leaders_for_assets(country)):
        base = (_SLUG_RE.sub("_", (leader.name or "").lower()).strip("_")
                or f"leader_{i}")
        slug, n = base, 2
        while slug in used:
            slug = f"{base}_{n}"
            n += 1
        used.add(slug)
        slugs.append(slug)
    return slugs


def leader_asset_slug(country, leader) -> str:
    """The unique slug for one leader (identity lookup in the country's combined
    leader list). Falls back to the plain slug when the leader isn't part of the
    country (defensive — e.g. previews of a detached LeaderData)."""
    if country is not None:
        for ld, slug in zip(_country_leaders_for_assets(country),
                            leader_asset_slugs(country)):
            if ld is leader:
                return slug
    return _leader_slug(leader)


def _san(token: str) -> str:
    """Filesystem/sprite-safe form of a sub-ideology token (keeps the loc key raw,
    but hyphens etc. aren't safe in sprite names / filenames)."""
    return _SAN_RE.sub("_", token or "").strip("_")


def _party_logo_sprite_name(tag: str, sub: str) -> str:
    """Generated sprite name for a CUSTOM party logo (distinct ``_party_logo``
    suffix so it never collides with one of MD's own GFX_<TAG>_<party> sprites)."""
    return f"GFX_{(tag or '').upper()}_{_san(sub)}_party_logo"


def _party_logo_relpath(tag: str, sub: str) -> str:
    """Posix relpath of a custom party-logo .dds, alongside MD's own party icons."""
    return (f"gfx/texticons/parties_icons/{(tag or '').lower()}/"
            f"{(tag or '').upper()}_{_san(sub)}_party_logo.dds")


def _party_logo_loc_value(tag: str, party) -> str:
    """The ``£<value>`` sprite reference for a party's logo, or "" if none.
    Custom logos point at the generated sprite; presets reuse the chosen MD
    sprite (its name minus the GFX_ prefix)."""
    if party.logoData:
        return f"{(tag or '').upper()}_{_san(party.subIdeology)}_party_logo"
    ref = party.logoRef or ""
    if ref:
        return ref[4:] if ref.startswith("GFX_") else ref
    return ""


def _event_picture_sprite_name(event) -> str:
    """Generated sprite name for a CUSTOM event picture (``_event_pic`` suffix so it
    never collides with a vanilla/MD GFX_report_event_… sprite)."""
    return f"GFX_{_san(event.id)}_event_pic"


def _event_picture_relpath(event) -> str:
    """Posix relpath of a custom event-picture .dds (under the mod's event_pictures)."""
    return f"gfx/event_pictures/{_san(event.id)}.dds"


def _event_picture_value(event) -> str:
    """The ``picture = …`` GFX name for an event: the generated sprite for a custom
    image, else the chosen/typed sprite name."""
    if getattr(event, "pictureData", ""):
        return _event_picture_sprite_name(event)
    return event.picture or "GFX_report_event_generic_parliament"


def export_event_picture_sprites(project) -> "str | None":
    """interface/*.gfx spriteTypes wrapping each CUSTOM event picture (imported
    image), so the generated ``GFX_<id>_event_pic`` reference resolves. None if no
    event uses a custom picture (presets reference existing sprites)."""
    entries = [(_event_picture_sprite_name(e), _event_picture_relpath(e))
               for e in project.events if getattr(e, "pictureData", "")]
    if not entries:
        return None
    lines = ["spriteTypes = {"]
    for name, tex in entries:
        lines.append(f'{TAB}spriteType = {{ name = "{name}" texturefile = "{tex}" }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _focus_icon_sprite_name(focus) -> str:
    """Generated sprite name for a CUSTOM focus icon (``_focus_icon`` suffix so it
    never collides with a vanilla/MD GFX_focus_… sprite)."""
    return f"GFX_{_san(focus.id)}_focus_icon"


def _focus_icon_relpath(focus) -> str:
    """Posix relpath of a custom focus-icon .dds (under the mod's goals folder,
    where HOI4/MD keep focus art — the New Submod scaffold creates it)."""
    return f"gfx/interface/goals/{_san(focus.id)}.dds"


def _focus_icon_value(focus) -> str:
    """The ``icon = …`` GFX name for a focus: the generated sprite for a custom
    imported image, else the chosen/typed sprite name."""
    if getattr(focus, "iconData", ""):
        return _focus_icon_sprite_name(focus)
    return focus.icon


def _focus_shine_lines(name: str, tex: str) -> list:
    """The standard HOI4 ``GFX_…_shine`` spriteType (two scrolling add-blend
    animations over the icon, like base-game goals_shine.gfx) — without it the
    game logs a missing-sprite error and completable focuses don't glow."""
    lines = [f"{TAB}spriteType = {{",
             f'{TAB}{TAB}name = "{name}_shine"',
             f'{TAB}{TAB}texturefile = "{tex}"',
             f'{TAB}{TAB}effectFile = "gfx/FX/buttonstate.lua"']
    for rotation in ("-90.0", "90.0"):
        lines.extend([
            f"{TAB}{TAB}animation = {{",
            f'{TAB}{TAB}{TAB}animationmaskfile = "{tex}"',
            f'{TAB}{TAB}{TAB}animationtexturefile = "gfx/interface/goals/shine_overlay.dds"',
            f"{TAB}{TAB}{TAB}animationrotation = {rotation}",
            f"{TAB}{TAB}{TAB}animationlooping = no",
            f"{TAB}{TAB}{TAB}animationtime = 0.75",
            f"{TAB}{TAB}{TAB}animationdelay = 0",
            f'{TAB}{TAB}{TAB}animationblendmode = "add"',
            f'{TAB}{TAB}{TAB}animationtype = "scrolling"',
            f"{TAB}{TAB}{TAB}animationrotationoffset = {{ x = 0.0 y = 0.0 }}",
            f"{TAB}{TAB}{TAB}animationtexturescale = {{ x = 1.0 y = 1.0 }}",
            f"{TAB}{TAB}}}",
        ])
    lines.append(f"{TAB}{TAB}legacy_lazy_load = no")
    lines.append(f"{TAB}}}")
    return lines


def export_focus_icon_sprites(project) -> "str | None":
    """interface/*.gfx spriteTypes wrapping each CUSTOM focus icon (imported
    image), so the generated ``GFX_<id>_focus_icon`` reference resolves — plus the
    matching ``_shine`` sprite the game expects for every focus icon. None if no
    focus uses a custom icon (named icons reference existing sprites)."""
    entries = [(_focus_icon_sprite_name(f), _focus_icon_relpath(f))
               for f in project.focuses if getattr(f, "iconData", "")]
    if not entries:
        return None
    lines = ["spriteTypes = {"]
    for name, tex in entries:
        lines.append(f'{TAB}spriteType = {{ name = "{name}" texturefile = "{tex}" }}')
    for name, tex in entries:
        lines.extend(_focus_shine_lines(name, tex))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _is_portrait_path(ref) -> bool:
    """True when a leader's pictureRef is an MD portrait image path (always under
    gfx/leaders/<TAG>/…), vs a GFX sprite name or a bare filename."""
    return "gfx/leaders" in (ref or "").replace("\\", "/").lower()


def _portrait_sprite_name(tag, leader, country=None) -> str:
    # With a country, the unique per-leader slug keeps two same-slugging leaders
    # from sharing one sprite name (second texture would win for both).
    slug = leader_asset_slug(country, leader) if country is not None else _leader_slug(leader)
    return f"GFX_{(tag or '').upper()}_{slug}"


def _country_leaders_for_assets(country) -> list:
    leaders = list(getattr(country, "leaders", None) or [])
    for assignment in getattr(country, "electionLeaders", None) or []:
        leader = getattr(assignment, "leader", None)
        if leader is not None:
            leaders.append(leader)
    return leaders


def export_leader_portrait_sprites(project) -> "str | None":
    """interface/*.gfx spriteTypes wrapping each MD-image portrait a leader picked,
    so ``create_country_leader { picture = GFX_… }`` resolves. None if there are
    no image-path portraits. The texturefile points at MD's existing image (MD is
    a dependency), so no .dds copy is needed."""
    c = project.country
    if not c:
        return None
    tag = project.countryTag
    entries = {}
    for ld in _country_leaders_for_assets(c):
        if _is_portrait_path(ld.pictureRef):
            entries[_portrait_sprite_name(tag, ld, c)] = ld.pictureRef.replace("\\", "/")
    if not entries:
        return None
    lines = ["spriteTypes = {"]
    for name, tex in entries.items():
        lines.append(f'{TAB}spriteType = {{ name = "{name}" texturefile = "{tex}" }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_party_logo_sprites(project) -> "str | None":
    """interface/*.gfx spriteTypes wrapping each CUSTOM party logo (imported image),
    so the generated ``£<TAG>_<sub>_party_logo`` reference resolves. None if there
    are no custom logos (presets reuse MD's own sprites, which need no definition)."""
    c = project.country
    if not c:
        return None
    tag = project.countryTag
    entries = [(_party_logo_sprite_name(tag, p.subIdeology), _party_logo_relpath(tag, p.subIdeology))
               for p in c.parties if p.logoData and p.subIdeology]
    if not entries:
        return None
    lines = ["spriteTypes = {"]
    for name, tex in entries:
        lines.append(f'{TAB}spriteType = {{ name = "{name}" texturefile = "{tex}" }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _assignment_party_index(assignment) -> int:
    try:
        return int(getattr(assignment, "partyIndex", 14))
    except (TypeError, ValueError):
        return 14


def _assignment_start_date(assignment) -> str:
    return (getattr(assignment, "startDate", "") or "").strip()


def _date_key(value: str) -> tuple:
    m = re.match(r"^\s*(\d{1,4})\.(\d{1,2})\.(\d{1,2})\s*$", value or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(part) for part in m.groups())


def _election_leader_base(project) -> str:
    settings = getattr(project, "exportSettings", None)
    prefix = getattr(settings, "localisationPrefix", "") if settings else ""
    return _san(prefix or getattr(project, "countryTag", "") or "ffg") or "ffg"


def _election_leader_namespace(project) -> str:
    return f"{_election_leader_base(project)}_election_leaders"


def _election_leader_effect_name(project) -> str:
    return f"{_election_leader_base(project)}_set_election_leader"


def country_election_leader_assignments(project) -> list:
    c = getattr(project, "country", None)
    if not c:
        return []
    rows = []
    for assignment in getattr(c, "electionLeaders", None) or []:
        leader = getattr(assignment, "leader", None)
        party_index = _assignment_party_index(assignment)
        if party_index not in MD_PARTY_SUBIDEOLOGY_BY_INDEX:
            continue
        if not _assignment_start_date(assignment):
            continue
        if leader is None or not (getattr(leader, "name", "") or "").strip():
            continue
        rows.append(assignment)
    return rows


def export_country_election_leader_effects(project) -> str:
    """Scripted effect that picks the newest matching dated leader assignment.

    Each hidden event calls this same effect. Sorting newest-first means that if
    an older event becomes eligible after a newer row's date, it still leaves the
    country with the newest applicable leader.
    """
    tag = (getattr(project, "countryTag", "") or "").strip().upper()
    rows = sorted(
        country_election_leader_assignments(project),
        key=lambda a: (_date_key(_assignment_start_date(a)), _assignment_party_index(a)),
        reverse=True,
    )
    lines = [f"{_election_leader_effect_name(project)} = {{"]
    for i, assignment in enumerate(rows):
        party_index = _assignment_party_index(assignment)
        party_label = MD_PARTY_LABEL_BY_INDEX.get(party_index, "MD party")
        start_date = _assignment_start_date(assignment)
        leader = assignment.leader
        key = "if" if i == 0 else "else_if"
        lines.append(f"{TAB}{key} = {{")
        lines.append(f"{TAB}{TAB}limit = {{")
        if tag:
            lines.append(f"{TAB}{TAB}{TAB}original_tag = {tag}")
        lines.append(f"{TAB}{TAB}{TAB}is_in_array = {{ ruling_party = {party_index} }}")
        lines.append(f"{TAB}{TAB}{TAB}date > {start_date}")
        lines.append(f"{TAB}{TAB}}}")
        lines.append(f"{TAB}{TAB}# {party_index}: {party_label}")
        lines.append(f"{TAB}{TAB}hidden_effect = {{ kill_country_leader = yes }}")
        lines.extend(_leader_block_lines(leader, tag, 2, country=project.country))
        lines.append(f"{TAB}}}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_country_election_leader_events(project) -> str:
    namespace = _election_leader_namespace(project)
    effect = _election_leader_effect_name(project)
    tag = (getattr(project, "countryTag", "") or "").strip().upper()
    lines = [f"add_namespace = {namespace}"]
    for i, assignment in enumerate(country_election_leader_assignments(project), start=1):
        leader = assignment.leader
        event_id = f"{namespace}.{i}"
        lines.append("")
        lines.append("country_event = {")
        lines.append(f"{TAB}id = {event_id}")
        lines.append(f"{TAB}hidden = yes")
        lines.append(f"{TAB}is_triggered_only = yes")
        lines.append(f"{TAB}fire_only_once = yes")
        lines.append(f"{TAB}trigger = {{")
        if tag:
            lines.append(f"{TAB}{TAB}original_tag = {tag}")
        lines.append(f"{TAB}{TAB}date > {_assignment_start_date(assignment)}")
        lines.append(f"{TAB}{TAB}is_in_array = {{ ruling_party = {_assignment_party_index(assignment)} }}")
        lines.append(f'{TAB}{TAB}NOT = {{ has_country_leader = {{ name = "{_escape_loc(leader.name)}" ruling_only = yes }} }}')
        lines.append(f"{TAB}}}")
        lines.append("")
        lines.append(f"{TAB}option = {{")
        lines.append(f"{TAB}{TAB}name = OK")
        lines.append(f"{TAB}{TAB}{effect} = yes")
        lines.append(f"{TAB}}}")
        lines.append("}")
    return "\n".join(lines) + "\n"


def export_country_election_leader_on_actions(project) -> str:
    namespace = _election_leader_namespace(project)
    lines = ["on_actions = {"]
    lines.append(f"{TAB}on_daily = {{")
    lines.append(f"{TAB}{TAB}events = {{")
    for i, _assignment in enumerate(country_election_leader_assignments(project), start=1):
        lines.append(f"{TAB}{TAB}{TAB}{namespace}.{i}")
    lines.append(f"{TAB}{TAB}}}")
    lines.append(f"{TAB}}}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_country_localisation(project: FocusForgeProject) -> str:
    c = project.country
    tag = project.countryTag
    lines = ["l_english:"]
    for party in c.parties:
        if not party.ideology:
            continue
        key = _party_key(tag, party.ideology)
        lines.append(f' {key}:0 "{_escape_loc(party.name)}"')
        lines.append(f' {key}_long:0 "{_escape_loc(party.longName or party.name)}"')
    # Party-logo icon mapping MD reads at runtime: <TAG>.<subideology>_icon → £sprite
    for party in c.parties:
        if not party.subIdeology:
            continue
        value = _party_logo_loc_value(tag, party)
        if value:
            lines.append(f' {tag}.{party.subIdeology}_icon:0 "£{value}"')
        # MD displays the party name from <TAG>.<sub> (with a leading £icon token),
        # not from set_party_name — so write it here too or edits won't show in-game.
        if (party.name or "").strip():
            prefix = f"£{value} " if value else ""
            lines.append(f' {tag}.{party.subIdeology}:0 "{prefix}{_escape_loc(party.name)}"')
        if (party.description or "").strip():
            # MD party description shown in the politics screen (<TAG>.<sub>_desc).
            lines.append(f' {tag}.{party.subIdeology}_desc:0 "{_escape_loc(party.description)}"')
    # Leader descriptions (main leaders + election-timeline leaders): the text
    # behind each create_country_leader's desc = "<key>".
    for leader in _country_leaders_for_assets(c):
        if (getattr(leader, "description", "") or "").strip():
            key = _leader_desc_key(tag, leader, c)
            lines.append(f' {key}:0 "{_escape_loc(leader.description)}"')
    return "\n".join(lines) + "\n"


def shortcut_loc_keys(project: FocusForgeProject) -> list:
    """One UNIQUE localisation key per shortcut, aligned with ``project.shortcuts``
    order.

    Two shortcuts with the same label would slug to the same key and collide
    (the second ``name = <key>`` would show the wrong label), so — mirroring
    :func:`leader_asset_slugs` — an empty label falls back to ``shortcut_<index>``
    and duplicates get a deterministic ``_2`` / ``_3`` suffix. Used by BOTH the
    tree and loc exporters so ``name = <key>`` and ``<key>:0 "…"`` always agree."""
    settings = getattr(project, "exportSettings", None)
    prefix = (getattr(settings, "localisationPrefix", "") if settings else "") or ""
    keys: list = []
    used: set = set()
    for i, sc in enumerate(getattr(project, "shortcuts", None) or []):
        slug = _SLUG_RE.sub("_", (getattr(sc, "label", "") or "").lower()).strip("_") or f"shortcut_{i}"
        base = f"{prefix}_{slug}_shortcut"
        key, n = base, 2
        while key in used:
            key = f"{base}_{n}"
            n += 1
        used.add(key)
        keys.append(key)
    return keys


def _export_shortcut(shortcut, loc_key: str) -> list:
    """One ``shortcut = { }`` block at focus_tree depth (indent 1)."""
    lines = [
        f"{TAB}shortcut = {{",
        f"{TAB}{TAB}name = {loc_key}",
        f"{TAB}{TAB}target = {shortcut.target}",
    ]
    if getattr(shortcut, "zoomFactor", None) is not None:
        lines.append(f"{TAB}{TAB}scroll_wheel_factor = {_format_number(shortcut.zoomFactor)}")
    trigger = [ln for ln in (getattr(shortcut, "triggerRawLines", None) or [])
               if (ln or "").strip()]
    if trigger:
        lines.append(f"{TAB}{TAB}trigger = {{")
        for raw in trigger:
            lines.append(f"{TAB}{TAB}{TAB}{raw.strip()}")
        lines.append(f"{TAB}{TAB}}}")
    lines.append(f"{TAB}}}")
    return lines


def export_focus_tree(project: FocusForgeProject) -> str:
    lines: list = [
        "focus_tree = {",
        f"{TAB}id = {project.treeId}",
        "",
        f"{TAB}country = {{",
        f"{TAB}{TAB}factor = 0",
        f"{TAB}{TAB}modifier = {{",
        f"{TAB}{TAB}{TAB}add = 100",
        f"{TAB}{TAB}{TAB}tag = {project.countryTag}",
        f"{TAB}{TAB}}}",
        f"{TAB}}}",
        "",
        f"{TAB}continuous_focus_position = {{ x = {project.continuousFocusPosition.x} y = {project.continuousFocusPosition.y} }}",
        f"{TAB}initial_show_position = {{ x = 0 y = 0 }}",
        "",
    ]

    # Branch-bookmark shortcut blocks sit at the top of the tree, before the
    # focuses. Skip any with an empty target; emit NOTHING (no blank lines) when
    # there are no shortcuts so the no-shortcuts export stays byte-identical.
    keys = shortcut_loc_keys(project)
    for shortcut, key in zip(getattr(project, "shortcuts", None) or [], keys):
        if not (getattr(shortcut, "target", "") or "").strip():
            continue
        lines.extend(_export_shortcut(shortcut, key))
        lines.append("")

    sorted_focuses = sorted(project.focuses, key=lambda f: (f.position.y, f.position.x, f.id))
    for focus in sorted_focuses:
        lines.extend(_export_focus(focus))
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _export_focus(focus: FocusNodeData) -> list:
    lines: list = [
        f"{TAB}focus = {{",
        f"{TAB}{TAB}id = {focus.id}",
    ]
    icon = _focus_icon_value(focus)
    if (icon or "").strip():
        # `icon = ` with NO value would make the Paradox parser consume the next
        # token ("x") as the value, corrupting the whole focus block.
        lines.append(f"{TAB}{TAB}icon = {icon}")
    lines.extend([
        f"{TAB}{TAB}x = {focus.position.x}",
        f"{TAB}{TAB}y = {focus.position.y}",
        f"{TAB}{TAB}cost = {focus.cost}",
    ])
    # Each element of prerequisites is one prerequisite BLOCK. A plain id is a
    # single-focus block; a list is an OR group (several focus= in one block).
    # Separate blocks are AND-ed by HOI4; choices within a block are OR-ed.
    for prereq in focus.prerequisites:
        if isinstance(prereq, (list, tuple)):
            inner = " ".join(f"focus = {p}" for p in prereq)
            lines.append(f"{TAB}{TAB}prerequisite = {{ {inner} }}")
        else:
            lines.append(f"{TAB}{TAB}prerequisite = {{ focus = {prereq} }}")
    for exclusive in focus.mutuallyExclusive:
        lines.append(f"{TAB}{TAB}mutually_exclusive = {{ focus = {exclusive} }}")

    if focus.available and _has_availability(focus.available):
        lines.append(f"{TAB}{TAB}available = {{")
        for line in _availability_inner_lines(focus.available):
            lines.append(f"{TAB}{TAB}{TAB}{line}")
        lines.append(f"{TAB}{TAB}}}")

    bypass = getattr(focus, "bypass", None)
    if bypass and _has_availability(bypass):
        lines.append(f"{TAB}{TAB}bypass = {{")
        for line in _availability_inner_lines(bypass):
            lines.append(f"{TAB}{TAB}{TAB}{line}")
        lines.append(f"{TAB}{TAB}}}")

    if focus.filters:
        lines.append(f"{TAB}{TAB}search_filters = {{ {' '.join(focus.filters)} }}")

    lines.append("")
    lines.append(f"{TAB}{TAB}completion_reward = {{")
    lines.append(f'{TAB}{TAB}{TAB}log = "[GetDateText]: [Root.GetName]: Focus {focus.id}"')
    lines.extend(export_completion_reward_lines(focus.completionReward))
    lines.append(f"{TAB}{TAB}}}")
    lines.append("")
    ai_base = getattr(focus, "aiWillDo", None)
    lines.append(f"{TAB}{TAB}ai_will_do = {{")
    lines.append(f"{TAB}{TAB}{TAB}base = {_format_number(ai_base) if ai_base is not None else 10}")
    lines.append(f"{TAB}{TAB}}}")
    lines.append(f"{TAB}}}")
    return lines


def _has_availability(rule: AvailabilityRule) -> bool:
    return bool(
        (rule.completedFocuses or [])
        or (rule.flagsRequired or [])
        or (rule.flagsBlocked or [])
        or (rule.items or [])
        or (rule.rawLines or [])
    )


def export_completion_reward_lines(reward: CompletionReward) -> list:
    lines: list = []
    if reward is None:
        return lines
    if reward.politicalPower:
        lines.append(f"{TAB}{TAB}{TAB}add_political_power = {_format_number(reward.politicalPower)}")
    if reward.stability:
        lines.append(f"{TAB}{TAB}{TAB}add_stability = {_format_number(reward.stability)}")
    if reward.warSupport:
        lines.append(f"{TAB}{TAB}{TAB}add_war_support = {_format_number(reward.warSupport)}")
    if reward.commandPower:
        lines.append(f"{TAB}{TAB}{TAB}add_command_power = {_format_number(reward.commandPower)}")
    if reward.armyExperience:
        lines.append(f"{TAB}{TAB}{TAB}army_experience = {_format_number(reward.armyExperience)}")
    if reward.airExperience:
        lines.append(f"{TAB}{TAB}{TAB}air_experience = {_format_number(reward.airExperience)}")
    if reward.navyExperience:
        lines.append(f"{TAB}{TAB}{TAB}navy_experience = {_format_number(reward.navyExperience)}")
    for idea in (reward.addIdeas or []):
        lines.append(f"{TAB}{TAB}{TAB}add_ideas = {idea}")
    for idea in (reward.removeIdeas or []):
        lines.append(f"{TAB}{TAB}{TAB}remove_ideas = {idea}")
    for event in (reward.events or []):
        days = "" if (getattr(event, "days", None) is None) else f" days = {int(event.days)}"
        lines.append(f"{TAB}{TAB}{TAB}country_event = {{ id = {event.id}{days} }}")
    for bonus in (reward.techBonuses or []):
        lines.append(f"{TAB}{TAB}{TAB}add_tech_bonus = {{")
        if getattr(bonus, "name", None):
            lines.append(f"{TAB}{TAB}{TAB}{TAB}name = {bonus.name}")
        lines.append(f"{TAB}{TAB}{TAB}{TAB}bonus = {_format_number(bonus.bonus)}")
        lines.append(f"{TAB}{TAB}{TAB}{TAB}uses = {int(bonus.uses)}")
        lines.append(f"{TAB}{TAB}{TAB}{TAB}category = {bonus.category}")
        lines.append(f"{TAB}{TAB}{TAB}}}")
    for item in (reward.items or []):
        for line in build_reward_item_lines(item):
            lines.append(f"{TAB}{TAB}{TAB}{line}")
    for raw in (reward.rawLines or []):
        lines.append(f"{TAB}{TAB}{TAB}{raw}")
    return lines


def _format_number(value) -> str:
    f = float(value)
    if f.is_integer():
        return str(int(f))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def export_focus_localisation(project: FocusForgeProject) -> str:
    lines = ["l_english:"]
    for focus in project.focuses:
        lines.append(f' {focus.id}:0 "{_escape_loc(focus.title)}"')
        lines.append(f' {focus.id}_desc:0 "{_escape_loc(focus.description)}"')
    # Shortcut button labels — keyed identically to each tree ``name = <key>``.
    keys = shortcut_loc_keys(project)
    for shortcut, key in zip(getattr(project, "shortcuts", None) or [], keys):
        if not (getattr(shortcut, "target", "") or "").strip():
            continue
        lines.append(f' {key}:0 "{_escape_loc(shortcut.label)}"')
    return "\n".join(lines) + "\n"


def export_ideas(project: FocusForgeProject) -> str:
    lines = ["ideas = {", f"{TAB}country = {{"]
    for idea in project.ideas:
        lines.append(f"{TAB}{TAB}{idea.id} = {{")
        if (idea.picture or "").strip():
            # a valueless `picture = ` line would swallow the next token
            lines.append(f"{TAB}{TAB}{TAB}picture = {idea.picture}")
        for raw in idea.modifierRawLines:
            lines.append(f"{TAB}{TAB}{TAB}{raw}")
        lines.append(f"{TAB}{TAB}}}")
    lines.append(f"{TAB}}}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_idea_localisation(project: FocusForgeProject) -> str:
    lines = ["l_english:"]
    for idea in project.ideas:
        lines.append(f' {idea.id}:0 "{_escape_loc(idea.title)}"')
        lines.append(f' {idea.id}_desc:0 "{_escape_loc(idea.description)}"')
    return "\n".join(lines) + "\n"


def _availability_inner_lines(rule: AvailabilityRule) -> list:
    """Flat HOI4 trigger lines for an AvailabilityRule (no wrapper, no indent).
    Reused for event-level and per-option ``trigger = { }`` blocks."""
    lines: list = []
    if rule is None:
        return lines
    for c in (rule.completedFocuses or []):
        lines.append(f"has_completed_focus = {c}")
    for flag in (rule.flagsRequired or []):
        lines.append(f"has_country_flag = {flag}")
    for flag in (rule.flagsBlocked or []):
        lines.append(f"NOT = {{ has_country_flag = {flag} }}")
    for item in (rule.items or []):
        lines.extend(build_availability_item_lines(item))
    for raw in (rule.rawLines or []):
        lines.append(raw)
    return lines


def scheduled_events(project: FocusForgeProject) -> list:
    """Events with a fireOnDate — they export as triggered-only + fire_only_once
    with a ``date >`` trigger, and are pumped from an ``on_daily`` on_action."""
    return [e for e in project.events
            if (getattr(e, "fireOnDate", "") or "").strip()]


def export_events(project: FocusForgeProject) -> str:
    lines = [f"add_namespace = {project.exportSettings.localisationPrefix}"]
    for event in project.events:
        # Date-scheduled events are forced triggered-only + fire-once: the
        # on_daily on_action attempts them every day, the date trigger gates
        # them, so they land exactly once, on the chosen date.
        fire_date = (getattr(event, "fireOnDate", "") or "").strip()
        lines.append("")
        lines.append(f"{event.eventType or 'country_event'} = {{")
        lines.append(f"{TAB}id = {event.id}")
        lines.append(f"{TAB}title = {event.id}.t")
        lines.append(f"{TAB}desc = {event.id}.d")
        lines.append(f"{TAB}picture = {_event_picture_value(event)}")
        if event.isTriggeredOnly or fire_date:
            lines.append(f"{TAB}is_triggered_only = yes")
        if event.hidden:
            lines.append(f"{TAB}hidden = yes")
        if event.major:
            lines.append(f"{TAB}major = yes")
        if event.fireOnlyOnce or fire_date:
            lines.append(f"{TAB}fire_only_once = yes")
        if (not event.isTriggeredOnly) and (not fire_date) and event.meanTimeToHappen:
            lines.append(f"{TAB}mean_time_to_happen = {{ days = {int(event.meanTimeToHappen)} }}")
        event_trigger = _availability_inner_lines(event.trigger)
        if fire_date:
            # on_daily fires for every country — gate on the project's tag first
            # (cheap short-circuit) so the event lands once, for this country.
            schedule = []
            tag = (project.countryTag or "").strip().upper()
            if tag:
                # original_tag survives MD tag switches (reformations, civil
                # wars); plain `tag =` would permanently block the event.
                schedule.append(f"original_tag = {tag}")
            schedule.append(f"date > {fire_date}")
            event_trigger = schedule + event_trigger
        if event_trigger:
            lines.append(f"{TAB}trigger = {{")
            for ln in event_trigger:
                lines.append(f"{TAB}{TAB}{ln}")
            lines.append(f"{TAB}}}")
        for option in event.options:
            lines.append("")
            lines.append(f"{TAB}option = {{")
            lines.append(f"{TAB}{TAB}name = {event.id}.{option.key}")
            option_trigger = _availability_inner_lines(getattr(option, "trigger", None))
            if option_trigger:
                lines.append(f"{TAB}{TAB}trigger = {{")
                for ln in option_trigger:
                    lines.append(f"{TAB}{TAB}{TAB}{ln}")
                lines.append(f"{TAB}{TAB}}}")
            if getattr(option, "aiChance", None) is not None:
                lines.append(f"{TAB}{TAB}ai_chance = {{ base = {_format_number(option.aiChance)} }}")
            for item in (getattr(option, "items", None) or []):
                for ln in build_reward_item_lines(item):
                    lines.append(f"{TAB}{TAB}{ln}")
            for raw in option.effectRawLines:
                lines.append(f"{TAB}{TAB}{raw}")
            lines.append(f"{TAB}}}")
        lines.append("}")
    return "\n".join(lines) + "\n"


def _decision_icon_relpath(decision) -> str:
    """Posix relpath of a custom decision-icon .dds (under the mod's decisions
    folder, where HOI4/MD keep decision art)."""
    return f"gfx/interface/decisions/{_san(decision.id)}.dds"


def _decision_icon_sprite_name(decision) -> str:
    """Generated sprite name for a CUSTOM decision icon (``_decision_icon`` suffix
    so it never collides with a vanilla/MD GFX_decision_… sprite)."""
    return f"GFX_{_san(decision.id)}_decision_icon"


def _decision_icon_value(decision) -> str:
    """The ``icon = …`` GFX name for a decision: the generated sprite for a custom
    imported image, else the chosen/typed sprite name."""
    if getattr(decision, "iconData", ""):
        return _decision_icon_sprite_name(decision)
    return (decision.icon or "").strip()


def export_decision_icon_sprites(project) -> "str | None":
    """interface/*.gfx spriteTypes wrapping each CUSTOM decision icon (imported
    image), so the generated ``GFX_<id>_decision_icon`` reference resolves. None
    if no decision uses a custom icon (named icons reference existing sprites)."""
    entries = [(_decision_icon_sprite_name(d), _decision_icon_relpath(d))
               for d in project.decisions if getattr(d, "iconData", "")]
    if not entries:
        return None
    lines = ["spriteTypes = {"]
    for name, tex in entries:
        lines.append(f'{TAB}spriteType = {{ name = "{name}" texturefile = "{tex}" }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _decision_lines(decision, tag: str) -> list:
    """One decision block at category depth (indent 1)."""
    d = decision
    lines = [f"{TAB}{d.id} = {{"]
    icon = _decision_icon_value(d)
    if icon:
        lines.append(f"{TAB}{TAB}icon = {icon}")
    if tag:
        # Per-decision gate so a decision dropped into a SHARED (MD) category
        # never shows for other countries.
        lines.append(f"{TAB}{TAB}allowed = {{ original_tag = {tag} }}")
    if d.cost is not None:
        lines.append(f"{TAB}{TAB}cost = {_format_number(d.cost)}")
    if d.fireOnlyOnce:
        lines.append(f"{TAB}{TAB}fire_only_once = yes")
    if d.isGood is not None:
        lines.append(f"{TAB}{TAB}is_good = {'yes' if d.isGood else 'no'}")
    if d.daysRemove is not None:
        lines.append(f"{TAB}{TAB}days_remove = {int(d.daysRemove)}")
    if d.daysReEnable is not None:
        lines.append(f"{TAB}{TAB}days_re_enable = {int(d.daysReEnable)}")
    if d.daysMissionTimeout is not None:
        lines.append(f"{TAB}{TAB}days_mission_timeout = {int(d.daysMissionTimeout)}")
    if d.priority is not None:
        lines.append(f"{TAB}{TAB}priority = {int(d.priority)}")
    for rule, key in ((d.visible, "visible"), (d.available, "available")):
        inner = _availability_inner_lines(rule)
        if inner:
            lines.append(f"{TAB}{TAB}{key} = {{")
            lines.extend(f"{TAB}{TAB}{TAB}{ln}" for ln in inner)
            lines.append(f"{TAB}{TAB}}}")
    for reward, key, log in (
            (d.completeEffect, "complete_effect", True),
            (d.removeEffect, "remove_effect", True),
            (d.timeoutEffect, "timeout_effect", False)):
        body = export_completion_reward_lines(reward)  # emits at indent 3 already
        if not body and key != "complete_effect":
            continue  # optional effects are omitted when empty
        lines.append(f"{TAB}{TAB}{key} = {{")
        if log:
            stem = "Decision" if key == "complete_effect" else "Decision remove"
            lines.append(f'{TAB}{TAB}{TAB}log = "[GetDateText]: [Root.GetName]: {stem} {d.id}"')
        lines.extend(body)
        lines.append(f"{TAB}{TAB}}}")
    for raw in (d.modifierRawLines or []):
        lines.append(f"{TAB}{TAB}{raw}")
    if d.aiWillDo is not None:
        lines.append(f"{TAB}{TAB}ai_will_do = {{ base = {_format_number(d.aiWillDo)} }}")
    for raw in (d.rawLines or []):
        lines.append(f"{TAB}{TAB}{raw}")
    lines.append(f"{TAB}}}")
    return lines


def export_decisions(project: FocusForgeProject) -> str:
    """common/decisions file: decisions grouped under their category ids (a
    category block may be a custom category from this project or an existing
    MD category — HOI4 merges blocks for the same category across files)."""
    tag = (project.countryTag or "").strip().upper()
    by_category: dict = {}
    for d in project.decisions:
        # Strip BEFORE the fallback so a whitespace-only category can't emit a
        # malformed nameless block; validation flags the missing category too.
        category = (d.category or "").strip() or "uncategorized_decisions"
        by_category.setdefault(category, []).append(d)
    lines: list = []
    for category, decisions in by_category.items():
        lines.append(f"{category} = {{")
        for i, d in enumerate(decisions):
            if i:
                lines.append("")
            lines.extend(_decision_lines(d, tag))
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def export_decision_categories(project: FocusForgeProject) -> str:
    tag = (project.countryTag or "").strip().upper()
    lines: list = []
    for cat in project.decisionCategories:
        lines.append(f"{cat.id} = {{")
        if (cat.icon or "").strip():
            lines.append(f"{TAB}icon = {cat.icon.strip()}")
        if tag:
            lines.append(f"{TAB}allowed = {{ original_tag = {tag} }}")
        if cat.priority is not None:
            lines.append(f"{TAB}priority = {int(cat.priority)}")
        inner = _availability_inner_lines(cat.visible)
        if inner:
            lines.append(f"{TAB}visible = {{")
            lines.extend(f"{TAB}{TAB}{ln}" for ln in inner)
            lines.append(f"{TAB}}}")
        for raw in (cat.rawLines or []):
            lines.append(f"{TAB}{raw}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def export_decision_localisation(project: FocusForgeProject) -> str:
    lines = ["l_english:"]
    for cat in project.decisionCategories:
        lines.append(f' {cat.id}:0 "{_escape_loc(cat.title or cat.id)}"')
        if (cat.description or "").strip():
            lines.append(f' {cat.id}_desc:0 "{_escape_loc(cat.description)}"')
    for d in project.decisions:
        lines.append(f' {d.id}:0 "{_escape_loc(d.title or d.id)}"')
        if (d.description or "").strip():
            lines.append(f' {d.id}_desc:0 "{_escape_loc(d.description)}"')
    return "\n".join(lines) + "\n"


def export_on_actions(project: FocusForgeProject) -> str:
    """on_daily attempts every date-scheduled event once per day; each event's
    own ``date >`` trigger + fire_only_once make it land exactly once on its
    date. on_actions files merge additively across mods, so this coexists with
    Millennium Dawn's own on_actions."""
    lines = ["on_actions = {"]
    lines.append(f"{TAB}on_daily = {{")
    lines.append(f"{TAB}{TAB}events = {{")
    for event in scheduled_events(project):
        lines.append(f"{TAB}{TAB}{TAB}{event.id}")
    lines.append(f"{TAB}{TAB}}}")
    lines.append(f"{TAB}}}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_event_localisation(project: FocusForgeProject) -> str:
    lines = ["l_english:"]
    for event in project.events:
        lines.append(f' {event.id}.t:0 "{_escape_loc(event.title)}"')
        lines.append(f' {event.id}.d:0 "{_escape_loc(event.description)}"')
        for option in event.options:
            lines.append(f' {event.id}.{option.key}:0 "{_escape_loc(option.text)}"')
    return "\n".join(lines) + "\n"


def export_llm_markdown(project: FocusForgeProject) -> str:
    import json
    from .serialization import project_to_dict
    return "\n".join([
        f"# {project.projectName} Focus Forge Project",
        "",
        "Edit this JSON and return the full object. Keep IDs stable unless explicitly renaming a focus.",
        "",
        "```json",
        json.dumps(project_to_dict(project), indent=2, ensure_ascii=False),
        "```",
        "",
    ])


def _escape_loc(value: str) -> str:
    # Literal newlines inside a quoted loc value corrupt the .yml for HOI4 —
    # the game wants the two-character sequence \n instead.
    return ((value or "").replace("\\", "\\\\").replace('"', '\\"')
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))
