"""HOI4 / Millennium Dawn export — ported from exporters.ts. Byte-identical to TS output."""
from __future__ import annotations

import re

from .availability_presets import build_availability_item_lines
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
    if settings.includeCountry and project.country:
        files.append(ExportedFile(
            relativePath=f"history/countries/{project.countryTag} - {project.projectName or project.countryTag}.txt",
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
    return files


def _party_key(tag: str, ideology: str) -> str:
    return f"{tag}_{ideology}_party"


def export_country_history(project: FocusForgeProject) -> str:
    c = project.country
    tag = project.countryTag
    lines: list = []
    if c.popularities:
        lines.append("set_popularities = {")
        for ideo in ("democratic", "communism", "fascism", "neutrality", "nationalist"):
            if ideo in c.popularities:
                v = c.popularities[ideo]
                n = int(v) if float(v).is_integer() else v  # keep MD's decimals, drop .0
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
        if leader.pictureData:
            picture = f"{_leader_slug(leader)}.dds"
        elif _is_portrait_path(leader.pictureRef):
            picture = _portrait_sprite_name(tag, leader)  # generated sprite (see below)
        else:
            picture = leader.pictureRef or ""
        lines.append("create_country_leader = {")
        lines.append(f'{TAB}name = "{_escape_loc(leader.name)}"')
        if picture:
            lines.append(f'{TAB}picture = "{picture}"')
        lines.append(f"{TAB}ideology = {leader.ideology}")
        if leader.traits:
            lines.append(f"{TAB}traits = {{ {' '.join(leader.traits)} }}")
        lines.append("}")
    return "\n".join(lines) + "\n"


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SAN_RE = re.compile(r"[^A-Za-z0-9]+")


def _leader_slug(leader) -> str:
    return _SLUG_RE.sub("_", (leader.name or "leader").lower()).strip("_") or "leader"


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


def _portrait_sprite_name(tag, leader) -> str:
    return f"GFX_{(tag or '').upper()}_{_leader_slug(leader)}"


def export_leader_portrait_sprites(project) -> "str | None":
    """interface/*.gfx spriteTypes wrapping each MD-image portrait a leader picked,
    so ``create_country_leader { picture = GFX_… }`` resolves. None if there are
    no image-path portraits. The texturefile points at MD's existing image (MD is
    a dependency), so no .dds copy is needed."""
    c = project.country
    if not c:
        return None
    tag = project.countryTag
    entries = [(_portrait_sprite_name(tag, ld), ld.pictureRef.replace("\\", "/"))
               for ld in c.leaders if _is_portrait_path(ld.pictureRef)]
    if not entries:
        return None
    lines = ["spriteTypes = {"]
    for name, tex in entries:
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
    return "\n".join(lines) + "\n"


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
        f"{TAB}{TAB}icon = {_focus_icon_value(focus)}",
        f"{TAB}{TAB}x = {focus.position.x}",
        f"{TAB}{TAB}y = {focus.position.y}",
        f"{TAB}{TAB}cost = {focus.cost}",
    ]
    for prereq in focus.prerequisites:
        lines.append(f"{TAB}{TAB}prerequisite = {{ focus = {prereq} }}")
    for exclusive in focus.mutuallyExclusive:
        lines.append(f"{TAB}{TAB}mutually_exclusive = {{ focus = {exclusive} }}")

    if focus.available and _has_availability(focus.available):
        lines.append(f"{TAB}{TAB}available = {{")
        for line in _availability_inner_lines(focus.available):
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
    lines.append(f"{TAB}{TAB}ai_will_do = {{")
    lines.append(f"{TAB}{TAB}{TAB}base = 10")
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
    return "\n".join(lines) + "\n"


def export_ideas(project: FocusForgeProject) -> str:
    lines = ["ideas = {", f"{TAB}country = {{"]
    for idea in project.ideas:
        lines.append(f"{TAB}{TAB}{idea.id} = {{")
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
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')
