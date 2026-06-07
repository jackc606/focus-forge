"""HOI4 / Millennium Dawn export — ported from exporters.ts. Byte-identical to TS output."""
from __future__ import annotations

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


def _leader_slug(leader) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", (leader.name or "leader").lower()).strip("_") or "leader"


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
        f"{TAB}{TAB}icon = {focus.icon}",
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
        for completed in (focus.available.completedFocuses or []):
            lines.append(f"{TAB}{TAB}{TAB}has_completed_focus = {completed}")
        for flag in (focus.available.flagsRequired or []):
            lines.append(f"{TAB}{TAB}{TAB}has_country_flag = {flag}")
        for flag in (focus.available.flagsBlocked or []):
            lines.append(f"{TAB}{TAB}{TAB}NOT = {{ has_country_flag = {flag} }}")
        for item in (focus.available.items or []):
            for line in build_availability_item_lines(item):
                lines.append(f"{TAB}{TAB}{TAB}{line}")
        for raw in (focus.available.rawLines or []):
            lines.append(f"{TAB}{TAB}{TAB}{raw}")
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
        lines.append(f"{TAB}{TAB}{TAB}add_political_power = {reward.politicalPower}")
    if reward.stability:
        lines.append(f"{TAB}{TAB}{TAB}add_stability = {_format_number(reward.stability)}")
    if reward.warSupport:
        lines.append(f"{TAB}{TAB}{TAB}add_war_support = {_format_number(reward.warSupport)}")
    if reward.commandPower:
        lines.append(f"{TAB}{TAB}{TAB}add_command_power = {reward.commandPower}")
    if reward.armyExperience:
        lines.append(f"{TAB}{TAB}{TAB}army_experience = {reward.armyExperience}")
    if reward.airExperience:
        lines.append(f"{TAB}{TAB}{TAB}air_experience = {reward.airExperience}")
    if reward.navyExperience:
        lines.append(f"{TAB}{TAB}{TAB}navy_experience = {reward.navyExperience}")
    for idea in (reward.addIdeas or []):
        lines.append(f"{TAB}{TAB}{TAB}add_ideas = {idea}")
    for idea in (reward.removeIdeas or []):
        lines.append(f"{TAB}{TAB}{TAB}remove_ideas = {idea}")
    for event in (reward.events or []):
        days = "" if (getattr(event, "days", None) is None) else f" days = {event.days}"
        lines.append(f"{TAB}{TAB}{TAB}country_event = {{ id = {event.id}{days} }}")
    for bonus in (reward.techBonuses or []):
        lines.append(f"{TAB}{TAB}{TAB}add_tech_bonus = {{")
        if getattr(bonus, "name", None):
            lines.append(f"{TAB}{TAB}{TAB}{TAB}name = {bonus.name}")
        lines.append(f"{TAB}{TAB}{TAB}{TAB}bonus = {_format_number(bonus.bonus)}")
        lines.append(f"{TAB}{TAB}{TAB}{TAB}uses = {bonus.uses}")
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


def export_events(project: FocusForgeProject) -> str:
    lines = [f"add_namespace = {project.exportSettings.localisationPrefix}"]
    for event in project.events:
        lines.append("")
        lines.append("country_event = {")
        lines.append(f"{TAB}id = {event.id}")
        lines.append(f"{TAB}title = {event.id}.t")
        lines.append(f"{TAB}desc = {event.id}.d")
        lines.append(f"{TAB}picture = GFX_report_event_generic_parliament")
        for option in event.options:
            lines.append("")
            lines.append(f"{TAB}option = {{")
            lines.append(f"{TAB}{TAB}name = {event.id}.{option.key}")
            for raw in option.effectRawLines:
                lines.append(f"{TAB}{TAB}{raw}")
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
