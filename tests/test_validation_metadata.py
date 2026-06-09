"""Project/export metadata validation."""
from __future__ import annotations

from core.types import (CountryData, ExportSettings, EventData, FocusForgeProject,
                        FocusNodeData, FocusPosition, IdeaData, LeaderData, PartyData)
from core.validation import validate_project


def _codes(project):
    return {i.code for i in validate_project(project)}


def _errors(project):
    return {i.code for i in validate_project(project) if i.severity == "error"}


def _valid_base(**over):
    """A metadata-complete project (one focus) with overridable fields."""
    kw = dict(
        projectName="Libya Expanded", countryTag="LBA", treeId="lba_focus",
        focuses=[FocusNodeData(id="LBA_a", title="A", description="d", icon="x",
                               position=FocusPosition(0, 0))],
        exportSettings=ExportSettings(focusFileName="lba_focus", localisationPrefix="LBA"),
    )
    kw.update(over)
    return FocusForgeProject(**kw)


def test_complete_project_has_no_metadata_codes():
    codes = _codes(_valid_base())
    meta = {c for c in codes if c.startswith(("project.", "export.", "country.",
                                              "idea", "event"))}
    assert meta == set()


def test_empty_tree_id_is_error():
    assert "project.treeId.empty" in _errors(_valid_base(treeId=""))


def test_empty_country_tag_is_error_bad_format_is_warning():
    assert "project.tag.empty" in _errors(_valid_base(countryTag=""))
    assert "project.tag.format" in _codes(_valid_base(countryTag="usa"))   # lowercase
    assert "project.tag.format" in _codes(_valid_base(countryTag="USAA"))  # 4 chars


def test_export_filename_and_prefix():
    p = _valid_base(exportSettings=ExportSettings(focusFileName="", localisationPrefix=""))
    e = _errors(p)
    assert "export.focusFile.empty" in e
    assert "export.locPrefix.empty" in e
    bad = _valid_base(exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="bad prefix!"))
    assert "export.locPrefix.invalid" in _errors(bad)


def test_project_name_empty_is_warning():
    assert "project.name.empty" in _codes(_valid_base(projectName=""))


def test_include_country_without_data_warns():
    p = _valid_base(exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeCountry=True))
    assert "country.missing" in _codes(p)


def test_country_ruling_party_and_popularities():
    c = CountryData(rulingParty="leftist",
                    popularities={"democratic": 60.0, "communism": 20.0})  # sums 80
    p = _valid_base(country=c,
                    exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeCountry=True))
    codes = _codes(p)
    assert "country.rulingParty.invalid" in _errors(p)
    assert "country.popularities.sum" in codes


def test_country_party_and_leader_checks():
    c = CountryData(rulingParty="communism",
                    popularities={"communism": 100.0},
                    parties=[PartyData(ideology="liberal", name="")],   # bad ideology + blank name
                    leaders=[LeaderData(name="", ideology="xyz")])      # blank name + bad sub-ideology
    p = _valid_base(country=c,
                    exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeCountry=True))
    codes = _codes(p)
    assert {"country.party.ideology", "country.party.name",
            "country.leader.name", "country.leader.ideology"} <= codes


def test_duplicate_subideology_collides():
    c = CountryData(rulingParty="democratic", popularities={"democratic": 100.0},
                    parties=[PartyData(ideology="democratic", subIdeology="conservatism", name="A"),
                             PartyData(ideology="democratic", subIdeology="conservatism", name="B"),  # same sub
                             PartyData(ideology="democratic", subIdeology="liberalism", name="C")])
    p = _valid_base(country=c,
                    exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeCountry=True))
    assert "country.party.collision" in _codes(p)


def test_multiple_parties_same_top_different_sub_is_clean():
    # MD allows several parties under one top ideology, distinguished by sub-ideology.
    c = CountryData(rulingParty="democratic", popularities={"democratic": 100.0},
                    parties=[PartyData(ideology="democratic", subIdeology="conservatism", name="A"),
                             PartyData(ideology="democratic", subIdeology="liberalism", name="B"),
                             PartyData(ideology="democratic", subIdeology="socialism", name="C")])
    p = _valid_base(country=c,
                    exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeCountry=True))
    assert "country.party.collision" not in _codes(p)


def test_subless_parties_same_top_collide():
    c = CountryData(rulingParty="democratic", popularities={"democratic": 100.0},
                    parties=[PartyData(ideology="democratic", name="A"),
                             PartyData(ideology="democratic", name="B")])  # no sub → top collides
    p = _valid_base(country=c,
                    exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeCountry=True))
    assert "country.party.collision" in _codes(p)


def test_ideas_and_events_export_consistency():
    # include ideas but none -> warning
    p = _valid_base(exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                  includeIdeas=True))
    assert "ideas.empty" in _codes(p)
    # duplicate idea id -> error
    dup = _valid_base(ideas=[IdeaData(id="LBA_x", title="X"), IdeaData(id="LBA_x")],
                      exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                    includeIdeas=True))
    assert "idea.id.duplicate" in _errors(dup)
    # duplicate event id -> error
    ev = _valid_base(events=[EventData(id="LBA.1", title="t"), EventData(id="LBA.1")],
                     exportSettings=ExportSettings(focusFileName="lba", localisationPrefix="LBA",
                                                   includeEvents=True))
    assert "event.id.duplicate" in _errors(ev)


def test_event_namespace_must_match_loc_prefix():
    es = ExportSettings(focusFileName="lba", localisationPrefix="LBA", includeEvents=True)
    p = _valid_base(events=[EventData(id="LBA.1", title="ok"),     # correct namespace
                            EventData(id="USA.1", title="x"),       # wrong namespace
                            EventData(id="noprefix", title="x")],   # no namespace
                    exportSettings=es)
    msgs = [i.message for i in validate_project(p) if i.code == "event.namespace"]
    assert any("USA.1" in m for m in msgs)
    assert any("noprefix" in m for m in msgs)
    assert not any("LBA.1" in m for m in msgs)   # the correct one is fine


def test_event_namespace_not_enforced_when_prefix_invalid():
    # if the loc prefix is itself invalid (its own error), don't pile on namespace errors
    es = ExportSettings(focusFileName="lba", localisationPrefix="", includeEvents=True)
    p = _valid_base(events=[EventData(id="anything", title="t")], exportSettings=es)
    codes = _codes(p)
    assert "export.locPrefix.empty" in codes
    assert "event.namespace" not in codes


def test_ideas_not_validated_when_not_included():
    # includeIdeas off -> a dup idea id does NOT raise (it won't be exported)
    p = _valid_base(ideas=[IdeaData(id="d"), IdeaData(id="d")])
    assert "idea.id.duplicate" not in _codes(p)
