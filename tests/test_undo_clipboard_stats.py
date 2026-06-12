"""Undo/redo, branch copy/paste/duplicate, and tree stats."""
from __future__ import annotations

from core.tree_stats import compute_stats
from core.types import (
    CompletionReward,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    RewardItem,
)


def _model():
    from ui.project_model import ProjectModel
    m = ProjectModel()
    m._undo_coalesce_s = -1.0  # every change = its own undo step (deterministic)
    return m


def _focus(fid, x=0, y=0, **kw) -> FocusNodeData:
    return FocusNodeData(id=fid, title=kw.pop("title", fid),
                         position=FocusPosition(x=x, y=y), **kw)


# ----- undo / redo -----
def test_undo_redo_add_focus():
    m = _model()
    before = len(m.project.focuses)
    new_id = m.add_focus()
    assert len(m.project.focuses) == before + 1
    assert m.can_undo()
    assert m.undo()
    assert len(m.project.focuses) == before
    assert m.find_focus(new_id) is None
    assert m.can_redo()
    assert m.redo()
    assert len(m.project.focuses) == before + 1
    assert m.find_focus(new_id) is not None


def test_undo_restores_field_edits_and_new_edit_clears_redo():
    m = _model()
    fid = m.project.focuses[0].id
    original = m.find_focus(fid).title
    m.update_focus(fid, title="Changed")
    m.undo()
    assert m.find_focus(fid).title == original
    assert m.can_redo()
    m.update_focus(fid, title="Another")   # new edit after undo
    assert not m.can_redo()                # redo history is gone


def test_keystroke_burst_coalesces_into_one_step():
    m = _model()
    m._undo_coalesce_s = 60.0  # everything within one minute = one gesture
    fid = m.project.focuses[0].id
    original = m.find_focus(fid).title
    for t in ("H", "He", "Hel", "Hell", "Hello"):
        m.update_focus(fid, title=t)
    assert m.find_focus(fid).title == "Hello"
    assert m.undo()
    assert m.find_focus(fid).title == original  # one undo reverts the burst
    assert not m.can_undo() or m.find_focus(fid).title == original


def test_noop_change_burns_no_undo_step():
    m = _model()
    fid = m.project.focuses[0].id
    title = m.find_focus(fid).title
    depth = len(m._undo_stack)
    m.update_focus(fid, title=title)  # same value
    assert len(m._undo_stack) == depth


def test_load_clears_undo_history(tmp_path):
    m = _model()
    m.add_focus()
    assert m.can_undo()
    path = tmp_path / "p.focusforge.json"
    m.save_to_file(path)
    m2 = _model()
    m2.load_from_file(path)
    assert not m2.can_undo()


def test_undo_fixes_dead_selection():
    m = _model()
    new_id = m.add_focus()
    m.set_selection(new_id)
    m.undo()  # the selected focus no longer exists
    assert m.selected_id != new_id


# ----- copy / paste / duplicate -----
def test_paste_remaps_internal_links_and_offsets():
    m = _model()
    m.replace_project(FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[_focus("LBA_a", 0, 0),
                 _focus("LBA_b", 0, 1, prerequisites=["LBA_a"])],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge")))
    new_ids = m.paste_focuses(m.copy_payload(["LBA_a", "LBA_b"]))
    assert len(new_ids) == 2
    a2, b2 = (m.find_focus(i) for i in new_ids)
    assert b2.prerequisites == [a2.id]           # internal link remapped
    assert a2.id not in ("LBA_a", "LBA_b")       # fresh ids
    assert (a2.position.x, a2.position.y) == (1, 1)  # default: offset down-right


def test_paste_at_cursor_anchors_top_left_and_keeps_layout():
    m = _model()
    m.replace_project(FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[_focus("LBA_a", 3, 5),                       # top-left of the group
                 _focus("LBA_b", 4, 6, prerequisites=["LBA_a"])],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge")))
    new_ids = m.paste_focuses(m.copy_payload(["LBA_a", "LBA_b"]), at=(10, 2))
    a2, b2 = (m.find_focus(i) for i in new_ids)
    # top-left focus lands exactly at the target cell...
    assert (a2.position.x, a2.position.y) == (10, 2)
    # ...and the relative layout is preserved (b was +1,+1 from a).
    assert (b2.position.x, b2.position.y) == (11, 3)
    assert b2.prerequisites == [a2.id]


def test_paste_keeps_external_links_and_symmetrizes_mutex():
    m = _model()
    m.replace_project(FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[_focus("LBA_root", 0, 0),
                 _focus("LBA_a", 0, 1, prerequisites=["LBA_root"],
                        mutuallyExclusive=["LBA_root"])],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge")))
    m.find_focus("LBA_root").mutuallyExclusive = ["LBA_a"]
    (new_id,) = m.paste_focuses(m.copy_payload(["LBA_a"]))
    pasted = m.find_focus(new_id)
    assert pasted.prerequisites == ["LBA_root"]          # external link kept
    assert new_id in m.find_focus("LBA_root").mutuallyExclusive  # back-ref added


def test_duplicate_is_undoable():
    m = _model()
    fid = m.project.focuses[0].id
    before = len(m.project.focuses)
    m.duplicate_focuses([fid])
    assert len(m.project.focuses) == before + 1
    m.undo()
    assert len(m.project.focuses) == before


# ----- tree stats -----
def test_stats_days_and_paths():
    p = FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[
            _focus("a", 0, 0, cost=10),
            _focus("b", 0, 1, cost=10, prerequisites=["a"]),
            _focus("c", 1, 0, cost=5),
        ],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"))
    s = compute_stats(p)
    assert s["focuses"] == 3
    assert s["roots"] == 2                       # a and c
    assert s["max_depth"] == 2                   # a -> b
    assert s["longest_path_days"] == 140         # (10+10) * 7
    assert s["total_days"] == 175                # 25 * 7
    branches = {b["root"]: b for b in s["branches"]}
    assert branches["a"]["focuses"] == 2
    assert branches["a"]["days"] == 140


def test_stats_pp_economy():
    p = FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[
            _focus("a", 0, 0, completionReward=CompletionReward(politicalPower=120)),
            _focus("b", 1, 0, completionReward=CompletionReward(items=[
                RewardItem(kind="political_power", enabled=True, params={"amount": -50})])),
            _focus("c", 2, 0),  # no reward
        ],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"))
    s = compute_stats(p)
    assert s["pp_gained"] == 120
    assert s["pp_spent"] == 50
    assert s["focuses_without_rewards"] == 1


# ----- release-review regression fixes -----
def test_structural_ops_force_their_own_undo_step():
    m = _model()
    m._undo_coalesce_s = 60.0  # aggressive coalescing window
    before = len(m.project.focuses)
    m.add_focus()
    m.add_focus()  # immediately after — must still be its own gesture
    assert len(m.project.focuses) == before + 2
    m.undo()
    assert len(m.project.focuses) == before + 1  # only the second add reverted
    m.undo()
    assert len(m.project.focuses) == before


def test_rename_and_delete_clean_bypass_references():
    from core.types import AvailabilityRule, RewardItem
    m = _model()
    a = m.add_focus()
    b = m.add_focus()
    fb = m.find_focus(b)
    fb.bypass = AvailabilityRule(
        completedFocuses=[a],
        items=[RewardItem(kind="has_completed_focus", enabled=True, params={"focus": a})])
    m.notify_changed()
    new_a = m.rename_focus(a, "ZZZ_renamed_a")
    assert fb.bypass.completedFocuses == [new_a]
    assert fb.bypass.items[0].params["focus"] == new_a
    m.delete_focus(new_a)
    assert fb.bypass.completedFocuses == []
    assert fb.bypass.items[0].params["focus"] == ""


def test_paste_remaps_condition_item_focus_refs():
    from core.types import AvailabilityRule, RewardItem
    m = _model()
    a = m.add_focus()
    b = m.add_focus()
    fb = m.find_focus(b)
    fb.prerequisites = [a]
    fb.available = AvailabilityRule(items=[
        RewardItem(kind="has_completed_focus", enabled=True, params={"focus": a})])
    m.notify_changed()
    new_ids = m.paste_focuses(m.copy_payload([a, b]))
    a2, b2 = new_ids
    pasted_b = m.find_focus(b2)
    assert pasted_b.available.items[0].params["focus"] == a2  # remapped, not stale


def test_stats_self_prerequisite_not_double_counted():
    p = FocusForgeProject(
        countryTag="LBA", treeId="t",
        focuses=[_focus("a", 0, 0, cost=10, prerequisites=["a"])],
        exportSettings=ExportSettings(localisationPrefix="LBA_forge"))
    s = compute_stats(p)
    assert s["longest_path_days"] == 70   # cost*7 once, not twice
    assert s["max_depth"] == 1


def test_stats_diamond_chain_is_fast():
    import time
    focuses = [_focus("r", 0, 0, cost=1)]
    prev = ["r"]
    for layer in range(1, 26):  # 25 stacked diamonds = 2^25 paths unmemoized
        a = _focus(f"a{layer}", 0, layer, cost=1, prerequisites=list(prev))
        b = _focus(f"b{layer}", 1, layer, cost=1, prerequisites=list(prev))
        focuses += [a, b]
        prev = [a.id, b.id]
    p = FocusForgeProject(countryTag="LBA", treeId="t", focuses=focuses,
                          exportSettings=ExportSettings(localisationPrefix="LBA_forge"))
    t0 = time.monotonic()
    s = compute_stats(p)
    assert time.monotonic() - t0 < 2.0
    assert s["focuses"] == 51
