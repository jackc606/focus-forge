"""Country history/loc export + image writers."""
from __future__ import annotations

from core.dds_decode import decode_dds
from core.exporters import (
    export_country_history,
    export_country_localisation,
    export_project_files,
)
from core.image_write import dds_bgra32, tga_bgra32
from core.serialization import project_from_dict, project_to_dict
from core.types import (
    CountryData,
    ExportSettings,
    FocusForgeProject,
    LeaderData,
    PartyData,
)


def _project():
    country = CountryData(
        popularities={"democratic": 30, "communism": 20, "neutrality": 50},
        rulingParty="neutrality", lastElection="2000.1.1",
        electionFrequency=48, electionsAllowed=True,
        parties=[PartyData(ideology="democratic", name="Liberal Front",
                           longName="The Liberal Front of Libya")],
        leaders=[LeaderData(name="Test Leader", ideology="Neutral_Autocracy",
                            traits=["emotional", "dictator"], pictureRef="Portrait_x.dds")],
        flagMain="",
    )
    return FocusForgeProject(
        countryTag="LBA", projectName="Libya Expanded", treeId="t", country=country,
        exportSettings=ExportSettings(modPrefix="LBA", focusFileName="lba_focus",
                                      localisationPrefix="LBA", includeCountry=True),
    )


def test_history_emits_politics_parties_leaders():
    out = export_country_history(_project())
    assert "set_popularities = {" in out
    assert "democratic = 30" in out
    assert "set_politics = {" in out
    assert "ruling_party = neutrality" in out
    assert 'last_election = "2000.1.1"' in out
    assert "elections_allowed = yes" in out
    assert "set_party_name = {" in out
    assert "ideology = democratic" in out
    assert "name = LBA_democratic_party" in out
    assert "create_country_leader = {" in out
    assert 'name = "Test Leader"' in out
    assert "ideology = Neutral_Autocracy" in out
    assert "traits = { emotional dictator }" in out
    assert 'picture = "Portrait_x.dds"' in out


def test_country_localisation():
    loc = export_country_localisation(_project())
    assert 'LBA_democratic_party:0 "Liberal Front"' in loc
    assert 'LBA_democratic_party_long:0 "The Liberal Front of Libya"' in loc


def test_export_files_gated_on_include_country():
    files = {f.relativePath for f in export_project_files(_project())}
    assert "history/countries/LBA - Libya Expanded.txt" in files
    assert "localisation/english/LBA_country_l_english.yml" in files
    # off when flag cleared
    p = _project()
    p.exportSettings.includeCountry = False
    files2 = {f.relativePath for f in export_project_files(p)}
    assert not any("history/countries" in f for f in files2)


def test_country_round_trip():
    proj = _project()
    restored = project_from_dict(project_to_dict(proj))
    assert restored.country.rulingParty == "neutrality"
    assert restored.country.parties[0].name == "Liberal Front"
    assert restored.country.leaders[0].ideology == "Neutral_Autocracy"
    assert restored.country.popularities["democratic"] == 30


def test_dds_writer_round_trips_decoder():
    w, h = 4, 3
    bgra = bytes([10, 20, 30, 255] * (w * h))  # B,G,R,A
    data = dds_bgra32(bgra, w, h)
    res = decode_dds(data)
    assert res is not None
    rw, rh, out = res
    assert (rw, rh) == (w, h)
    assert bytes(out) == bgra


def test_tga_matches_hoi4_format():
    tga = tga_bgra32(bytes([1, 2, 3, 255]), 1, 1)
    assert tga[2] == 2                 # image type 2 = uncompressed true-color
    assert tga[16] == 32               # 32 bpp
    assert tga[17] == 0x08             # bottom-left origin + 8 alpha bits (like HOI4)
    assert tga.endswith(b"TRUEVISION-XFILE.\x00")  # TGA 2.0 footer
