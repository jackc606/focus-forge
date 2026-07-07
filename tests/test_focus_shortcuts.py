"""Tests for focus-tree shortcuts (the in-game bottom-left branch bookmarks)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.exporters import (
    export_focus_localisation,
    export_focus_tree,
    shortcut_loc_keys,
)
from core.focus_import import find_focus_trees, import_focus_tree
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.types import (
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    FocusShortcut,
)
from core.validation import validate_project


def _project_with_shortcuts(shortcuts) -> FocusForgeProject:
    p = make_sample_project()
    p.shortcuts = list(shortcuts)
    return p


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def test_export_tree_emits_shortcut_blocks() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Military", target="MEX_forge_security_review",
                      zoomFactor=0.80, triggerRawLines=['has_dlc = "Together for Victory"']),
        FocusShortcut(label="Industry", target="MEX_forge_industrial_plan"),
    ])
    out = export_focus_tree(p)
    # zoom+trigger shortcut
    assert "shortcut = {" in out
    assert "name = MEX_forge_military_shortcut" in out
    assert "target = MEX_forge_security_review" in out
    assert "scroll_wheel_factor = 0.8" in out
    assert "trigger = {" in out
    assert 'has_dlc = "Together for Victory"' in out
    # bare shortcut: no zoom line, no trigger block
    assert "name = MEX_forge_industry_shortcut" in out
    assert "target = MEX_forge_industrial_plan" in out
    # shortcuts come before the focuses
    assert out.index("shortcut = {") < out.index("focus = {")


def test_bare_shortcut_omits_optional_lines() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Industry", target="MEX_forge_industrial_plan"),
    ])
    out = export_focus_tree(p)
    block = out[out.index("shortcut = {"):out.index("focus = {")]
    assert "scroll_wheel_factor" not in block
    assert "trigger" not in block


def test_export_loc_has_shortcut_labels() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Military", target="MEX_forge_security_review"),
    ])
    loc = export_focus_localisation(p)
    assert ' MEX_forge_military_shortcut:0 "Military"' in loc


def test_duplicate_labels_get_unique_keys() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Politics", target="MEX_forge_national_assessment"),
        FocusShortcut(label="Politics", target="MEX_forge_security_review"),
    ])
    keys = shortcut_loc_keys(p)
    assert keys == ["MEX_forge_politics_shortcut", "MEX_forge_politics_shortcut_2"]
    tree = export_focus_tree(p)
    assert tree.count("name = MEX_forge_politics_shortcut\n") == 1
    assert "name = MEX_forge_politics_shortcut_2" in tree
    loc = export_focus_localisation(p)
    assert loc.count('_shortcut:0 "Politics"') == 1
    assert loc.count('_shortcut_2:0 "Politics"') == 1


def test_empty_label_falls_back_to_indexed_key() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="", target="MEX_forge_industrial_plan"),
    ])
    # empty label → slug fallback "shortcut_0", wrapped in the _shortcut suffix
    assert shortcut_loc_keys(p) == ["MEX_forge_shortcut_0_shortcut"]


def test_empty_target_shortcut_is_skipped_in_export() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Nowhere", target=""),
    ])
    tree = export_focus_tree(p)
    loc = export_focus_localisation(p)
    assert "shortcut = {" not in tree
    assert "Nowhere" not in loc


def test_no_shortcuts_export_is_byte_identical() -> None:
    """The most important guarantee: a project with no shortcuts exports exactly
    as it did before the feature."""
    p = make_sample_project()
    assert p.shortcuts == []
    tree = export_focus_tree(p)
    loc = export_focus_localisation(p)
    # No shortcut artifacts, and no stray blank lines injected.
    assert "shortcut" not in tree
    assert "_shortcut" not in loc
    # Header still flows straight into the first focus, exactly as before.
    assert ("initial_show_position = { x = 0 y = 0 }\n\n\tfocus = {") in tree


# --------------------------------------------------------------------------- #
# Import round-trip
# --------------------------------------------------------------------------- #
_TREE = """
focus_tree = {
\tid = tst_focus
\tcountry = { modifier = { add = 100 original_tag = TST } }
\tcontinuous_focus_position = { x = 0 y = 0 }
\tinitial_show_position = { x = 0 y = 0 }

\tshortcut = {
\t\tname = TST_military_shortcut
\t\ttarget = TST_army
\t\tscroll_wheel_factor = 0.75
\t\ttrigger = {
\t\t\thas_dlc = "Some DLC"
\t\t}
\t}

\tshortcut = {
\t\tname = TST_econ_shortcut
\t\ttarget = TST_root
\t}

\tfocus = {
\t\tid = TST_root
\t\tx = 0
\t\ty = 0
\t\tcost = 5
\t}

\tfocus = {
\t\tid = TST_army
\t\tx = 2
\t\ty = 1
\t\tcost = 5
\t}
}
"""


def _setup_tree(tmp_path):
    nf = tmp_path / "common" / "national_focus"
    nf.mkdir(parents=True)
    (nf / "tst.txt").write_text(_TREE, encoding="utf-8")
    loc = tmp_path / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "tst_l_english.yml").write_text(
        'l_english:\n TST_root:0 "Root"\n TST_army:0 "Army"\n'
        ' TST_military_shortcut:0 "Military"\n TST_econ_shortcut:0 "Economy"\n',
        encoding="utf-8")
    return [str(tmp_path)]


def test_import_recovers_shortcuts(tmp_path) -> None:
    roots = _setup_tree(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    assert len(proj.shortcuts) == 2
    a, b = proj.shortcuts
    # order preserved
    assert a.label == "Military"          # loc recovered from the yml
    assert a.target == "TST_army"
    assert a.zoomFactor == 0.75
    assert any('has_dlc = "Some DLC"' in ln for ln in a.triggerRawLines)
    assert b.label == "Economy"
    assert b.target == "TST_root"
    assert b.zoomFactor is None
    assert b.triggerRawLines == []


def test_import_export_shortcut_round_trip(tmp_path) -> None:
    roots = _setup_tree(tmp_path)
    ref = find_focus_trees(roots, use_cache=False)[0]
    proj = import_focus_tree(ref, roots)
    # Re-export and confirm the shortcut survives.
    out = export_focus_tree(proj)
    assert "target = TST_army" in out
    assert "scroll_wheel_factor = 0.75" in out


# --------------------------------------------------------------------------- #
# Serialization round-trip
# --------------------------------------------------------------------------- #
def test_serialization_round_trip() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Military", target="MEX_forge_security_review",
                      zoomFactor=0.8, triggerRawLines=['has_dlc = "X"']),
        FocusShortcut(label="Bare", target="MEX_forge_industrial_plan"),
    ])
    restored = project_from_dict(project_to_dict(p))
    assert len(restored.shortcuts) == 2
    a, b = restored.shortcuts
    assert a.label == "Military" and a.target == "MEX_forge_security_review"
    assert a.zoomFactor == 0.8
    assert a.triggerRawLines == ['has_dlc = "X"']
    # None zoom + empty trigger survive as None / []
    assert b.zoomFactor is None
    assert b.triggerRawLines == []


def test_old_project_without_shortcuts_key_loads() -> None:
    d = project_to_dict(make_sample_project())
    d.pop("shortcuts", None)
    restored = project_from_dict(d)
    assert restored.shortcuts == []


def test_null_zoom_survives_serialization() -> None:
    p = _project_with_shortcuts([FocusShortcut(label="A", target="MEX_forge_industrial_plan")])
    d = project_to_dict(p)
    # zoomFactor is None → serialized as null; must NOT become 0.0 on reload.
    restored = project_from_dict(d)
    assert restored.shortcuts[0].zoomFactor is None


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _codes(issues) -> set:
    return {i.code for i in issues}


def test_validation_missing_target_is_error() -> None:
    p = _project_with_shortcuts([FocusShortcut(label="X", target="does_not_exist")])
    issues = validate_project(p)
    assert "shortcut.target.missing" in _codes(issues)
    assert any(i.severity == "error" and i.code == "shortcut.target.missing" for i in issues)


def test_validation_empty_target_is_error() -> None:
    p = _project_with_shortcuts([FocusShortcut(label="X", target="")])
    assert "shortcut.target.empty" in _codes(validate_project(p))


def test_validation_empty_label_is_warning() -> None:
    p = _project_with_shortcuts([FocusShortcut(label="", target="MEX_forge_industrial_plan")])
    issues = validate_project(p)
    assert any(i.severity == "warning" and i.code == "shortcut.label.empty" for i in issues)


def test_validation_count_exceeds_eight() -> None:
    shortcuts = [FocusShortcut(label=f"S{i}", target="MEX_forge_industrial_plan")
                 for i in range(9)]
    p = _project_with_shortcuts(shortcuts)
    codes = [i.code for i in validate_project(p)]
    assert codes.count("shortcut.count.exceeds") == 1


def test_validation_valid_shortcut_no_issue() -> None:
    p = _project_with_shortcuts([
        FocusShortcut(label="Industry", target="MEX_forge_industrial_plan"),
    ])
    codes = _codes(validate_project(p))
    assert not any(c.startswith("shortcut.") for c in codes)


# --------------------------------------------------------------------------- #
# Model methods (undo boundaries)
# --------------------------------------------------------------------------- #
def _model():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m._undo_coalesce_s = 60.0  # aggressive: everything would coalesce if not for boundaries
    return m


def _base_project() -> FocusForgeProject:
    return FocusForgeProject(
        countryTag="TST", treeId="t",
        focuses=[FocusNodeData(id="TST_a", title="A", position=FocusPosition(0, 0)),
                 FocusNodeData(id="TST_b", title="B", position=FocusPosition(1, 0))],
        exportSettings=ExportSettings(localisationPrefix="TST_forge"))


def test_model_add_shortcut_is_own_undo_step() -> None:
    m = _model()
    m.replace_project(_base_project())
    m.add_shortcut(FocusShortcut(label="A", target="TST_a"))
    assert len(m.project.shortcuts) == 1
    assert m.undo()
    assert m.project.shortcuts == []


def test_model_update_shortcut() -> None:
    m = _model()
    m.replace_project(_base_project())
    m.add_shortcut(FocusShortcut(label="A", target="TST_a"))
    m.update_shortcut(0, FocusShortcut(label="B", target="TST_b"))
    assert m.project.shortcuts[0].label == "B"
    assert m.undo()
    assert m.project.shortcuts[0].label == "A"


def test_model_delete_shortcut() -> None:
    m = _model()
    m.replace_project(_base_project())
    m.add_shortcut(FocusShortcut(label="A", target="TST_a"))
    m.delete_shortcut(0)
    assert m.project.shortcuts == []
    assert m.undo()
    assert len(m.project.shortcuts) == 1


def test_model_move_shortcut_reorders_and_clamps() -> None:
    m = _model()
    m.replace_project(_base_project())
    m.add_shortcut(FocusShortcut(label="A", target="TST_a"))
    m.add_shortcut(FocusShortcut(label="B", target="TST_b"))
    m.move_shortcut(0, 1)  # A down -> [B, A]
    assert [s.label for s in m.project.shortcuts] == ["B", "A"]
    # clamp: moving the top item up is a no-op
    depth = len(m._undo_stack)
    m.move_shortcut(0, -1)
    assert [s.label for s in m.project.shortcuts] == ["B", "A"]
    assert len(m._undo_stack) == depth  # no undo step burned on a clamped no-op
