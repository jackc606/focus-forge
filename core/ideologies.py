"""Millennium Dawn ideologies — the 5 top ideologies and their sub-ideology
tokens (verified from MD common/ideologies/00_ideologies.txt). Sub-tokens are
used for country_leader.ideology; top ideologies for set_popularities/parties."""
from __future__ import annotations

TOP_IDEOLOGIES = ["democratic", "communism", "fascism", "neutrality", "nationalist"]

IDEOLOGY_TREE = {
    "democratic": ["conservatism", "liberalism", "socialism", "Western_Autocracy"],
    "communism": ["State", "Conservative", "Autocracy", "Vilayat_e_Faqih",
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
