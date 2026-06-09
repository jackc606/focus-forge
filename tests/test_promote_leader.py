"""The "Put Leader in Power" reward and the MD leader parser."""
from __future__ import annotations

from core.md_leaders import _leaders_from_text
from core.reward_presets import (
    build_reward_item_lines,
    decode_leader,
    encode_leader,
    get_reward_preset,
)


def test_preset_registered():
    p = get_reward_preset("promote_leader")
    assert p is not None and p.group == "Leaders"
    assert [param.key for param in p.params] == ["leader", "setRuling"]


def test_encode_decode_round_trip():
    v = encode_leader("Muammar Gaddafi", "Autocracy", "g.dds", ["a", "b"])
    d = decode_leader(v)
    assert d == {"name": "Muammar Gaddafi", "ideology": "Autocracy",
                 "picture": "g.dds", "traits": ["a", "b"]}
    assert decode_leader("not-base64") is None


def test_build_sets_ruling_party():
    v = encode_leader("X", "Autocracy", "x.dds", ["t1"])
    lines = build_reward_item_lines({"kind": "promote_leader", "enabled": True,
                                     "params": {"leader": v, "setRuling": "yes"}})
    text = "\n".join(lines)
    assert 'create_country_leader = {' in text
    assert 'name = "X"' in text
    assert "ideology = Autocracy" in text
    assert "traits = { t1 }" in text
    assert "ruling_party = communism" in text   # Autocracy -> communism


def test_build_without_ruling():
    v = encode_leader("X", "liberalism")
    lines = build_reward_item_lines({"kind": "promote_leader", "enabled": True,
                                     "params": {"leader": v, "setRuling": "no"}})
    text = "\n".join(lines)
    assert "create_country_leader" in text
    assert "set_politics" not in text


def test_build_empty_when_no_leader():
    assert build_reward_item_lines({"kind": "promote_leader", "enabled": True,
                                    "params": {"leader": "", "setRuling": "yes"}}) == []


# ----- parser -----
_HISTORY = """
create_country_leader = {
\tname = "Muammar Gaddafi"
\tpicture = "muammar_al_gaddafi.dds"
\tdesc = LBA_gaddafi_desc
\tideology = Autocracy
\ttraits = { emerging_Autocracy military_career }
}
create_country_leader = {
\tname = "Some Liberal"
\tideology = liberalism
}
"""


def test_parses_leaders_from_text():
    leaders = list(_leaders_from_text(_HISTORY))
    assert [l["name"] for l in leaders] == ["Muammar Gaddafi", "Some Liberal"]
    g = leaders[0]
    assert g["picture"] == "muammar_al_gaddafi.dds"
    assert g["ideology"] == "Autocracy"
    assert g["traits"] == ["emerging_Autocracy", "military_career"]
