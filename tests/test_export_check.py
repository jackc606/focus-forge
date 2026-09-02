"""Export smoke check (pre-flight parse + structure + localisation coverage) and
the HOI4 error.log scanner (post-flight)."""
from __future__ import annotations

from core.bridge_dispatch import dispatch
from core.export_check import (
    attribute_focus,
    format_hits,
    log_is_stale,
    log_needles,
    parse_script,
    scan_error_log,
    smoke_check,
)
from core.exporters import export_project_files
from core.sample_project import make_sample_project
from core.types import EventData, EventOption, ExportedFile, IdeaData
from ui.project_model import ProjectModel


# ----- parse_script ------------------------------------------------------------------

def test_parse_script_accepts_real_paradox_shapes():
    good = ('focus_tree = {\n\tid = x\n\tcountry = { factor = 0 modifier = { add = 10 tag = MEX } }\n'
            '\tfocus = {\n\t\tid = A\n\t\tavailable = { date > 2006.1.1 has_war_support > 0.5 NOT = { has_country_flag = f } }\n'
            '\t\tcompletion_reward = { log = "[GetDateText]: [Root.GetName]: Focus A" 835 = { add_core_of = MEX } }\n'
            '\t\tai_will_do = { base = 1 modifier = { factor = 0 is_historical_focus_on = yes } }\n\t}\n}\n# trailing comment { unbalanced in comment\n')
    assert parse_script(good) == []


def test_parse_script_reports_problems_with_lines():
    assert parse_script("a = {\n b = 1\n") == [(3, "1 unclosed '{'")]
    assert parse_script("a = { }\n}\n")[0][0] == 2
    assert parse_script('x = "oops\ny = 1')[0] == (1, "unterminated string")
    assert parse_script("= 5") == [(1, "'=' has no key before it")]
    assert parse_script("a { b = 1 }") == [(1, "'{' after a bare word (missing '=')")]
    assert parse_script("a = { b = }") == [(1, "'=' with no value before '}'")]
    assert parse_script("a =") == [(1, "file ends after '=' with no value")]


# ----- smoke_check on a real export -----------------------------------------------------

def test_sample_project_export_passes_smoke_check():
    project = make_sample_project()
    project.exportSettings.includeIdeas = True
    project.exportSettings.includeEvents = True
    project.ideas.append(IdeaData(id="MEX_test_idea", title="Idea", description="d", picture="mex_pemex",
                                  modifierRawLines=["modifier = {", "\tstability_factor = 0.05", "}"]))
    ns = project.exportSettings.localisationPrefix
    project.events.append(EventData(id=f"{ns}.99", title="T", description="D",
                                    options=[EventOption(key="a", text="Ok")]))
    files = export_project_files(project)
    assert smoke_check(files) == []


def _f(rel, content, bom=False):
    return ExportedFile(relativePath=rel, content=content, bom=bom)


def test_smoke_check_flags_structure_and_localisation():
    tree = ('focus_tree = {\n\tid = t\n\tcountry = { factor = 0 }\n'
            '\tfocus = { id = A x = 0 y = 0 icon = i }\n'
            '\tfocus = { id = A x = 2 y = 0 icon = i }\n'
            '\tfocus = { id = B x = 4 y = 1 prerequisite = { focus = ZZZ } mutually_exclusive = { focus = QQQ } relative_position_id = NOPE }\n'
            '}\n')
    events = ('add_namespace = MEX\n'
              'country_event = {\n\tid = MEX.1\n\ttitle = MEX.1.t\n\tis_triggered_only = yes\n\toption = { name = MEX.1.a }\n}\n'
              'country_event = {\n\tid = OTHER.2\n\ttitle = OTHER.2.t\n\toption = { name = OTHER.2.a }\n}\n'
              'country_event = {\n\tid = MEX_forge.3\n\tis_triggered_only = yes\n}\n')
    loc = 'l_english:\n A:0 "Alpha"\n A_desc:0 "d"\n A:0 "dup"\n bad line here\n C:0 "has "quote" inside"\n MEX.1.t:0 "T"\n'
    broken = "ideas = {\n\tcountry = {\n\t\tX = { \n}\n"
    issues = smoke_check([
        _f("common/national_focus/t.txt", tree),
        _f("events/e.txt", events),
        _f("localisation/english/t_l_english.yml", loc, bom=False),
        _f("common/ideas/i.txt", broken),
        _f("interface/x.gfx", 'spriteTypes = { spriteType = { name = "GFX_a" } spriteType = { texturefile = "p.dds" } }'),
    ])
    codes = [i.code for i in issues]
    assert "export.focus.duplicateId" in codes
    assert "export.focus.prereqMissing" in codes and "export.focus.mutexMissing" in codes
    assert "export.focus.relativeMissing" in codes and "export.focus.noIcon" in codes
    assert "export.events.namespace" in codes and "export.events.noOption" in codes
    assert "export.events.neverFires" in codes and "export.events.noTitle" in codes
    assert "export.loc.bom" in codes and "export.loc.entry" in codes
    assert "export.loc.duplicate" in codes and "export.loc.quote" in codes
    assert "export.parse" in codes                          # broken ideas file
    assert "export.ideas.noBlock" not in codes              # structural checks skipped on a broken file
    assert "export.gfx.noTexture" in codes and "export.gfx.noName" in codes
    missing = [i for i in issues if i.code == "export.loc.missingFocus"]
    assert [i.focusId for i in missing] == ["B"]           # A is localised, B is not
    assert any(i.code == "export.loc.missingEvent" and "MEX.1.d" in i.message for i in issues)
    assert any(i.code == "export.loc.missingOption" and "MEX.1.a" in i.message for i in issues)


def test_localisation_filename_and_header():
    issues = smoke_check([_f("localisation/english/t.yml", 'l_french:\n A:0 "x"\n', bom=True)])
    codes = {i.code for i in issues}
    assert {"export.loc.filename", "export.loc.header"} <= codes


# ----- error.log scanner -----------------------------------------------------------------

_LOG = """[17:57:36][no_game_date][pdx_entity.cpp:2172]: Duplicate of HOL_cavalry_rifle_combined_entity added to entity system
[17:57:51][no_game_date][database_scoped_variables.cpp:63]: invalid database object for effect/trigger:  file: common/national_focus/mex_focus_forge.txt line: 4 Inf_equipment. use var:var_name to explicitly use variables in effects/triggers
[17:57:51][no_game_date][database_scoped_variables.cpp:63]: invalid database object for effect/trigger:  file: common/national_focus/mex_focus_forge.txt line: 4 Inf_equipment. use var:var_name to explicitly use variables in effects/triggers
[17:57:57][no_game_date][persistent.cpp:67]: Error: "Unexpected token: context_type, near line: 7" in file: "common/scripted_guis/02_conditional_peace_deals_scripted_gui.txt" near line: 7
[18:02:00][no_game_date][localisation.cpp:12]: Missing localisation key MEX_forge.9.t
[18:02:01][no_game_date][events.cpp:9]: Event MEX_forge.3 has no option
"""

_TREE = ("focus_tree = {\n\tfocus = {\n\t\tid = MEX_gafe\n\t\tcompletion_reward = { add_equipment_to_stockpile = { type = Inf_equipment } }\n"
         "\t}\n\tfocus = {\n\t\tid = MEX_other\n\t}\n}\n")


def _mex_project():
    p = make_sample_project()
    p.countryTag = "MEX"
    p.exportSettings.focusFileName = "mex_focus_forge"
    return p


def test_scan_error_log_filters_maps_and_dedupes(tmp_path):
    log = tmp_path / "error.log"
    log.write_text(_LOG, encoding="utf-8")
    files = [_f("common/national_focus/mex_focus_forge.txt", _TREE)]
    hits = scan_error_log(files, _mex_project(), str(log))
    msgs = [h.message for h in hits]
    assert len(hits) == 3                                  # duplicate collapsed, unrelated lines dropped
    assert not any("HOL_cavalry" in m or "scripted_guis" in m for m in msgs)
    eq = next(h for h in hits if "Inf_equipment" in h.message)
    assert eq.file == "common/national_focus/mex_focus_forge.txt" and eq.line == 4
    assert eq.focusId == "MEX_gafe"                        # line 4 sits inside MEX_gafe's block
    assert any("MEX_forge.9.t" in m for m in msgs) and any("MEX_forge.3" in m for m in msgs)
    # since filter keeps only the later launch
    later = scan_error_log(files, _mex_project(), str(log), since="18:00:00")
    assert len(later) == 2
    assert "→ MEX_gafe" in format_hits(hits)
    assert scan_error_log(files, _mex_project(), str(tmp_path / "missing.log")) == []


def test_attribute_prefers_on_disk_file_and_staleness(tmp_path):
    mod = tmp_path / "md_x"
    (mod / "common" / "national_focus").mkdir(parents=True)
    disk_tree = "focus_tree = {\n\tfocus = {\n\t\tid = MEX_from_disk\n\t\tx = 1\n\t}\n}\n"
    (mod / "common" / "national_focus" / "mex_focus_forge.txt").write_text(disk_tree, encoding="utf-8")
    files = [_f("common/national_focus/mex_focus_forge.txt", _TREE)]
    assert attribute_focus(files, "common/national_focus/mex_focus_forge.txt", 4, str(mod)) == "MEX_from_disk"
    assert attribute_focus(files, "common/national_focus/mex_focus_forge.txt", 4) == "MEX_gafe"
    log = tmp_path / "error.log"
    log.write_text(_LOG, encoding="utf-8")
    import os, time
    old = time.time() - 3600
    os.utime(log, (old, old))
    assert log_is_stale(str(log), str(mod)) is True       # mod written after the log
    os.utime(log, None)
    assert log_is_stale(str(log), str(mod)) is False
    assert log_is_stale(str(tmp_path / "nope.log"), str(mod)) is False


def test_log_needles_cover_ids_paths_and_namespace():
    p = _mex_project()
    p.events.append(EventData(id="MEX_forge.7", title="t", description="d"))
    needles = log_needles(p, export_project_files(p), mod_dir=r"C:\mods\md_beta_mexico_expanded")
    assert {p.focuses[0].id, "MEX_forge.7", "MEX_forge.", "mex_focus_forge", "md_beta_mexico_expanded",
            "common/national_focus/mex_focus_forge.txt"} <= set(needles)


# ----- bridge ----------------------------------------------------------------------------

def test_bridge_smoke_check_and_log_scan(tmp_path):
    model = ProjectModel()
    model.replace_project(_mex_project())
    r = dispatch(model, "smoke_check", {})
    assert r["ok"] and r["result"]["summary"] == {"errors": 0, "warnings": 0} and r["result"]["files"] >= 2
    log = tmp_path / "error.log"
    log.write_text(_LOG, encoding="utf-8")
    r = dispatch(model, "scan_error_log", {"path": str(log)})
    assert r["ok"] and r["result"]["exists"] and len(r["result"]["hits"]) == 3
    r = dispatch(model, "scan_error_log", {"path": str(tmp_path / "none.log")})
    assert r["ok"] and r["result"]["exists"] is False and r["result"]["hits"] == []
