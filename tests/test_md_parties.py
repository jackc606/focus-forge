"""Importing a country's existing Millennium Dawn parties from localisation."""
from __future__ import annotations

from core.md_parties import parse_country_parties

# MD-style party loc: <TAG>.<sub> (name, with a leading £icon token), _icon, _desc.
_LOC = (
    "l_english:\n"
    ' CAN.conservatism: "£can_western_conservative Conservative Party"\n'
    ' CAN.conservatism_icon: "£can_western_conservative"\n'
    ' CAN.conservatism_desc: "The Tories."\n'
    ' CAN.liberalism: "£can_western_liberal Liberal Party"\n'
    ' CAN.liberalism_icon: "£can_western_liberal"\n'
    ' CAN.liberalism_desc: ""\n'
    ' CAN.made_up_sub: "£x Bogus"\n'          # unknown sub-ideology → ignored
    ' OTH.conservatism: "£oth Other Country"\n'  # different tag → ignored
)


def _roots(tmp_path):
    loc = tmp_path / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "MD_subideology_parties_l_english.yml").write_text(_LOC, encoding="utf-8")
    return [str(tmp_path)]


def test_parses_name_icon_desc_and_top_ideology(tmp_path):
    parties = parse_country_parties(_roots(tmp_path), "CAN")
    by_sub = {p["subIdeology"]: p for p in parties}
    assert set(by_sub) == {"conservatism", "liberalism"}   # made_up_sub dropped
    con = by_sub["conservatism"]
    assert con["ideology"] == "democratic"                 # mapped from sub
    assert con["name"] == "Conservative Party"             # £icon token stripped
    assert con["logoRef"] == "can_western_conservative"    # £ stripped
    assert con["description"] == "The Tories."
    assert con["longName"] == "Conservative Party"         # MD has no separate long name


def test_other_tags_ignored(tmp_path):
    parties = parse_country_parties(_roots(tmp_path), "CAN")
    assert all(p["name"] != "Other Country" for p in parties)


def test_unknown_tag_returns_empty(tmp_path):
    assert parse_country_parties(_roots(tmp_path), "ZZZ") == []
