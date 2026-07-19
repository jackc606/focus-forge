"""AI-bridge `search_icons` op: matching, limit, exact-first, and the
no-roots note — against a faked sprite index (no real HOI4 install needed)."""
from __future__ import annotations

import json

import pytest

# The bridge lives in the ui layer (Qt). Skip cleanly if PySide6/QtNetwork isn't
# importable in this environment.
pytest.importorskip("PySide6.QtNetwork")

from ui.agent_bridge import _QUIET_OPS, AgentBridge  # noqa: E402

_SPRITES = [
    ("GFX_focus_generic_air_defense", "a.dds"),
    ("GFX_focus_generic_army", "b.dds"),
    ("GFX_focus_generic_industry", "c.dds"),
    ("GFX_focus_nuclear", "d.dds"),
    ("GFX_focus_NUCLEAR_deal", "e.dds"),
]


class _StubProvider:
    def __init__(self, sprites=_SPRITES):
        self._sprites = sprites

    def focus_sprites(self):
        return self._sprites


def _bridge(token="secret-token"):
    """An AgentBridge without Qt's __init__/event loop — pure request logic."""
    b = AgentBridge.__new__(AgentBridge)
    b._model = None
    b._scene = None
    b._token = token
    return b


def _fake_provider(monkeypatch, sprites=_SPRITES):
    import ui.icon_provider as ip
    monkeypatch.setattr(ip, "_INSTANCE", _StubProvider(sprites))


def _ok(resp):
    assert resp["ok"], resp
    return resp["result"]


def test_substring_match_is_case_insensitive(monkeypatch):
    _fake_provider(monkeypatch)
    r = _ok(AgentBridge._search_icons({"query": "nuclear"}))
    assert set(r["icons"]) == {"GFX_focus_nuclear", "GFX_focus_NUCLEAR_deal"}
    assert r["total_matches"] == 2 and r["shown"] == 2


def test_exact_hit_goes_first_and_flags_exact(monkeypatch):
    _fake_provider(monkeypatch)
    r = _ok(AgentBridge._search_icons({"query": "gfx_focus_NUCLEAR"}))
    assert r["icons"][0] == "GFX_focus_nuclear"   # exact (case-insensitive) first
    assert r["exact"] is True
    assert r["total_matches"] == 2


def test_no_exact_key_when_no_exact_match(monkeypatch):
    _fake_provider(monkeypatch)
    r = _ok(AgentBridge._search_icons({"query": "generic"}))
    assert "exact" not in r
    assert r["total_matches"] == 3


def test_limit_caps_shown_but_reports_total(monkeypatch):
    _fake_provider(monkeypatch)
    r = _ok(AgentBridge._search_icons({"query": "GFX_focus", "limit": 2}))
    assert r["shown"] == 2 and len(r["icons"]) == 2
    assert r["total_matches"] == len(_SPRITES)


def test_limit_is_clamped_to_100(monkeypatch):
    many = [(f"GFX_focus_x{i:04d}", "p.dds") for i in range(150)]
    _fake_provider(monkeypatch, many)
    r = _ok(AgentBridge._search_icons({"query": "GFX_focus_x", "limit": 9999}))
    assert r["shown"] == 100 and r["total_matches"] == 150


def test_query_too_short_or_missing_is_an_error(monkeypatch):
    _fake_provider(monkeypatch)
    for bad in ({}, {"query": "a"}, {"query": "  "}, {"query": 3}):
        resp = AgentBridge._search_icons(bad)
        assert resp["ok"] is False and "at least 2" in resp["error"]


def test_bad_limit_is_an_error(monkeypatch):
    _fake_provider(monkeypatch)
    resp = AgentBridge._search_icons({"query": "nuclear", "limit": "lots"})
    assert resp["ok"] is False and "limit" in resp["error"]


def test_empty_index_returns_note_not_error(monkeypatch):
    _fake_provider(monkeypatch, sprites=[])
    r = _ok(AgentBridge._search_icons({"query": "nuclear"}))
    assert r["icons"] == [] and r["total_matches"] == 0
    assert "No icon roots configured" in r["note"]


def test_handled_in_bridge_and_marked_quiet(monkeypatch):
    # Routed GUI-side (never reaches core dispatch, model is None) and quiet
    # (no op_applied narration — this bridge has no initialized signal, so an
    # accidental emit would blow up here).
    _fake_provider(monkeypatch)
    assert "search_icons" in _QUIET_OPS
    b = _bridge()
    line = json.dumps({"op": "search_icons", "args": {"query": "nuclear"},
                       "token": "secret-token", "id": 4}).encode("utf-8")
    resp = b._handle_line(line)
    assert resp["ok"] is True and resp["id"] == 4
    assert resp["result"]["total_matches"] == 2
