"""Project JSON round-trip integrity."""
from __future__ import annotations

import json

from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict


def test_round_trip_equals_initial_dict() -> None:
    project = make_sample_project()
    dict1 = project_to_dict(project)
    dict2 = project_to_dict(project_from_dict(dict1))
    assert dict1 == dict2


def test_round_trip_through_json_text() -> None:
    project = make_sample_project()
    text = json.dumps(project_to_dict(project), indent=2, ensure_ascii=False)
    parsed = json.loads(text)
    restored = project_from_dict(parsed)
    assert project_to_dict(restored) == project_to_dict(project)


def test_optional_none_fields_are_stripped() -> None:
    project = make_sample_project()
    d = project_to_dict(project)
    # The first focus's completionReward only has politicalPower; other fields should be absent.
    cr = d["focuses"][0]["completionReward"]
    assert "politicalPower" in cr
    assert "stability" not in cr
    assert "items" not in cr
    # available is None on every sample focus → stripped
    for f in d["focuses"]:
        assert "available" not in f
        assert "notes" not in f


def test_export_dir_and_mod_meta_round_trip() -> None:
    project = make_sample_project()
    project.exportDir = r"C:/mods/md_demo"
    project.modMeta = {"name": "Demo", "tags": ["Gameplay"],
                       "dependencies": ["Millennium Dawn: A Modern Day Mod"],
                       "supported_version": "1.17.*"}
    restored = project_from_dict(project_to_dict(project))
    assert restored.exportDir == r"C:/mods/md_demo"
    assert restored.modMeta == project.modMeta


def test_export_dir_defaults_when_absent() -> None:
    # Older project files (no exportDir/modMeta) load with safe defaults.
    project = project_from_dict({"projectName": "Bare", "countryTag": "USA",
                                 "treeId": "usa_focus"})
    assert project.exportDir == ""
    assert project.modMeta == {}


def test_availability_items_round_trip() -> None:
    from core.types import AvailabilityRule, RewardItem
    project = make_sample_project()
    project.focuses[0].available = AvailabilityRule(items=[
        RewardItem(kind="nato_member", enabled=True, params={}),
        RewardItem(kind="gdp_threshold", enabled=True, params={"amount": 2000}),
    ], rawLines=["has_war = no"])
    restored = project_from_dict(project_to_dict(project))
    av = restored.focuses[0].available
    assert av is not None
    assert [i.kind for i in av.items] == ["nato_member", "gdp_threshold"]
    assert av.items[1].params["amount"] == 2000
    assert av.rawLines == ["has_war = no"]


def test_loads_project_with_missing_optional_fields() -> None:
    """Backward compatibility: older project files may be missing newer optional keys."""
    minimal = {
        "schemaVersion": 1,
        "app": "Focus Forge",
        "mode": "millennium-dawn",
        "projectName": "Bare",
        "countryTag": "USA",
        "treeId": "usa_focus",
        "continuousFocusPosition": {"x": 0, "y": 0},
        "exportSettings": {
            "modPrefix": "USA",
            "focusFileName": "usa_focus",
            "localisationPrefix": "USA",
            "includeIdeas": False,
            "includeEvents": False,
        },
        "focuses": [
            {
                "id": "USA_a",
                "title": "A",
                "description": "Desc",
                "icon": "icon",
                "position": {"x": 0, "y": 0},
                "cost": 5,
                "filters": [],
                "prerequisites": [],
                "mutuallyExclusive": [],
                "completionReward": {},
            }
        ],
        "ideas": [],
        "events": [],
    }
    project = project_from_dict(minimal)
    assert project.focuses[0].id == "USA_a"
    assert project.focuses[0].available is None
