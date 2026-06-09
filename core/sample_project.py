"""Sample default project — ported from sampleProject.ts."""
from __future__ import annotations

from .types import (
    CompletionReward,
    EventData,
    EventOption,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
)


def make_blank_project() -> FocusForgeProject:
    """An empty project shown behind the startup launcher (no sample content)."""
    return FocusForgeProject(projectName="", countryTag="")


def make_sample_project() -> FocusForgeProject:
    return FocusForgeProject(
        projectName="Mexico Sample",
        countryTag="MEX",
        treeId="mexico_focus",
        continuousFocusPosition=FocusPosition(x=22000, y=5200),
        exportSettings=ExportSettings(
            modPrefix="MEX_forge",
            focusFileName="mexico_focus_forge",
            localisationPrefix="MEX_forge",
            includeIdeas=False,  # sample has no ideas; keeps it consistent (no export change)
            includeEvents=True,
        ),
        focuses=[
            FocusNodeData(
                id="MEX_forge_national_assessment",
                title="Assess the National Situation",
                description="Mexico reviews its politics, industry, security situation, and the terrifying possibility that all of them are connected.",
                icon="MEX_Mexican_government",
                position=FocusPosition(x=0, y=0),
                cost=5,
                filters=["FOCUS_FILTER_POLITICAL"],
                prerequisites=[],
                mutuallyExclusive=[],
                completionReward=CompletionReward(politicalPower=50),
            ),
            FocusNodeData(
                id="MEX_forge_industrial_plan",
                title="Industrial Plan",
                description="A practical industrial plan gives the economy a direction and gives committees something to rename.",
                icon="MEX_Economic_reform",
                position=FocusPosition(x=-4, y=1),
                cost=5,
                filters=["FOCUS_FILTER_ECONOMY", "FOCUS_FILTER_INDUSTRY"],
                prerequisites=["MEX_forge_national_assessment"],
                mutuallyExclusive=[],
                completionReward=CompletionReward(stability=0.01, rawLines=["add_treasury = 5"]),
            ),
            FocusNodeData(
                id="MEX_forge_security_review",
                title="Security Review",
                description="The security cabinet counts radios, vehicles, maps, and excuses. The radios are in the best condition.",
                icon="Generic_Policeman",
                position=FocusPosition(x=4, y=1),
                cost=5,
                filters=["FOCUS_FILTER_POLITICAL", "FOCUS_FILTER_ARMY"],
                prerequisites=["MEX_forge_national_assessment"],
                mutuallyExclusive=[],
                completionReward=CompletionReward(armyExperience=10),
            ),
        ],
        ideas=[],
        events=[
            EventData(
                id="MEX_forge.1",
                title="The First Draft",
                description="The cabinet receives the first focus tree draft. Someone asks if the arrows are legally binding.",
                options=[EventOption(key="a", text="Only emotionally.", effectRawLines=[])],
            )
        ],
    )


SAMPLE_PROJECT: FocusForgeProject = make_sample_project()
