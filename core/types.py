from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

RewardParamValue = Union[str, int, float, bool]


def normalize_id_list(value) -> list:
    """Coerce a focus-id list (prerequisites / mutuallyExclusive) into a flat
    list of non-empty, de-duplicated strings.

    Defends against malformed input — most importantly nested lists like
    ``[["focus_a"]]`` that an AI-bridge client (or a hand-edited / older project
    file) can produce. An un-flattened list element is unhashable, which blows
    up every ``x in some_set`` check downstream (graph reconcile, validation,
    chip rendering). Flattening keeps every referenced id; order is preserved."""
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        value = [value]
    out: list = []
    seen: set = set()

    def _walk(v):
        if isinstance(v, (list, tuple, set)):
            for item in v:
                _walk(item)
            return
        s = ("" if v is None else str(v)).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    _walk(value)
    return out


def normalize_prereq_groups(value) -> list:
    """Coerce a focus ``prerequisites`` value into the canonical mixed form: a
    list whose elements are each either a plain id ``str`` (one required focus =
    its own AND prerequisite block) or a ``list[str]`` of >=2 ids (an OR group =
    one prerequisite block listing several ``focus =`` choices).

    This is the OR-aware sibling of :func:`normalize_id_list`. Where that one
    flattens everything (and so destroys OR structure), this preserves exactly
    one level of nesting:

      * ``["a", "b"]``        -> ``["a", "b"]``         (a AND b)
      * ``[["a", "b"]]``      -> ``[["a", "b"]]``       (a OR b)
      * ``[["a", "b"], "c"]`` -> ``[["a", "b"], "c"]``  ((a OR b) AND c)
      * ``[["a"]]``           -> ``["a"]``              (singleton group collapses)
      * ``[["a", "b", "a"]]`` -> ``[["a", "b"]]``       (dedup within a group)

    Ids are de-duplicated *within* each group only, order preserved, blanks
    dropped; exact-duplicate groups (same member set) are dropped. An id is NEVER
    removed just because it also appears in another group — ``[["a","b"], "a"]``
    means (a OR b) AND a, and both blocks must survive (global dedup used to
    silently delete the hard requirement on "a"). Deeper nesting is flattened
    down to a single group level so an OR group can't itself contain groups
    (HOI4 has no such concept)."""
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        value = [value]
    out: list = []
    seen_groups: set = set()   # member sets of already-emitted groups

    def _ids(v, seen: set) -> list:
        # Flatten an arbitrary value to clean id strings, deduped within `seen`
        # (one group's members) only.
        collected: list = []
        if isinstance(v, (list, tuple, set)):
            for item in v:
                collected.extend(_ids(item, seen))
            return collected
        s = ("" if v is None else str(v)).strip()
        if s and s not in seen:
            seen.add(s)
            collected.append(s)
        return collected

    for element in value:
        group = _ids(element, set())          # a plain id is a group of one
        if not group:
            continue                          # empty group / blank id
        key = frozenset(group)
        if key in seen_groups:
            continue                          # exact-duplicate group (same members)
        seen_groups.add(key)
        if len(group) == 1:
            out.append(group[0])              # singleton OR group == plain AND term
        else:
            out.append(group)                 # genuine OR group
    return out


def map_prereq_groups(prerequisites, fn):
    """Rebuild a ``prerequisites`` value applying ``fn`` to every id while keeping
    OR-group structure intact. ``fn(id)`` returns the replacement id, or ``None``
    to drop that id. A group reduced to one id collapses to a plain AND term; an
    emptied group is dropped. Used for rename-remap and delete-strip everywhere
    the prerequisite graph is rewritten."""
    out: list = []
    for element in (prerequisites or []):
        if isinstance(element, (list, tuple, set)):
            group: list = []
            seen: set = set()
            for pid in element:
                if not isinstance(pid, str):
                    continue
                new = fn(pid)
                if new and new not in seen:
                    seen.add(new)
                    group.append(new)
            if len(group) == 1:
                out.append(group[0])
            elif group:
                out.append(group)
        elif isinstance(element, str):
            new = fn(element)
            if new:
                out.append(new)
    return out


def iter_prereq_ids(prerequisites):
    """Yield every focus id referenced by a ``prerequisites`` value, flattening
    OR groups. The order-preserving read view used by everything that only needs
    "what does this point at" (edges, stats, cycle/missing-ref validation)."""
    for element in (prerequisites or []):
        if isinstance(element, (list, tuple, set)):
            for pid in element:
                if isinstance(pid, str):
                    yield pid
        elif isinstance(element, str):
            yield element


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
    bypass: Optional[AvailabilityRule] = None  # conditions that SKIP the focus
    aiWillDo: Optional[float] = None           # AI priority; None = HOI4-default 10
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
    description: str = ""     # in-game leader tooltip text (exported via desc = loc key)


@dataclass
class ElectionLeaderAssignment:
    partyIndex: int = 14       # MD's global party/ruling_party array index
    startDate: str = ""        # year.month.day; first date this leader can apply
    leader: LeaderData = field(default_factory=LeaderData)


@dataclass
class CountryData:
    popularities: dict = field(default_factory=dict)   # {top_ideology: float}
    rulingParty: str = "neutrality"                     # a top ideology
    lastElection: str = ""
    electionFrequency: int = 48
    electionsAllowed: bool = True
    parties: list = field(default_factory=list)         # list[PartyData]
    leaders: list = field(default_factory=list)         # list[LeaderData]
    electionLeaders: list = field(default_factory=list) # list[ElectionLeaderAssignment]
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
    includeDecisions: bool = False


@dataclass
class DecisionCategory:
    """A decisions-panel category authored by this project. Decisions can also
    target an existing MD category by id instead."""
    id: str = ""
    title: str = ""
    description: str = ""
    icon: str = "GFX_decision_category_generic_political_actions"
    priority: Optional[int] = None         # panel sort order; None = omit
    visible: Optional[AvailabilityRule] = None
    rawLines: list = field(default_factory=list)   # extra category fields, verbatim


@dataclass
class DecisionData:
    id: str = ""
    title: str = ""
    description: str = ""
    category: str = ""                     # custom category id, or an MD one
    icon: str = ""                         # GFX_decision_* sprite
    iconData: str = ""                     # base64 PNG of a custom imported icon (overrides icon)
    cost: Optional[float] = 25             # political power; None = omit
    fireOnlyOnce: bool = False
    isGood: Optional[bool] = None          # mission tint (green/red); None = omit
    daysRemove: Optional[int] = None       # active-timer days → remove_effect
    daysReEnable: Optional[int] = None     # cooldown before it can be retaken
    daysMissionTimeout: Optional[int] = None  # mission countdown → timeout_effect
    aiWillDo: Optional[float] = None       # AI base weighting; None = omit
    priority: Optional[int] = None         # sort within the category; None = omit
    visible: Optional[AvailabilityRule] = None    # shown in the panel
    available: Optional[AvailabilityRule] = None  # selectable
    completeEffect: Optional[CompletionReward] = None  # on select
    removeEffect: Optional[CompletionReward] = None    # when days_remove ends
    timeoutEffect: Optional[CompletionReward] = None   # when a mission times out
    modifierRawLines: list = field(default_factory=list)  # modifier = { … } lines
    rawLines: list = field(default_factory=list)   # any extra decision fields, verbatim


@dataclass
class FocusShortcut:
    """A focus-tree branch bookmark (the in-game bottom-left shortcut buttons).

    Exported as a ``shortcut = { }`` block at the top of the focus_tree, a
    sibling of the focus blocks. HOI4 shows at most 8 shortcut slots."""
    label: str = ""                        # the button text (written to loc under a generated key)
    target: str = ""                       # focus id the camera jumps to
    zoomFactor: Optional[float] = None     # → scroll_wheel_factor; None = omit the line
    triggerRawLines: list = field(default_factory=list)  # verbatim trigger body lines; empty = omit


@dataclass
class FocusForgeProject:
    projectName: str = ""
    countryTag: str = ""
    treeId: str = ""
    continuousFocusPosition: FocusPosition = field(default_factory=FocusPosition)
    focuses: list = field(default_factory=list)
    ideas: list = field(default_factory=list)
    events: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    decisionCategories: list = field(default_factory=list)
    shortcuts: list = field(default_factory=list)
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
