"""Mirrors src/core/validation.test.ts plus extended coverage."""
from __future__ import annotations

import copy

from core.sample_project import make_sample_project
from core.types import (
    AvailabilityRule,
    CompletionReward,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    RewardItem,
)
from core.validation import validate_project


def _errors(project: FocusForgeProject) -> list:
    return [i for i in validate_project(project) if i.severity == "error"]


def _codes(project: FocusForgeProject) -> set:
    return {i.code for i in validate_project(project)}


def test_sample_project_has_no_errors() -> None:
    assert _errors(make_sample_project()) == []


def test_duplicate_id_is_error() -> None:
    project = make_sample_project()
    project.focuses.append(copy.deepcopy(project.focuses[0]))
    assert "focus.id.duplicate" in _codes(project)


def test_invalid_reward_is_error() -> None:
    project = make_sample_project()
    project.focuses[0].completionReward = CompletionReward(
        items=[RewardItem(kind="add_idea", params={"idea": ""})]
    )
    assert "focus.reward.invalid" in _codes(project)


def test_invalid_id_pattern_is_error() -> None:
    project = make_sample_project()
    project.focuses[0].id = "1starts_with_digit"
    assert "focus.id.invalid" in _codes(project)


def test_self_prerequisite_is_error() -> None:
    project = make_sample_project()
    project.focuses[0].prerequisites = [project.focuses[0].id]
    assert "focus.prerequisite.self" in _codes(project)


def test_missing_prerequisite_is_error() -> None:
    project = make_sample_project()
    project.focuses[0].prerequisites = ["does_not_exist"]
    assert "focus.prerequisite.missing" in _codes(project)


def test_missing_mutual_is_error() -> None:
    project = make_sample_project()
    project.focuses[0].mutuallyExclusive = ["does_not_exist"]
    assert "focus.mutual.missing" in _codes(project)


def test_missing_available_completed_is_error() -> None:
    project = make_sample_project()
    project.focuses[0].available = AvailabilityRule(completedFocuses=["does_not_exist"])
    assert "focus.available.completed.missing" in _codes(project)


def test_position_overlap_is_error() -> None:
    project = make_sample_project()
    project.focuses[1].position = FocusPosition(x=0, y=0)  # same as focuses[0]
    assert "focus.position.overlap" in _codes(project)


def test_empty_title_is_warning() -> None:
    project = make_sample_project()
    project.focuses[0].title = ""
    issues = validate_project(project)
    assert any(i.code == "focus.title.empty" and i.severity == "warning" for i in issues)


def test_empty_description_is_warning() -> None:
    project = make_sample_project()
    project.focuses[0].description = ""
    issues = validate_project(project)
    assert any(i.code == "focus.description.empty" and i.severity == "warning" for i in issues)


def test_empty_icon_is_warning() -> None:
    project = make_sample_project()
    project.focuses[0].icon = ""
    issues = validate_project(project)
    assert any(i.code == "focus.icon.empty" and i.severity == "warning" for i in issues)


def test_cycle_detected() -> None:
    project = make_sample_project()
    a, b, c = project.focuses
    a.prerequisites = [c.id]
    b.prerequisites = [a.id]
    c.prerequisites = [b.id]
    assert "focus.graph.cycle" in _codes(project)


def test_normalize_id_list_flattens_nested() -> None:
    """Regression for the v0.2.1 'unhashable type: list' crash — a nested
    prerequisite element (e.g. from a malformed AI-bridge command or an older
    project file) must be flattened to plain string ids before it reaches any
    `x in set` check in validation / graph reconcile / chip rendering."""
    from core.types import normalize_id_list

    assert normalize_id_list([["A"]]) == ["A"]
    assert normalize_id_list(["A", ["B", "C"], "A"]) == ["A", "B", "C"]
    assert normalize_id_list(None) == []
    assert normalize_id_list("X") == ["X"]
    assert normalize_id_list([None, "", "  Y  "]) == ["Y"]


def test_validate_survives_nested_prerequisite() -> None:
    project = make_sample_project()
    # Simulate the corrupted-on-disk shape that crashed validate_project.
    project.focuses[1].prerequisites = [[project.focuses[0].id]]  # type: ignore[list-item]
    from core.serialization import project_from_dict, project_to_dict

    healed = project_from_dict(project_to_dict(project))
    assert healed.focuses[1].prerequisites == [project.focuses[0].id]
    # Must not raise TypeError: unhashable type: 'list'.
    validate_project(healed)
