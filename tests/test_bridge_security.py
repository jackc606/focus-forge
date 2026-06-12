"""AI-bridge security hardening: request authentication (shared token),
screenshot-path confinement, and the oversized-request guard."""
from __future__ import annotations

import json

import pytest

# The bridge lives in the ui layer (Qt). Skip cleanly if PySide6/QtNetwork isn't
# importable in this environment.
pytest.importorskip("PySide6.QtNetwork")

from ui.agent_bridge import AgentBridge, _MAX_REQUEST_BYTES  # noqa: E402


def _bridge(token="secret-token"):
    """An AgentBridge without going through Qt's __init__/event loop — we only
    exercise the pure request-handling logic."""
    b = AgentBridge.__new__(AgentBridge)
    b._model = None
    b._scene = None
    b._token = token
    return b


def test_request_without_token_is_rejected():
    b = _bridge()
    resp = b._handle_line(json.dumps({"op": "hello"}).encode("utf-8"))
    assert resp["ok"] is False and "Unauthorized" in resp["error"]


def test_request_with_wrong_token_is_rejected():
    b = _bridge()
    resp = b._handle_line(json.dumps({"op": "hello", "token": "nope"}).encode("utf-8"))
    assert resp["ok"] is False and "Unauthorized" in resp["error"]


def test_unauthorized_response_echoes_id_but_not_token():
    b = _bridge()
    resp = b._handle_line(json.dumps({"op": "hello", "id": 7}).encode("utf-8"))
    assert resp["ok"] is False
    assert resp["id"] == 7            # correlation id preserved for the client
    assert "token" not in resp        # never reflect the secret back


def test_no_token_configured_authorizes_nothing():
    b = _bridge(token="")
    assert b._authorized("") is False
    assert b._authorized("anything") is False


def test_authorized_accepts_exact_token():
    b = _bridge(token="abc123")
    assert b._authorized("abc123") is True
    assert b._authorized("abc124") is False
    assert b._authorized(None) is False
    assert b._authorized(123) is False  # non-string


def test_bad_json_rejected_before_auth():
    # A malformed body fails fast without leaking whether a token would've worked.
    b = _bridge()
    resp = b._handle_line(b"{not json")
    assert resp["ok"] is False and "Bad JSON" in resp["error"]
    resp = b._handle_line(b"[1, 2, 3]")
    assert resp["ok"] is False and "expected a JSON object" in resp["error"]


def test_screenshot_uses_a_fixed_path_not_a_client_one():
    # Guard against re-introducing the arbitrary-file-write vector: the screenshot
    # op must write to the fixed app-owned canvas.png, never a path from args.
    import inspect
    import ui.agent_bridge as ab
    src = inspect.getsource(ab.AgentBridge._screenshot)
    assert 'args.get("path")' not in src
    assert 'args["path"]' not in src
    assert "canvas.png" in src


def test_max_request_bytes_is_bounded():
    # Sanity: the cap exists and is a sane, finite size.
    assert 0 < _MAX_REQUEST_BYTES <= 64 * 1024 * 1024
