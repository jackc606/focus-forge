"""Base tree generator — ported from baseTree.ts. Produces 21 placeholder focuses."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .country_tags import MD_COUNTRY_TAGS
from .types import CompletionReward, FocusForgeProject, FocusNodeData, FocusPosition


@dataclass
class _BaseFocusTemplate:
    idSuffix: str
    title: str
    x: int
    y: int
    icon: str
    filters: list
    prerequisite: str = ""


_BASE_TEMPLATES: list[_BaseFocusTemplate] = [
    _BaseFocusTemplate("focus_001", "Unnamed Focus 001", 0, 0, "MEX_Mexican_government", ["FOCUS_FILTER_POLITICAL"]),
    _BaseFocusTemplate("political_001", "Unnamed Political Focus 001", -8, 2, "support_democracy", ["FOCUS_FILTER_POLITICAL"], "focus_001"),
    _BaseFocusTemplate("political_002", "Unnamed Political Focus 002", -8, 4, "political_reform", ["FOCUS_FILTER_POLITICAL", "FOCUS_FILTER_STABILITY"], "political_001"),
    _BaseFocusTemplate("political_003", "Unnamed Political Focus 003", -10, 6, "nationalist_administration", ["FOCUS_FILTER_POLITICAL"], "political_002"),
    _BaseFocusTemplate("political_004", "Unnamed Political Focus 004", -6, 6, "communism", ["FOCUS_FILTER_POLITICAL"], "political_002"),
    _BaseFocusTemplate("economic_001", "Unnamed Economic Focus 001", -4, 2, "MEX_Economic_reform", ["FOCUS_FILTER_ECONOMY", "FOCUS_FILTER_INDUSTRY"], "focus_001"),
    _BaseFocusTemplate("economic_002", "Unnamed Economic Focus 002", -4, 4, "industry", ["FOCUS_FILTER_ECONOMY", "FOCUS_FILTER_INDUSTRY"], "economic_001"),
    _BaseFocusTemplate("economic_003", "Unnamed Economic Focus 003", -5, 6, "construct_infrastructure", ["FOCUS_FILTER_ECONOMY"], "economic_002"),
    _BaseFocusTemplate("economic_004", "Unnamed Economic Focus 004", -3, 6, "focus_trade_republic", ["FOCUS_FILTER_ECONOMY", "FOCUS_FILTER_TRADE"], "economic_002"),
    _BaseFocusTemplate("military_001", "Unnamed Military Focus 001", 0, 2, "army_reform", ["FOCUS_FILTER_ARMY"], "focus_001"),
    _BaseFocusTemplate("military_002", "Unnamed Army Focus 001", -1, 4, "military_planning", ["FOCUS_FILTER_ARMY"], "military_001"),
    _BaseFocusTemplate("military_003", "Unnamed Air Focus 001", 1, 4, "modern_fighter", ["FOCUS_FILTER_AIR"], "military_001"),
    _BaseFocusTemplate("military_004", "Unnamed Naval Focus 001", 0, 6, "MEX_The_Mexican_navy", ["FOCUS_FILTER_NAVY"], "military_001"),
    _BaseFocusTemplate("foreign_001", "Unnamed Foreign Focus 001", 4, 2, "align_to_mexico", ["FOCUS_FILTER_FOREIGN_POLICY"], "focus_001"),
    _BaseFocusTemplate("foreign_002", "Unnamed Western Focus 001", 3, 4, "support_democracy", ["FOCUS_FILTER_FOREIGN_POLICY"], "foreign_001"),
    _BaseFocusTemplate("foreign_003", "Unnamed Eastern Focus 001", 5, 4, "align_to_venezuela", ["FOCUS_FILTER_FOREIGN_POLICY"], "foreign_001"),
    _BaseFocusTemplate("foreign_004", "Unnamed Regional Focus 001", 4, 6, "align_to_mexico", ["FOCUS_FILTER_FOREIGN_POLICY"], "foreign_001"),
    _BaseFocusTemplate("research_001", "Unnamed Research Focus 001", 8, 2, "research", ["FOCUS_FILTER_RESEARCH"], "focus_001"),
    _BaseFocusTemplate("research_002", "Unnamed Industry Research Focus 001", 7, 4, "research3", ["FOCUS_FILTER_RESEARCH", "FOCUS_FILTER_INDUSTRY"], "research_001"),
    _BaseFocusTemplate("research_003", "Unnamed Military Research Focus 001", 9, 4, "research", ["FOCUS_FILTER_RESEARCH", "FOCUS_FILTER_ARMY"], "research_001"),
    _BaseFocusTemplate("research_004", "Unnamed Nuclear Focus 001", 8, 6, "nuclear_energy", ["FOCUS_FILTER_RESEARCH"], "research_001"),
]


_PLACEHOLDER_DESC = (
    "Placeholder focus. Rename this focus, add a real description, then attach rewards "
    "when the branch concept is decided."
)


_TAG_RE = re.compile(r"[^A-Z0-9]")


def normalize_country_tag(tag: str) -> str:
    if tag is None:
        return "TAG"
    cleaned = _TAG_RE.sub("", tag.strip().upper())[:3]
    return cleaned or "TAG"


def _country_name(tag: str) -> str:
    for entry in MD_COUNTRY_TAGS:
        if entry.tag == tag:
            return entry.name
    return tag


def _focus_id(tag: str, suffix: str) -> str:
    return f"{tag}_{suffix}"


def create_base_focus_tree(tag_input: str) -> list:
    tag = normalize_country_tag(tag_input)
    nodes: list = []
    for tpl in _BASE_TEMPLATES:
        nodes.append(
            FocusNodeData(
                id=_focus_id(tag, tpl.idSuffix),
                title=tpl.title,
                description=_PLACEHOLDER_DESC,
                icon=tpl.icon,
                position=FocusPosition(x=tpl.x, y=tpl.y),
                cost=5,
                filters=list(tpl.filters),
                prerequisites=[_focus_id(tag, tpl.prerequisite)] if tpl.prerequisite else [],
                mutuallyExclusive=[],
                completionReward=CompletionReward(),
            )
        )
    return nodes


def apply_base_tree_to_project(project: FocusForgeProject) -> None:
    tag = normalize_country_tag(project.countryTag)
    lower_tag = tag.lower()
    project.countryTag = tag
    project.projectName = f"{_country_name(tag)} Base Tree"
    project.treeId = f"{lower_tag}_focus"
    project.exportSettings.modPrefix = tag
    project.exportSettings.focusFileName = f"{lower_tag}_focus_forge"
    project.exportSettings.localisationPrefix = tag
    project.focuses = create_base_focus_tree(tag)
    project.ideas = []
    project.events = []
