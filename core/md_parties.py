"""Millennium Dawn's global party / sub-ideology index.

MD's ``party_pop_array`` and ``party_index`` use a single, GLOBAL ordering of
24 parties (sub-ideologies) — the same index means the same party in every
country (e.g. index 1 is always "Western Conservatives"). The
``add_relative_party_popularity`` helper picks the party to shift by this index.

Source: MD ``common/scripted_effects/00_subideology_scripted_effects.txt``
(the per-party ``# comment`` labels) + ``attract_voters_pos.*`` localisation for
the two Khomeinist entries (8/9).
"""
from __future__ import annotations

# (party_index, display name), ordered by index. Index order roughly groups the
# parties by their top ideology: 0-3 democratic, 4-9 communism (incl. the two
# Vilayat-e Faqih theocracies), 10-12 Islamic, 13-19 neutrality, 20-23 nationalist.
MD_PARTIES = [
    (0, "Western Autocrats"),
    (1, "Western Conservatives"),
    (2, "Western Liberals"),
    (3, "Western Socialists"),
    (4, "Emerging Communists"),
    (5, "Emerging Left-Wing Radicals"),
    (6, "Emerging Reactionaries"),
    (7, "Emerging Autocrats"),
    (8, "Moderate Vilayat-e Faqih"),
    (9, "Vilayat-e Faqih"),
    (10, "Salafist Kingdom"),
    (11, "Salafist Caliphate"),
    (12, "Neutral Moderate Islam"),
    (13, "Neutral Autocrats"),
    (14, "Neutral Conservatives"),
    (15, "Neutral Oligarchs"),
    (16, "Neutral Libertarians"),
    (17, "Neutral Greens"),
    (18, "Neutral Socialists"),
    (19, "Neutral Communists"),
    (20, "Nationalist Populists"),
    (21, "Nationalist Fascists"),
    (22, "Nationalist Military Junta"),
    (23, "Nationalist Monarchists"),
]
