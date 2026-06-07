"""Tests for the HOI4 state index + English name resolution."""
from __future__ import annotations

from core.state_index import build_state_index, resolve_states, states_for_owner

STATES_A = """
state = {
\tid = 1100
\tname = "STATE_1100"
\thistory = {
\t\towner = LBA
\t\tadd_core_of = LBA
\t}
}
state = {
\tid = 1101
\tname = "STATE_1101"
\thistory = { owner = EGY }
}
state = {
\tid = 1102
\thistory = { owner = LBA }
}
"""

# A later root reassigns 1101 to LBA (mod override).
STATES_B = """
state = {
\tid = 1101
\tname = "STATE_1101"
\thistory = { owner = LBA }
}
"""


def _setup(tmp_path):
    base = tmp_path / "base"
    mod = tmp_path / "mod"
    (base / "history" / "states").mkdir(parents=True)
    (mod / "history" / "states").mkdir(parents=True)
    (base / "history" / "states" / "a.txt").write_text(STATES_A, encoding="utf-8")
    (mod / "history" / "states" / "b.txt").write_text(STATES_B, encoding="utf-8")
    loc = mod / "localisation" / "english"
    loc.mkdir(parents=True)
    (loc / "state_names_l_english.yml").write_text(
        'l_english:\n STATE_1100:0 "Kufra"\n STATE_1101:0 "Tripoli"\n', encoding="utf-8")
    return [str(base), str(mod)]


def test_index_parses_id_name_owner_with_override(tmp_path):
    roots = _setup(tmp_path)
    idx = build_state_index(roots)
    assert idx[1100] == {"owner": "LBA", "name_key": "STATE_1100"}
    assert idx[1101]["owner"] == "LBA"            # later root overrode EGY -> LBA
    assert idx[1102]["name_key"] == "STATE_1102"  # no name field -> fallback key


def test_states_for_owner(tmp_path):
    roots = _setup(tmp_path)
    idx = build_state_index(roots)
    owned = dict(states_for_owner(idx, "LBA"))
    assert set(owned) == {1100, 1101, 1102}
    assert states_for_owner(idx, "EGY") == []     # 1101 was reassigned away


def test_resolve_states_labels_english(tmp_path):
    roots = _setup(tmp_path)
    labels = dict(resolve_states(roots, "LBA"))
    assert labels[1100] == "1100 — Kufra"
    assert labels[1101] == "1101 — Tripoli"
    assert labels[1102] == "1102 — STATE_1102"    # unlocalised falls back to key
