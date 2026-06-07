"""Mirrors src/core/baseTree.test.ts."""
from __future__ import annotations

import copy

from core.base_tree import (
    apply_base_tree_to_project,
    create_base_focus_tree,
    normalize_country_tag,
)
from core.sample_project import make_sample_project
from core.validation import validate_project


def test_normalize_uppercases_short() -> None:
    assert normalize_country_tag("mex") == "MEX"


def test_normalize_strips_punctuation_and_truncates() -> None:
    assert normalize_country_tag("  sov_extra ") == "SOV"


def test_normalize_empty_falls_back_to_TAG() -> None:
    assert normalize_country_tag("") == "TAG"
    assert normalize_country_tag("   ") == "TAG"


def test_base_tree_has_21_focuses() -> None:
    base = create_base_focus_tree("usa")
    assert len(base) == 21


def test_base_tree_root_id() -> None:
    base = create_base_focus_tree("usa")
    assert base[0].id == "USA_focus_001"


def test_base_tree_titles_start_with_unnamed() -> None:
    base = create_base_focus_tree("usa")
    assert all(focus.title.startswith("Unnamed") for focus in base)


def test_base_tree_root_is_referenced_as_prerequisite() -> None:
    base = create_base_focus_tree("usa")
    assert any("USA_focus_001" in focus.prerequisites for focus in base)


def test_apply_base_tree_normalises_project() -> None:
    project = make_sample_project()
    project.countryTag = "FRA"
    apply_base_tree_to_project(project)
    assert project.countryTag == "FRA"
    assert project.treeId == "fra_focus"
    assert project.exportSettings.modPrefix == "FRA"
    assert project.focuses[0].id == "FRA_focus_001"
    errors = [i for i in validate_project(project) if i.severity == "error"]
    assert errors == []
