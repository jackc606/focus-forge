"""Tests for the MD country-history starting-politics parser."""
from __future__ import annotations

from core.country_history import parse_starting_politics

_USA = """COUNTRY = {
\tset_popularities = {
\t\tdemocratic = 63
\t\tfascism = 0
\t\tcommunism = 5
\t\tneutrality = 27
\t\tnationalist = 5
\t}
\tset_politics = {
\t\truling_party = democratic
\t\tlast_election = "1996.11.5"
\t\telection_frequency = 48
\t\telections_allowed = yes
\t}
}
"""

# party_pop_array country — no set_popularities block
_CYR = """COUNTRY = {
\tstart_politics_input = yes
\tset_variable = { party_pop_array^14 = 0.80 } #Neutral_conservatism
\tadd_to_array = { ruling_party = 14 }
}
"""


def _root(tmp_path, filename, content):
    cd = tmp_path / "history" / "countries"
    cd.mkdir(parents=True)
    (cd / filename).write_text(content, encoding="utf-8")
    return str(tmp_path)


def test_parses_popularities_and_politics(tmp_path):
    root = _root(tmp_path, "USA - United States.txt", _USA)
    d = parse_starting_politics([root], "USA")
    assert d is not None
    assert d["popularities"] == {"democratic": 63.0, "fascism": 0.0,
                                 "communism": 5.0, "neutrality": 27.0, "nationalist": 5.0}
    assert d["rulingParty"] == "democratic"
    assert d["lastElection"] == "1996.11.5"
    assert d["electionFrequency"] == 48
    assert d["electionsAllowed"] is True


def test_file_matched_by_tag_before_dash(tmp_path):
    root = _root(tmp_path, "USA - United States.txt", _USA)
    assert parse_starting_politics([root], "usa") is not None  # case-insensitive
    assert parse_starting_politics([root], "US") is None        # not a prefix match


def test_decimals_preserved(tmp_path):
    content = _USA.replace("communism = 5", "communism = 69.8")
    root = _root(tmp_path, "SOV - Russia.txt", content)
    d = parse_starting_politics([root], "SOV")
    assert d["popularities"]["communism"] == 69.8


def test_party_pop_array_country_returns_none(tmp_path):
    root = _root(tmp_path, "CYR - Cyrenaica.txt", _CYR)
    assert parse_starting_politics([root], "CYR") is None


def test_missing_country_returns_none(tmp_path):
    root = _root(tmp_path, "USA - United States.txt", _USA)
    assert parse_starting_politics([root], "ZZZ") is None


def test_replace_path_honored(tmp_path):
    # A vanilla root + a mod root that replace_path's history/countries: only the
    # mod's file should be read.
    vanilla = tmp_path / "vanilla"
    (vanilla / "history" / "countries").mkdir(parents=True)
    (vanilla / "history" / "countries" / "USA - United States.txt").write_text(
        _USA.replace("ruling_party = democratic", "ruling_party = communism"),
        encoding="utf-8")
    mod = tmp_path / "mod"
    (mod / "history" / "countries").mkdir(parents=True)
    (mod / "history" / "countries" / "USA - United States.txt").write_text(_USA, encoding="utf-8")
    (mod / "descriptor.mod").write_text(
        'name="M"\nreplace_path="history/countries"\n', encoding="utf-8")
    d = parse_starting_politics([str(vanilla), str(mod)], "USA")
    assert d["rulingParty"] == "democratic"   # mod wins, vanilla ignored
