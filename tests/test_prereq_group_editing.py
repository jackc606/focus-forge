"""Group-aware OR-prerequisite editing: model group/ungroup operations, the
inspector's group-preserving chip round-trip, and the canvas edge styling
(dashed = OR-group member) including in-place restyle on plain<->group moves.

Runs offscreen with a QApplication (model timers + widgets need one)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from core.types import ExportSettings, FocusForgeProject, FocusNodeData, FocusPosition


def _ensure_app():
    return QApplication.instance() or QApplication([])


class _StubProvider(QObject):
    """Minimal icon-provider stand-in so InspectorPanel never scans game files
    (same shape as the stub in test_focused_editor_flush)."""
    changed = Signal()
    roots_changed = Signal()
    icons_warmed = Signal()

    def pixmap(self, name):
        return None

    def is_indexed(self):
        return False

    def sprite_exists(self, name):
        return True

    def roots(self):
        return []

    def warm_focus_icons_async(self, icons):
        pass


def _model(coalesce: float = 60.0):
    _ensure_app()
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m._undo_coalesce_s = coalesce  # aggressive window: everything coalesces
    return m


def _proj(prerequisites) -> FocusForgeProject:
    """a, b, c are roots; d has the given prerequisites value."""
    return FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[
            FocusNodeData(id="LBA_a", title="A", position=FocusPosition(0, 0)),
            FocusNodeData(id="LBA_b", title="B", position=FocusPosition(2, 0)),
            FocusNodeData(id="LBA_c", title="C", position=FocusPosition(4, 0)),
            FocusNodeData(id="LBA_d", title="D", position=FocusPosition(2, 2),
                          prerequisites=list(prerequisites)),
        ],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"))


def _prereqs(m):
    return m.find_focus("LBA_d").prerequisites


# ===== model: group_prerequisite =====
def test_group_with_no_existing_group_collapses_all_plains():
    m = _model()
    m.replace_project(_proj(["LBA_a", "LBA_b"]))
    msg = m.group_prerequisite("LBA_d", "LBA_b")
    assert msg == "OR group: LBA_a | LBA_b"
    assert _prereqs(m) == [["LBA_a", "LBA_b"]]


def test_group_preserves_plain_order():
    m = _model()
    m.replace_project(_proj(["LBA_c", "LBA_a", "LBA_b"]))
    m.group_prerequisite("LBA_d", "LBA_a")
    assert _prereqs(m) == [["LBA_c", "LBA_a", "LBA_b"]]


def test_group_with_existing_group_moves_plain_into_first_group():
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"], "LBA_c"]))
    msg = m.group_prerequisite("LBA_d", "LBA_c")
    assert msg == "OR group: LBA_a | LBA_b | LBA_c"
    assert _prereqs(m) == [["LBA_a", "LBA_b", "LBA_c"]]


def test_group_noop_with_single_plain_prereq():
    m = _model()
    m.replace_project(_proj(["LBA_a"]))
    assert m.group_prerequisite("LBA_d", "LBA_a") == ""
    assert _prereqs(m) == ["LBA_a"]


def test_group_noop_when_prereq_not_plain():
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"]]))
    assert m.group_prerequisite("LBA_d", "LBA_a") == ""   # already in a group
    assert m.group_prerequisite("LBA_d", "LBA_c") == ""   # not a prereq at all
    assert _prereqs(m) == [["LBA_a", "LBA_b"]]


def test_group_noop_burns_no_undo_step():
    m = _model()
    m.replace_project(_proj(["LBA_a"]))
    depth = len(m._undo_stack)
    assert m.group_prerequisite("LBA_d", "LBA_a") == ""
    assert len(m._undo_stack) == depth


# ===== model: ungroup_prerequisite =====
def test_ungroup_member_becomes_plain():
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b", "LBA_c"]]))
    msg = m.ungroup_prerequisite("LBA_d", "LBA_b")
    assert msg == "Required (AND): LBA_b → LBA_d"
    assert _prereqs(m) == [["LBA_a", "LBA_c"], "LBA_b"]


def test_ungroup_dissolves_group_of_two_to_plains():
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"]]))
    m.ungroup_prerequisite("LBA_d", "LBA_a")
    assert _prereqs(m) == ["LBA_b", "LBA_a"]


def test_ungroup_noop_when_not_in_a_group():
    m = _model()
    m.replace_project(_proj(["LBA_a", "LBA_b"]))
    depth = len(m._undo_stack)
    assert m.ungroup_prerequisite("LBA_d", "LBA_a") == ""
    assert _prereqs(m) == ["LBA_a", "LBA_b"]
    assert len(m._undo_stack) == depth


# ===== model: both are their own undo step (test_undo_boundaries pattern) =====
def _burst(m, fid="LBA_a"):
    for t in ("X", "XY", "XYZ"):
        m.update_focus(fid, title=t)


def test_group_prerequisite_is_its_own_undo_step():
    m = _model()
    m.replace_project(_proj(["LBA_a", "LBA_b"]))
    _burst(m)
    assert m.group_prerequisite("LBA_d", "LBA_b")
    assert m.undo()                              # first undo: ONLY the grouping
    assert _prereqs(m) == ["LBA_a", "LBA_b"]
    assert m.find_focus("LBA_a").title == "XYZ"  # typing NOT swept into this undo
    assert m.undo()
    assert m.find_focus("LBA_a").title == "A"


def test_ungroup_prerequisite_is_its_own_undo_step():
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"]]))
    _burst(m)
    assert m.ungroup_prerequisite("LBA_d", "LBA_a")
    assert m.undo()
    assert _prereqs(m) == [["LBA_a", "LBA_b"]]
    assert m.find_focus("LBA_a").title == "XYZ"
    assert m.undo()
    assert m.find_focus("LBA_a").title == "A"


# ===== inspector: group-preserving chip round-trip =====
def _inspector(m, monkeypatch):
    import ui.icon_provider as ip
    monkeypatch.setattr(ip, "_INSTANCE", _StubProvider())
    from ui.inspector_panel import InspectorPanel
    return InspectorPanel(m)


def test_inspector_renders_group_and_plain_chips(monkeypatch):
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"], "LBA_c"]))
    m.set_selection("LBA_d")
    panel = _inspector(m, monkeypatch)
    assert panel._prereqs.tokens() == ["LBA_a | LBA_b", "LBA_c"]
    panel.close()


def test_inspector_removing_plain_chip_keeps_group_intact(monkeypatch):
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"], "LBA_c"]))
    m.set_selection("LBA_d")
    panel = _inspector(m, monkeypatch)
    panel._prereqs._remove("LBA_c")            # user clicks the chip's ×
    assert _prereqs(m) == [["LBA_a", "LBA_b"]]
    panel.close()


def test_inspector_adding_chip_keeps_group_intact(monkeypatch):
    m = _model()
    m.replace_project(_proj([["LBA_a", "LBA_b"]]))
    m.set_selection("LBA_d")
    panel = _inspector(m, monkeypatch)
    panel._prereqs._add("LBA_c")
    assert _prereqs(m) == [["LBA_a", "LBA_b"], "LBA_c"]
    panel.close()


def test_inspector_typed_pipe_token_creates_group(monkeypatch):
    m = _model()
    m.replace_project(_proj([]))
    m.set_selection("LBA_d")
    panel = _inspector(m, monkeypatch)
    panel._prereqs._add("LBA_a | LBA_b")       # power-user: typed group token
    assert _prereqs(m) == [["LBA_a", "LBA_b"]]
    panel.close()


def test_inspector_pipe_token_with_one_survivor_is_plain(monkeypatch):
    m = _model()
    m.replace_project(_proj([]))
    m.set_selection("LBA_d")
    panel = _inspector(m, monkeypatch)
    panel._prereqs._add("LBA_a | ")            # blank member dropped → plain id
    assert _prereqs(m) == ["LBA_a"]
    panel.close()


# ===== scene: dashed OR edges + in-place restyle =====
def _harness(prerequisites):
    from ui.graph_scene import GraphScene
    m = _model()
    m.replace_project(_proj(prerequisites))
    scene = GraphScene()
    m.project_changed.connect(lambda: scene.reconcile(m.project, m.selected_id))
    scene.reconcile(m.project, m.selected_id)
    return m, scene


def _edge(scene, src):
    return scene._edges[("prereq", src, "LBA_d")]


def test_reconcile_marks_group_member_edges_alternative():
    _, scene = _harness([["LBA_a", "LBA_b"], "LBA_c"])
    assert _edge(scene, "LBA_a").alternative is True
    assert _edge(scene, "LBA_b").alternative is True
    assert _edge(scene, "LBA_c").alternative is False


def test_alternative_edge_is_dashed_and_tooltipped():
    _, scene = _harness([["LBA_a", "LBA_b"], "LBA_c"])
    assert _edge(scene, "LBA_a").pen().style() == Qt.DashLine
    assert "OR alternative" in _edge(scene, "LBA_a").toolTip()
    assert _edge(scene, "LBA_c").pen().style() == Qt.SolidLine
    assert _edge(scene, "LBA_c").toolTip() == ""


def test_ungroup_restyles_existing_edge_in_place():
    m, scene = _harness([["LBA_a", "LBA_b", "LBA_c"]])
    edge_before = _edge(scene, "LBA_b")
    m.ungroup_prerequisite("LBA_d", "LBA_b")   # → [["LBA_a","LBA_c"], "LBA_b"]
    edge_after = _edge(scene, "LBA_b")
    assert edge_after is edge_before           # same key: restyled, not rebuilt
    assert edge_after.alternative is False
    assert edge_after.pen().style() == Qt.SolidLine
    assert edge_after.toolTip() == ""
    assert _edge(scene, "LBA_a").alternative is True


def test_group_restyles_existing_edge_in_place():
    m, scene = _harness(["LBA_a", "LBA_b"])
    assert _edge(scene, "LBA_a").alternative is False
    m.group_prerequisite("LBA_d", "LBA_b")
    assert _edge(scene, "LBA_a").alternative is True
    assert _edge(scene, "LBA_b").alternative is True
    assert _edge(scene, "LBA_a").pen().style() == Qt.DashLine


def test_plain_requirement_wins_over_group_membership_for_styling():
    # (a OR b) AND a — a is still a hard requirement, so its edge stays solid.
    _, scene = _harness([["LBA_a", "LBA_b"], "LBA_a"])
    assert _edge(scene, "LBA_a").alternative is False
    assert _edge(scene, "LBA_b").alternative is True
