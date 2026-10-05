"""Millennium Dawn ideologies — the 5 top ideologies and their sub-ideology
tokens (verified from MD common/ideologies/00_ideologies.txt, MD 2.0.2). Sub-tokens
are used for country_leader.ideology; top ideologies for set_popularities/parties."""
from __future__ import annotations

import re

TOP_IDEOLOGIES = ["democratic", "communism", "fascism", "neutrality", "nationalist"]

IDEOLOGY_TREE = {
    "democratic": ["conservatism", "liberalism", "socialism", "Western_Autocracy"],
    "communism": ["communist_state", "Conservative", "Autocracy", "Vilayat_e_Faqih",
                  "Mod_Vilayat_e_Faqih", "anarchist_communism"],
    "fascism": ["Kingdom", "Caliphate"],
    "neutrality": ["Neutral_conservatism", "oligarchism", "neutral_Social",
                   "Neutral_Libertarian", "Neutral_Autocracy", "Neutral_Communism",
                   "Neutral_Muslim_Brotherhood", "Neutral_green"],
    "nationalist": ["Nat_Autocracy", "Nat_Fascism", "Nat_Populism", "Monarchist"],
}


def sub_ideology_groups() -> list:
    """[(top, [sub, …])] for grouped dropdowns."""
    return [(top, list(IDEOLOGY_TREE[top])) for top in TOP_IDEOLOGIES]


def all_sub_ideologies() -> list:
    out = []
    for top in TOP_IDEOLOGIES:
        out.extend(IDEOLOGY_TREE[top])
    return out


# Sub-ideology ids MD renamed. MD 2.0.2 turned Communist-State into
# communist_state everywhere it is built from: the ideology itself, its leader
# traits (emerging_…, …_leader), party loc keys (TAG.…_desc) — no old spelling
# survives in 2.0.2. "State" is Focus Forge's own pre-2.0 shorthand.
LEGACY_SUB_IDEOLOGY_RENAMES = {"Communist-State": "communist_state", "State": "communist_state"}

# The old id where MD-derived tokens carry it: on its own, after a scope
# (TAG.Communist-State_desc) or as emerging_Communist-State. A project's own
# ids that merely contain it (MEX_Communist-State_x) are left alone.
_LEGACY_IN_TEXT = re.compile(r"(?:(?<![A-Za-z0-9_\-])|(?<=emerging_))Communist-State(?![A-Za-z0-9-])")


def canonical_sub_ideology(token: str) -> str:
    """The current MD id for a stored sub-ideology (renamed ids map forward)."""
    t = (token or "").strip()
    return LEGACY_SUB_IDEOLOGY_RENAMES.get(t, t)


def rename_legacy_ideology_tokens(text: str):
    """``(new_text, count)`` with MD's renamed sub-ideology updated inside
    script/trait text (Communist-State → communist_state, incl. derived tokens)."""
    return _LEGACY_IN_TEXT.subn("communist_state", text or "")


def has_legacy_ideology_token(text: str) -> bool:
    return bool(_LEGACY_IN_TEXT.search(text or ""))
