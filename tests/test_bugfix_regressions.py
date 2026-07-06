"""Regression tests for the 2026-07-06 bug-fix batch (core + bridge fixes whose
authoring agents were cut off before finishing their test files). Each test
names the defect it pins down. No Qt, no network, no game files needed."""
from __future__ import annotations

import struct

from core.types import (
    CountryData,
    ExportSettings,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
    normalize_prereq_groups,
)


def _proj(**kw) -> FocusForgeProject:
    base = dict(treeId="t", countryTag="MEX", focuses=[],
                exportSettings=ExportSettings(localisationPrefix="mex_forge"))
    base.update(kw)
    return FocusForgeProject(**base)


# ----- normalize_prereq_groups: no cross-group dedup (destroyed OR semantics) -----
def test_or_groups_keep_ids_repeated_across_groups():
    assert normalize_prereq_groups([["a", "b"], ["a", "c"]]) == [["a", "b"], ["a", "c"]]


def test_or_groups_keep_flat_id_also_present_in_a_group():
    # (a|b) AND a — the hard requirement on "a" must survive.
    assert normalize_prereq_groups([["a", "b"], "a"]) == [["a", "b"], "a"]


def test_or_groups_still_dedup_within_group_and_duplicate_groups():
    assert normalize_prereq_groups([["a", "a", "b"], ["a", "b"], "c", "c"]) == [["a", "b"], "c"]


# ----- serialization: null-safe + coercing load -----
def test_load_survives_json_nulls_in_availability_and_reward():
    from core.serialization import project_from_dict
    p = project_from_dict({
        "treeId": "t", "countryTag": "MEX",
        "focuses": [{"id": "f", "position": {"x": 0, "y": 0},
                     "availability": {"completedFocuses": None},
                     "completionReward": {"addIdeas": None}}]})
    assert p.focuses[0].id == "f"


def test_load_coerces_string_position_and_cost():
    # Heals files corrupted by the pre-fix bridge pass-through.
    from core.serialization import project_from_dict
    p = project_from_dict({
        "treeId": "t", "countryTag": "MEX",
        "focuses": [{"id": "f", "position": {"x": "9", "y": "3"}, "cost": "5"}]})
    f = p.focuses[0]
    assert f.position.x == 9 and isinstance(f.position.x, int)
    assert f.position.y == 3 and isinstance(f.position.y, int)
    assert f.cost == 5.0


def test_load_coerces_non_numeric_popularities():
    from core.serialization import project_from_dict
    p = project_from_dict({
        "treeId": "t", "countryTag": "MEX", "focuses": [],
        "country": {"popularities": {"democratic": "40%", "communism": "5"}}})
    pops = p.country.popularities
    assert all(isinstance(v, float) for v in pops.values()), pops


# ----- validation: reports instead of crashing on bad popularity values -----
def test_validation_survives_non_numeric_popularity():
    from core.validation import validate_project
    p = _proj(country=CountryData())
    p.exportSettings.includeCountry = True
    p.country.popularities = {"democratic": "40%"}
    issues = validate_project(p)  # must not raise
    assert any("popularit" in ((i.code or "") + i.message).lower() for i in issues)


# ----- exporters: filename sanitization (NTFS ADS silent-empty-file bug) -----
def test_country_history_filename_is_sanitized():
    from core.exporters import export_project_files
    p = _proj(projectName="Mexico: Reborn <test>", country=CountryData())
    p.exportSettings.includeCountry = True
    hist = [f for f in export_project_files(p)
            if "history/countries" in f.relativePath.replace("\\", "/")]
    assert hist
    name_part = hist[0].relativePath.replace("\\", "/").split("countries/")[-1]
    assert not any(c in name_part for c in '<>:"/\\|?*'), name_part


# ----- exporters: empty icon / picture lines are omitted, not emitted valueless -----
def test_empty_focus_icon_line_omitted():
    from core.exporters import export_focus_tree
    p = _proj(focuses=[FocusNodeData(id="f1", title="T", icon="",
                                     position=FocusPosition(0, 0))])
    out = export_focus_tree(p)
    for line in out.splitlines():
        assert line.strip() != "icon =", "valueless icon line corrupts the block"


# ----- exporters: unique leader asset slugs (non-Latin names collided) -----
def test_non_latin_leader_names_get_distinct_slugs():
    from types import SimpleNamespace as NS
    from core.exporters import leader_asset_slugs
    country = NS(leaders=[NS(name="Владимир Путин", pictureRef="", pictureData="x"),
                          NS(name="Дмитрий Медведев", pictureRef="", pictureData="x")],
                 parties=[])
    slugs = leader_asset_slugs(country)
    assert len(slugs) == len(set(slugs)) == 2, slugs


# ----- reward_presets: promote_leader escapes quotes -----
def test_promote_leader_name_quotes_escaped():
    from core.reward_presets import _escape_quoted
    out = _escape_quoted('Joaquin "El Chapo" Guzman')
    assert '"' not in out.replace('\\"', ""), out


# ----- pdx_loc: trailing comments after the closing quote -----
def test_loc_line_with_trailing_comment_matches():
    from core.pdx_loc import _LOC_LINE
    m = _LOC_LINE.match(' key_a:0 "Value here" # trailing note')
    assert m and m.group(2) == "Value here"


# ----- focus_import: comment stripping is quote-aware -----
def test_hash_inside_quoted_string_survives_comment_strip():
    from core.focus_import import _strip_comments
    out = _strip_comments('log = "50% done # half" # real comment')
    assert '"50% done # half"' in out
    assert "real comment" not in out


# ----- dds_decode: unsupported bit depth returns None, not (w, h, None) -----
def test_unsupported_dds_returns_none_not_partial_tuple():
    from core.dds_decode import decode_dds
    hdr = b"DDS " + struct.pack("<I", 124) + b"\x00" * 120
    assert decode_dds(hdr + b"\x00" * 64) is None


# ----- deep chains: iterative cycle detection + stats (no RecursionError) -----
def test_2000_deep_prerequisite_chain_validates_and_stats():
    from core.tree_stats import compute_stats
    from core.validation import validate_project
    focuses = [FocusNodeData(id=f"f{i}", title="x", position=FocusPosition(0, i),
                             prerequisites=([f"f{i-1}"] if i else []))
               for i in range(2000)]
    p = _proj(focuses=focuses)
    validate_project(p)
    compute_stats(p)


# ----- bridge: update_focus coerces / rejects loosely-typed JSON -----
class _FakeModel:
    """Just enough ProjectModel surface for the update_focus op."""

    def __init__(self):
        self.project = _proj(focuses=[FocusNodeData(
            id="f1", title="T", position=FocusPosition(1, 1))])
        self.notified = 0

    def find_focus(self, fid):
        return next((f for f in self.project.focuses if f.id == fid), None)

    def notify_changed(self):
        self.notified += 1

    def _force_undo_boundary(self):
        pass


def test_bridge_update_focus_coerces_string_position():
    from core.bridge_dispatch import dispatch
    m = _FakeModel()
    resp = dispatch(m, "update_focus", {"id": "f1", "position": {"x": "9", "y": "3"}})
    if resp["ok"]:
        f = m.find_focus("f1")
        assert f.position.x == 9 and isinstance(f.position.x, int)
    else:
        # Rejecting is also acceptable — the point is the model is never poisoned.
        f = m.find_focus("f1")
        assert isinstance(f.position.x, int)


def test_bridge_update_focus_rejects_garbage_position():
    from core.bridge_dispatch import dispatch
    m = _FakeModel()
    resp = dispatch(m, "update_focus", {"id": "f1", "position": {"x": "nine"}})
    assert resp["ok"] is False
    assert isinstance(m.find_focus("f1").position.x, int)  # model untouched


def test_bridge_update_focus_rejects_non_list_filters():
    from core.bridge_dispatch import dispatch
    m = _FakeModel()
    resp = dispatch(m, "update_focus", {"id": "f1", "filters": "political"})
    assert resp["ok"] is False
