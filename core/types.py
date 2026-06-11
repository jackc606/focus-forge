from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

RewardParamValue = Union[str, int, float, bool]


@dataclass
class FocusPosition:
    x: float = 0
    y: float = 0


@dataclass
class EventReward:
    id: str = ""
    days: Optional[int] = None


@dataclass
class TechBonusReward:
    category: str = ""
    bonus: float = 0
    uses: int = 0
    name: Optional[str] = None


@dataclass
class RewardItem:
    kind: str = ""
    params: dict = field(default_factory=dict)
    enabled: Optional[bool] = None


@dataclass
class CompletionReward:
    politicalPower: Optional[float] = None
    stability: Optional[float] = None
    warSupport: Optional[float] = None
    commandPower: Optional[float] = None
    armyExperience: Optional[float] = None
    airExperience: Optional[float] = None
    navyExperience: Optional[float] = None
    addIdeas: Optional[list] = None
    removeIdeas: Optional[list] = None
    events: Optional[list] = None
    techBonuses: Optional[list] = None
    items: Optional[list] = None
    rawLines: Optional[list] = None


@dataclass
class AvailabilityRule:
    completedFocuses: Optional[list] = None
    flagsRequired: Optional[list] = None
    flagsBlocked: Optional[list] = None
    items: Optional[list] = None  # list[RewardItem] — availability condition presets
    rawLines: Optional[list] = None


@dataclass
class FocusNodeData:
    id: str = ""
    title: str = ""
    description: str = ""
    icon: str = ""
    iconData: str = ""  # base64 PNG of a custom imported icon (overrides icon)
    position: FocusPosition = field(default_factory=FocusPosition)
    cost: float = 5
    filters: list = field(default_factory=list)
    prerequisites: list = field(default_factory=list)
    mutuallyExclusive: list = field(default_factory=list)
    completionReward: CompletionReward = field(default_factory=CompletionReward)
    available: Optional[AvailabilityRule] = None
    notes: Optional[str] = None


@dataclass
class IdeaData:
    id: str = ""
    title: str = ""
    description: str = ""
    picture: str = ""
    modifierRawLines: list = field(default_factory=list)


@dataclass
class EventOption:
    key: str = ""
    text: str = ""
    items: Optional[list] = None                  # list[RewardItem] — structured effects (reward presets)
    trigger: Optional[AvailabilityRule] = None    # per-option visibility trigger (availability presets)
    aiChance: Optional[float] = None              # → ai_chance = { base = N }
    effectRawLines: list = field(default_factory=list)  # raw effect escape hatch (back-compat)


@dataclass
class EventData:
    id: str = ""
    title: str = ""
    description: str = ""
    picture: str = "GFX_report_event_generic_parliament"
    pictureData: str = ""                         # base64 PNG of a custom event picture
    eventType: str = "country_event"              # 'country_event' | 'news_event'
    isTriggeredOnly: bool = True
    hidden: bool = False
    major: bool = False
    fireOnlyOnce: bool = False
    meanTimeToHappen: Optional[int] = None        # days; only meaningful when not triggered-only
    fireOnDate: str = ""                          # 'year.month.day' — fire exactly on this date
    trigger: Optional[AvailabilityRule] = None    # event-level fire trigger
    options: list = field(default_factory=list)


@dataclass
class PartyData:
    ideology: str = ""   # top ideology (democratic/communism/fascism/neutrality/nationalist)
    name: str = ""
    longName: str = ""
    subIdeology: str = ""  # MD sub-ideology token — keys the party-logo/description loc
    logoRef: str = ""      # preset MD party-icon sprite name (GFX_…)
    logoData: str = ""     # base64 PNG of a custom party logo
    description: str = ""  # MD party description (<TAG>.<sub>_desc), shown in politics


@dataclass
class LeaderData:
    name: str = ""
    ideology: str = ""        # a sub-ideology token
    traits: list = field(default_factory=list)
    pictureRef: str = ""      # preset portrait filename / sprite
    pictureData: str = ""     # base64 PNG of a custom portrait


@dataclass
class CountryData:
    popularities: dict = field(default_factory=dict)   # {top_ideology: float}
    rulingParty: str = "neutrality"                     # a top ideology
    lastElection: str = ""
    electionFrequency: int = 48
    electionsAllowed: bool = True
    parties: list = field(default_factory=list)         # list[PartyData]
    leaders: list = field(default_factory=list)         # list[LeaderData]
    flagMain: str = ""                                  # base64 PNG
    flagVariants: dict = field(default_factory=dict)    # {top_ideology: base64 PNG}


@dataclass
class ExportSettings:
    modPrefix: str = ""
    focusFileName: str = ""
    localisationPrefix: str = ""
    includeIdeas: bool = False
    includeEvents: bool = False
    includeCountry: bool = False


@dataclass
class FocusForgeProject:
    projectName: str = ""
    countryTag: str = ""
    treeId: str = ""
    continuousFocusPosition: FocusPosition = field(default_factory=FocusPosition)
    focuses: list = field(default_factory=list)
    ideas: list = field(default_factory=list)
    events: list = field(default_factory=list)
    exportSettings: ExportSettings = field(default_factory=ExportSettings)
    country: Optional["CountryData"] = None
    # Where "Export to Mod" publishes (absolute HOI4 mod folder) and the
    # descriptor metadata used to scaffold that folder on first export.
    exportDir: str = ""
    modMeta: dict = field(default_factory=dict)
    schemaVersion: int = 1
    app: str = "Focus Forge"
    mode: str = "millennium-dawn"


@dataclass
class ValidationIssue:
    severity: str = "error"  # 'error' | 'warning'
    code: str = ""
    message: str = ""
    focusId: Optional[str] = None


@dataclass
class ExportedFile:
    relativePath: str = ""
    content: str = ""
    bom: bool = False
