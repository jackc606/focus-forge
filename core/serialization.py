"""JSON round-trip — strips None and empty optional fields to match TS JSON.stringify."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from .ideologies import canonical_sub_ideology, rename_legacy_ideology_tokens
from .types import (
    AiModifier,
    AvailabilityRule,
    CompletionReward,
    CountryData,
    DecisionCategory,
    DecisionData,
    ElectionLeaderAssignment,
    EventData,
    EventOption,
    EventReward,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    FocusShortcut,
    FocusTreeData,
    IdeaData,
    LeaderData,
    PartyData,
    RewardItem,
    TechBonusReward,
    normalize_id_list,
    normalize_prereq_groups,
)

# ----- Serialize ---------------------------------------------------------------

# Optional fields that should be omitted from JSON when None.
_OPTIONAL_FIELDS = {
    FocusNodeData: {"available", "bypass", "aiWillDo", "aiModifiers", "notes"},
    AiModifier: {"factor", "add", "trigger"},
    CompletionReward: {
        "politicalPower", "stability", "warSupport", "commandPower",
        "armyExperience", "airExperience", "navyExperience",
        "addIdeas", "removeIdeas", "events", "techBonuses", "items", "rawLines",
    },
    AvailabilityRule: {"completedFocuses", "flagsRequired", "flagsBlocked", "items", "rawLines"},
    EventReward: {"days"},
    EventOption: {"items", "trigger", "aiChance"},
    EventData: {"meanTimeToHappen", "fireOnDate", "trigger"},
    TechBonusReward: {"name"},
    RewardItem: {"enabled"},
    DecisionCategory: {"priority", "visible"},
    DecisionData: {"cost", "isGood", "daysRemove", "daysReEnable",
                   "daysMissionTimeout", "aiWillDo", "priority", "visible",
                   "available", "completeEffect", "removeEffect", "timeoutEffect"},
    FocusForgeProject: {"country"},
}


# Fields added after the format was established: omitted whenever they hold
# their empty default (None / False / [] / 0), so a project that doesn't use
# them — every single-tree project — serializes exactly as it always did.
_OMIT_WHEN_EMPTY = {
    FocusNodeData: {"shared", "relativePositionId", "offsets", "appliedOffset",
                    "extraRawLines"},
    FocusForgeProject: {"otherTrees", "activeTreeIndex", "sharedPool",
                        "countryRawLines", "sharedFocusRefs", "treeRawLines"},
    FocusTreeData: {"shortcuts", "countryRawLines", "sharedFocusRefs", "extraRawLines"},
}


def _to_plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if is_dataclass(value):
        out: dict = {}
        optional = _OPTIONAL_FIELDS.get(type(value), set())
        omit_empty = _OMIT_WHEN_EMPTY.get(type(value))
        for f in fields(value):
            v = getattr(value, f.name)
            if (v is None or v == "") and f.name in optional:
                continue
            if omit_empty and f.name in omit_empty and not v:
                continue
            out[f.name] = _to_plain(v)
        return out
    return value


def project_to_dict(project: FocusForgeProject) -> dict:
    return _to_plain(project)


def focus_to_dict(focus: FocusNodeData) -> dict:
    """One focus as a plain dict — used by the clipboard copy/paste payload."""
    return _to_plain(focus)


def focus_from_dict(d: dict) -> FocusNodeData:
    return _focus_from_dict(d)


# ----- Deserialize -------------------------------------------------------------

def _opt_list(d: dict, key: str):
    """Optional-list field: JSON ``null`` (or an absent key) -> None, otherwise a
    real list. ``"key" in d`` + ``list(d["key"])`` crashed on null and made the
    whole project unloadable."""
    v = d.get(key)
    return None if v is None else list(v)


def _coerce_int(value, fallback: int = 0) -> int:
    """Coerce a possibly corrupt value ('9', 9.0) to int; bad value -> fallback.
    Heals project files poisoned with non-numeric positions on load."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _coerce_float(value, fallback: float = 0.0):
    """Numeric coercion that keeps an already-numeric value exactly as-is (an
    int stays an int, so re-saving doesn't churn 5 into 5.0)."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_popularity(value):
    """Popularity values must be numeric or validate/export crash. Keeps ints/
    floats as-is, heals '40' / '40%' strings, and falls back to 0.0 otherwise."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return 0.0


def _idea_from_dict(d: dict) -> IdeaData:
    return IdeaData(
        id=d.get("id", ""),
        title=d.get("title", ""),
        description=d.get("description", ""),
        picture=d.get("picture", ""),
        modifierRawLines=list(d.get("modifierRawLines") or []),
    )


def _event_option_from_dict(d: dict) -> EventOption:
    return EventOption(
        key=d.get("key", ""),
        text=d.get("text", ""),
        items=[_reward_item_from_dict(i) for i in d["items"]] if d.get("items") else None,
        trigger=_availability_from_dict(d["trigger"]) if d.get("trigger") else None,
        aiChance=d.get("aiChance"),
        effectRawLines=list(d.get("effectRawLines") or []),
    )


def _event_from_dict(d: dict) -> EventData:
    return EventData(
        id=d.get("id", ""),
        title=d.get("title", ""),
        description=d.get("description", ""),
        picture=d.get("picture", "GFX_report_event_generic_parliament"),
        pictureData=d.get("pictureData", ""),
        eventType=d.get("eventType", "country_event"),
        isTriggeredOnly=bool(d.get("isTriggeredOnly", True)),
        hidden=bool(d.get("hidden", False)),
        major=bool(d.get("major", False)),
        fireOnlyOnce=bool(d.get("fireOnlyOnce", False)),
        meanTimeToHappen=d.get("meanTimeToHappen"),
        fireOnDate=d.get("fireOnDate", "") or "",
        trigger=_availability_from_dict(d["trigger"]) if d.get("trigger") else None,
        options=[_event_option_from_dict(o) for o in (d.get("options") or [])],
    )


def _availability_from_dict(d: dict) -> AvailabilityRule:
    items = _opt_list(d, "items")
    return AvailabilityRule(
        completedFocuses=_opt_list(d, "completedFocuses"),
        flagsRequired=_opt_list(d, "flagsRequired"),
        flagsBlocked=_opt_list(d, "flagsBlocked"),
        items=[_reward_item_from_dict(i) for i in items] if items is not None else None,
        rawLines=_opt_list(d, "rawLines"),
    )


def _reward_item_from_dict(d: dict) -> RewardItem:
    return RewardItem(
        kind=d.get("kind", ""),
        params=dict(d.get("params") or {}),
        enabled=d.get("enabled"),
    )


def _event_reward_from_dict(d: dict) -> EventReward:
    return EventReward(id=d.get("id", ""), days=d.get("days"))


def _tech_bonus_from_dict(d: dict) -> TechBonusReward:
    return TechBonusReward(
        category=d.get("category", ""),
        bonus=float(d.get("bonus") or 0),
        uses=int(d.get("uses") or 0),
        name=d.get("name"),
    )


def _completion_reward_from_dict(d: dict) -> CompletionReward:
    events = _opt_list(d, "events")
    tech_bonuses = _opt_list(d, "techBonuses")
    items = _opt_list(d, "items")
    return CompletionReward(
        politicalPower=d.get("politicalPower"),
        stability=d.get("stability"),
        warSupport=d.get("warSupport"),
        commandPower=d.get("commandPower"),
        armyExperience=d.get("armyExperience"),
        airExperience=d.get("airExperience"),
        navyExperience=d.get("navyExperience"),
        addIdeas=_opt_list(d, "addIdeas"),
        removeIdeas=_opt_list(d, "removeIdeas"),
        events=[_event_reward_from_dict(e) for e in events] if events is not None else None,
        techBonuses=[_tech_bonus_from_dict(b) for b in tech_bonuses] if tech_bonuses is not None else None,
        items=[_reward_item_from_dict(i) for i in items] if items is not None else None,
        rawLines=_opt_list(d, "rawLines"),
    )


def _focus_from_dict(d: dict) -> FocusNodeData:
    pos = d.get("position") or {}
    return FocusNodeData(
        id=d.get("id", ""),
        title=d.get("title", ""),
        description=d.get("description", ""),
        icon=d.get("icon", ""),
        iconData=d.get("iconData", ""),
        position=FocusPosition(x=_coerce_int(pos.get("x", 0)),
                               y=_coerce_int(pos.get("y", 0))),
        cost=_coerce_float(d.get("cost", 5), 5.0),
        filters=list(d.get("filters") or []),
        prerequisites=normalize_prereq_groups(d.get("prerequisites")),
        mutuallyExclusive=normalize_id_list(d.get("mutuallyExclusive")),
        completionReward=_completion_reward_from_dict(d.get("completionReward") or {}),
        available=_availability_from_dict(d["available"]) if d.get("available") else None,
        bypass=_availability_from_dict(d["bypass"]) if d.get("bypass") else None,
        aiWillDo=d.get("aiWillDo"),
        aiModifiers=([_ai_modifier_from_dict(m) for m in d["aiModifiers"] if isinstance(m, dict)]
                     if d.get("aiModifiers") else None),
        notes=d.get("notes"),
        shared=bool(d.get("shared", False)),
        relativePositionId=(str(d["relativePositionId"])
                            if d.get("relativePositionId") else None),
        offsets=_offsets_from(d.get("offsets")),
        appliedOffset=_applied_offset_from(d.get("appliedOffset")),
        extraRawLines=_str_list(d.get("extraRawLines")) or None,
    )


def _str_list(value) -> list:
    """A list of strings from a possibly absent/corrupt value."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v is not None]


def _offsets_from(value):
    """``offsets``: a list of offset blocks, each a list of raw lines. A block
    given as one string is accepted as a one-line block."""
    if not isinstance(value, (list, tuple)):
        return None
    out = []
    for block in value:
        lines = [block] if isinstance(block, str) else _str_list(block)
        if lines:
            out.append(lines)
    return out or None


def _applied_offset_from(value):
    if not isinstance(value, dict):
        return None
    x, y = _coerce_int(value.get("x", 0)), _coerce_int(value.get("y", 0))
    return FocusPosition(x=x, y=y) if (x or y) else None


def _tree_from_dict(d: dict) -> FocusTreeData:
    cfp = d.get("continuousFocusPosition") or {}
    return FocusTreeData(
        treeId=str(d.get("treeId", "") or ""),
        focuses=[_focus_from_dict(f) for f in (d.get("focuses") or [])],
        shortcuts=[_shortcut_from_dict(s) for s in (d.get("shortcuts") or [])],
        continuousFocusPosition=FocusPosition(x=_coerce_int(cfp.get("x", 0)),
                                              y=_coerce_int(cfp.get("y", 0))),
        countryRawLines=_str_list(d.get("countryRawLines")),
        sharedFocusRefs=normalize_id_list(d.get("sharedFocusRefs")),
        extraRawLines=_str_list(d.get("extraRawLines")),
    )


def _ai_modifier_from_dict(d: dict) -> AiModifier:
    def num(v):
        if v is None or isinstance(v, bool):
            return None
        try:
            return v if isinstance(v, (int, float)) else float(v)
        except (TypeError, ValueError):
            return None
    return AiModifier(
        factor=num(d.get("factor")),
        add=num(d.get("add")),
        trigger=_availability_from_dict(d["trigger"]) if d.get("trigger") else None,
    )


def _export_settings_from_dict(d: dict) -> ExportSettings:
    return ExportSettings(
        modPrefix=d.get("modPrefix", ""),
        focusFileName=d.get("focusFileName", ""),
        localisationPrefix=d.get("localisationPrefix", ""),
        includeIdeas=bool(d.get("includeIdeas", False)),
        includeEvents=bool(d.get("includeEvents", False)),
        includeCountry=bool(d.get("includeCountry", False)),
        includeDecisions=bool(d.get("includeDecisions", False)),
    )


def _party_from_dict(d: dict) -> PartyData:
    return PartyData(ideology=d.get("ideology", ""), name=d.get("name", ""),
                     longName=d.get("longName", ""),
                     # MD renames sub-ideologies (2.0.2: Communist-State) — map forward.
                     subIdeology=canonical_sub_ideology(d.get("subIdeology", "")),
                     logoRef=d.get("logoRef", ""), logoData=d.get("logoData", ""),
                     description=d.get("description", ""))


def _leader_from_dict(d: dict) -> LeaderData:
    return LeaderData(
        name=d.get("name", ""), ideology=canonical_sub_ideology(d.get("ideology", "")),
        traits=[rename_legacy_ideology_tokens(t)[0] if isinstance(t, str) else t
                for t in (d.get("traits") or [])],
        pictureRef=d.get("pictureRef", ""), pictureData=d.get("pictureData", ""),
        description=d.get("description", ""))


def _election_leader_from_dict(d: dict) -> ElectionLeaderAssignment:
    try:
        party_index = int(float(d.get("partyIndex", 14)))
    except (TypeError, ValueError):
        party_index = 14
    return ElectionLeaderAssignment(
        partyIndex=party_index,
        startDate=d.get("startDate", "") or "",
        leader=_leader_from_dict(d.get("leader") or {}),
    )


def _country_from_dict(d: dict) -> CountryData:
    return CountryData(
        popularities={k: _coerce_popularity(v)
                      for k, v in (d.get("popularities") or {}).items()},
        rulingParty=d.get("rulingParty", "neutrality"),
        lastElection=d.get("lastElection", ""),
        electionFrequency=int(d.get("electionFrequency", 48)),
        electionsAllowed=bool(d.get("electionsAllowed", True)),
        parties=[_party_from_dict(p) for p in (d.get("parties") or [])],
        leaders=[_leader_from_dict(le) for le in (d.get("leaders") or [])],
        electionLeaders=[_election_leader_from_dict(le)
                         for le in (d.get("electionLeaders") or [])],
        flagMain=d.get("flagMain", ""),
        flagVariants=dict(d.get("flagVariants") or {}),
    )


def _decision_category_from_dict(d: dict) -> DecisionCategory:
    return DecisionCategory(
        id=d.get("id", ""),
        title=d.get("title", ""),
        description=d.get("description", ""),
        icon=d.get("icon", "GFX_decision_category_generic_political_actions"),
        priority=_num_or_none(d.get("priority"), int),
        visible=_availability_from_dict(d["visible"]) if d.get("visible") else None,
        rawLines=list(d.get("rawLines") or []),
    )


def _num_or_none(value, cast):
    """Coerce a possibly bridge-supplied value ('90', '90.5', 90) or fall back
    to None — downstream int()/float()/format calls must never crash the GUI."""
    if value is None or value == "":
        return None
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return None


def _shortcut_from_dict(d: dict) -> FocusShortcut:
    zoom = d.get("zoomFactor")
    return FocusShortcut(
        label=d.get("label", "") or "",
        target=d.get("target", "") or "",
        # Keep an absent/null zoom as None (omits scroll_wheel_factor on export);
        # only coerce a value that's actually present so we don't churn None → 0.0.
        zoomFactor=None if zoom is None else _coerce_float(zoom),
        triggerRawLines=list(_opt_list(d, "triggerRawLines") or []),
    )


def _decision_from_dict(d: dict) -> DecisionData:
    def _reward(key):
        return _completion_reward_from_dict(d[key]) if d.get(key) else None

    return DecisionData(
        id=d.get("id", ""),
        title=d.get("title", ""),
        description=d.get("description", ""),
        category=d.get("category", ""),
        icon=d.get("icon", ""),
        iconData=d.get("iconData", ""),
        cost=_num_or_none(d.get("cost"), float),
        fireOnlyOnce=bool(d.get("fireOnlyOnce", False)),
        isGood=d.get("isGood"),
        daysRemove=_num_or_none(d.get("daysRemove"), int),
        daysReEnable=_num_or_none(d.get("daysReEnable"), int),
        daysMissionTimeout=_num_or_none(d.get("daysMissionTimeout"), int),
        aiWillDo=_num_or_none(d.get("aiWillDo"), float),
        priority=_num_or_none(d.get("priority"), int),
        visible=_availability_from_dict(d["visible"]) if d.get("visible") else None,
        available=_availability_from_dict(d["available"]) if d.get("available") else None,
        completeEffect=_reward("completeEffect"),
        removeEffect=_reward("removeEffect"),
        timeoutEffect=_reward("timeoutEffect"),
        modifierRawLines=list(d.get("modifierRawLines") or []),
        rawLines=list(d.get("rawLines") or []),
    )


def project_from_dict(d: dict) -> FocusForgeProject:
    cfp = d.get("continuousFocusPosition") or {}
    return FocusForgeProject(
        projectName=d.get("projectName", ""),
        countryTag=d.get("countryTag", ""),
        treeId=d.get("treeId", ""),
        continuousFocusPosition=FocusPosition(x=_coerce_int(cfp.get("x", 0)),
                                              y=_coerce_int(cfp.get("y", 0))),
        focuses=[_focus_from_dict(f) for f in (d.get("focuses") or [])],
        ideas=[_idea_from_dict(i) for i in (d.get("ideas") or [])],
        events=[_event_from_dict(e) for e in (d.get("events") or [])],
        decisions=[_decision_from_dict(x) for x in (d.get("decisions") or [])],
        decisionCategories=[_decision_category_from_dict(x)
                            for x in (d.get("decisionCategories") or [])],
        shortcuts=[_shortcut_from_dict(s) for s in (d.get("shortcuts") or [])],
        exportSettings=_export_settings_from_dict(d.get("exportSettings") or {}),
        country=_country_from_dict(d["country"]) if d.get("country") else None,
        exportDir=d.get("exportDir", ""),
        modMeta=dict(d.get("modMeta") or {}),
        schemaVersion=int(d.get("schemaVersion", 1)),
        app=str(d.get("app", "Focus Forge")),
        mode=str(d.get("mode", "millennium-dawn")),
        mdEdition=str(d.get("mdEdition", "main") or "main"),
        source=dict(d.get("source") or {}),
        otherTrees=[_tree_from_dict(t) for t in (d.get("otherTrees") or [])
                    if isinstance(t, dict)],
        activeTreeIndex=max(0, _coerce_int(d.get("activeTreeIndex", 0))),
        sharedPool=[_focus_from_dict(f) for f in (d.get("sharedPool") or [])
                    if isinstance(f, dict)],
        countryRawLines=_str_list(d.get("countryRawLines")),
        sharedFocusRefs=normalize_id_list(d.get("sharedFocusRefs")),
        treeRawLines=_str_list(d.get("treeRawLines")),
    )
