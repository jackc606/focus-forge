"""Custom leader descriptions: create_country_leader gains desc = "<loc key>"
and the localisation file carries the text under that key."""
from __future__ import annotations

from core.exporters import (
    export_country_history,
    export_country_localisation,
)
from core.serialization import project_from_dict, project_to_dict
from core.types import (
    CountryData,
    ExportSettings,
    FocusForgeProject,
    LeaderData,
)


def _proj(leaders) -> FocusForgeProject:
    return FocusForgeProject(
        treeId="t", countryTag="MEX", projectName="p",
        focuses=[], country=CountryData(leaders=leaders),
        exportSettings=ExportSettings(localisationPrefix="mex_forge",
                                      includeCountry=True))


def test_desc_key_in_history_and_text_in_localisation():
    p = _proj([LeaderData(name="Ana Torres", ideology="conservatism",
                          description="A reformer with a mandate.")])
    hist = export_country_history(p)
    assert 'desc = "MEX_ana_torres_desc"' in hist
    loc = export_country_localisation(p)
    assert ' MEX_ana_torres_desc:0 "A reformer with a mandate."' in loc


def test_no_description_emits_nothing():
    p = _proj([LeaderData(name="Ana Torres", ideology="conservatism")])
    assert "desc =" not in export_country_history(p)
    assert "_desc:0" not in export_country_localisation(p)


def test_two_same_named_leaders_get_distinct_desc_keys():
    p = _proj([
        LeaderData(name="Ana Torres", ideology="conservatism", description="First."),
        LeaderData(name="Ana Torres", ideology="socialism", description="Second."),
    ])
    hist = export_country_history(p)
    assert 'desc = "MEX_ana_torres_desc"' in hist
    assert 'desc = "MEX_ana_torres_2_desc"' in hist
    loc = export_country_localisation(p)
    assert ' MEX_ana_torres_desc:0 "First."' in loc
    assert ' MEX_ana_torres_2_desc:0 "Second."' in loc


def test_description_quotes_escaped_in_localisation():
    p = _proj([LeaderData(name="Ana", ideology="conservatism",
                          description='Called "La Presidenta" at home.')])
    loc = export_country_localisation(p)
    assert '"La Presidenta"' not in loc.split(":0 ", 1)[1].strip('"')  # raw quotes escaped
    assert "MEX_ana_desc:0" in loc


def test_description_round_trips_through_serialization():
    p = _proj([LeaderData(name="Ana", ideology="conservatism",
                          description="Reformer.")])
    p2 = project_from_dict(project_to_dict(p))
    assert p2.country.leaders[0].description == "Reformer."


def test_old_project_files_without_description_still_load():
    d = project_to_dict(_proj([LeaderData(name="Ana", ideology="conservatism")]))
    del d["country"]["leaders"][0]["description"]
    p = project_from_dict(d)
    assert p.country.leaders[0].description == ""
