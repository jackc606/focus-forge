"""Hosted assistant mode, core side — no Qt, no network.

The relay Worker (docs/HOSTED_ASSISTANT.md) is mocked at the ``urlopen``
seam: the app must resolve the relay's base URL / token / model, surface the
``X-FF-*`` allotment headers as a ``quota`` event, show the relay's error
messages verbatim, and probe ``/v1/me`` instead of a chat request.
"""
from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from core import agent_loop as al
from core import hosted
from core.agent_loop import (
    BAD_TOKEN_TEXT,
    NO_TOKEN_TEXT,
    SERVICE_UNAVAILABLE_TEXT,
    AgentConfig,
    AgentSession,
    TransportError,
    UrllibTransport,
    friendly_http_error,
    test_connection as probe_connection,
)
from tests.test_agent_loop import FakeTransport, Gate, RecordingExecutor, reply

QUOTA_HEADERS = {"X-FF-Used-Cents": "8", "X-FF-Limit-Cents": "50", "X-FF-Reset": "2026-10-01"}


class _Resp(io.BytesIO):
    """What ``urlopen`` yields: a readable context manager with ``.headers``."""

    def __init__(self, data: bytes, headers=None) -> None:
        super().__init__(data)
        self.headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(url, status, body: dict, headers=None):
    return HTTPError(url, status, "err", dict(headers or {}), io.BytesIO(json.dumps(body).encode()))


def _hosted(token="ffa_abc") -> AgentConfig:
    return AgentConfig(mode="hosted", hosted_token=token, api_key="sk-or-own", model="own/model")


# ----- config -----

def test_effective_fields_resolve_per_mode():
    own = AgentConfig(api_key="sk", model="m/x", base_url="https://openrouter.ai/api/v1")
    assert own.mode == "own" and not own.is_hosted()
    assert (own.effective_base_url(), own.effective_api_key(), own.effective_model()) == (
        "https://openrouter.ai/api/v1", "sk", "m/x")
    h = _hosted()
    assert h.is_hosted()
    assert h.effective_base_url() == hosted.hosted_chat_base() == hosted.HOSTED_BASE_URL + "/v1"
    assert h.effective_api_key() == "ffa_abc"
    assert h.effective_model() == hosted.HOSTED_MODEL_ID == "meta/muse-spark-1.3-contributor"
    # the other pane's values survive untouched
    assert (h.api_key, h.model) == ("sk-or-own", "own/model")
    assert hosted.hosted_signin_url().endswith("/auth/discord/start")
    assert hosted.hosted_me_url().endswith("/v1/me")
    assert al.default_extra_headers(h.effective_base_url()) == {}   # no OpenRouter headers to the relay


# ----- allotment headers -> quota event -----

def test_parse_quota_headers_and_labels():
    q = hosted.parse_quota_headers({k.lower(): v for k, v in QUOTA_HEADERS.items()})
    assert q == {"used_cents": 8.0, "limit_cents": 50.0, "reset": "2026-10-01"}
    assert hosted.parse_quota_headers({"content-type": "application/json"}) is None
    assert hosted.parse_quota_headers({"x-ff-used-cents": "abc", "x-ff-limit-cents": "50"}) is None
    assert hosted.parse_quota_headers(None) is None
    assert hosted.format_allotment(q) == "$0.08 of $0.50 used · resets Oct 1"
    assert hosted.format_allotment({"used_cents": 50, "limit_cents": 50, "reset": ""}) == "$0.50 of $0.50 used"
    assert hosted.format_reset("2026-10-01T00:00:00Z") == "Oct 1"
    assert hosted.format_reset("soon") == "soon"
    assert hosted.format_dollars(None) == "$?"


def test_urllib_transport_records_response_headers(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _Resp(json.dumps(reply("hi")).encode(), QUOTA_HEADERS)

    monkeypatch.setattr(al, "urlopen", fake_urlopen)
    t = UrllibTransport()
    assert t.last_headers == {}
    t.chat({"model": hosted.HOSTED_MODEL_ID, "messages": []}, _hosted())
    assert t.last_headers["x-ff-used-cents"] == "8" and t.last_headers["x-ff-reset"] == "2026-10-01"
    assert seen["url"] == hosted.HOSTED_BASE_URL + "/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer ffa_abc"
    assert "x-title" not in seen["headers"]


def test_session_emits_quota_event_from_headers(monkeypatch):
    monkeypatch.setattr(al, "urlopen",
                        lambda request, timeout=None: _Resp(json.dumps(reply("ok")).encode(), QUOTA_HEADERS))
    events = []
    s = AgentSession(_hosted(), UrllibTransport(), RecordingExecutor(), Gate(),
                     tools=[], system_prompt="SYS", on_event=events.append)
    s.run_turn("hi")
    quota = [e for e in events if e.kind == "quota"]
    assert len(quota) == 1
    assert quota[0].quota == {"used_cents": 8.0, "limit_cents": 50.0, "reset": "2026-10-01"}
    assert isinstance(quota[0].quota["used_cents"], float)
    d = quota[0].to_dict()
    assert d["kind"] == "quota" and d["quota"]["limit_cents"] == 50.0
    assert "quota" in al.EVENT_KINDS
    # the payload went to the relay with the fixed model
    assert [e.kind for e in events] == ["thinking", "usage", "quota", "assistant"]


def test_no_quota_event_without_headers(monkeypatch):
    monkeypatch.setattr(al, "urlopen", lambda request, timeout=None: _Resp(json.dumps(reply("ok")).encode()))
    events = []
    s = AgentSession(AgentConfig(api_key="k"), UrllibTransport(), RecordingExecutor(), Gate(),
                     tools=[], system_prompt="SYS", on_event=events.append)
    s.run_turn("hi")
    assert "quota" not in [e.kind for e in events]
    # a transport with no last_headers at all (the test fakes) is fine too
    events2 = []
    s2 = AgentSession(AgentConfig(api_key="k"), FakeTransport([reply("x")]), RecordingExecutor(), Gate(),
                      tools=[], system_prompt="SYS", on_event=events2.append)
    s2.run_turn("hi")
    assert "quota" not in [e.kind for e in events2]


def test_hosted_payload_uses_relay_model():
    t = FakeTransport([reply("ok")])
    s = AgentSession(_hosted(), t, RecordingExecutor(), Gate(), tools=[], system_prompt="SYS")
    s.run_turn("hi")
    assert t.payloads[0]["model"] == hosted.HOSTED_MODEL_ID


# ----- relay errors -----

def test_relay_error_messages_are_shown_verbatim():
    body = json.dumps({"error": {"message": "You've used your $0.50 for September — it resets on Oct 1.",
                                 "code": "allotment_used"}})
    assert friendly_http_error(402, body) == "You've used your $0.50 for September — it resets on Oct 1."
    body = json.dumps({"error": {"message": "Slow down — more than 4 requests in 10 seconds.",
                                 "code": "rate_limited"}})
    assert friendly_http_error(429, body) == "Slow down — more than 4 requests in 10 seconds."
    body = json.dumps({"error": {"message": "Today's budget is spent — try again tomorrow.",
                                 "code": "budget_exhausted"}})
    assert friendly_http_error(503, body) == "Today's budget is spent — try again tomorrow."
    body = json.dumps({"error": {"message": "Unknown token.", "code": "bad_token"}})
    assert friendly_http_error(401, body) == "Unknown token."
    # a provider message without a relay code keeps the generic prefix
    assert friendly_http_error(429, json.dumps({"error": {"message": "slow"}})) == "Rate limited — wait a moment: slow"
    assert al.relay_error_code("not json") == "" and al.relay_error_code(json.dumps({"error": "x"})) == ""


def test_503_fallback_text():
    assert friendly_http_error(503) == SERVICE_UNAVAILABLE_TEXT
    assert "unavailable right now" in friendly_http_error(503, "not json")
    assert friendly_http_error(500) == "Provider error"


def test_402_from_relay_carries_status_and_quota(monkeypatch):
    body = {"error": {"message": "Allotment used — resets Oct 1.", "code": "allotment_used"}}
    spent = {**QUOTA_HEADERS, "X-FF-Used-Cents": "50"}

    def fake_urlopen(request, timeout=None):
        raise _http_error(request.full_url, 402, body, spent)

    monkeypatch.setattr(al, "urlopen", fake_urlopen)
    events = []
    s = AgentSession(_hosted(), UrllibTransport(), RecordingExecutor(), Gate(),
                     tools=[], system_prompt="SYS", on_event=events.append)
    out = s.run_turn("build")
    assert out == "Allotment used — resets Oct 1."
    kinds = [e.kind for e in events]
    assert kinds == ["thinking", "quota", "error"]
    assert events[1].quota["used_cents"] == 50.0
    assert events[2].status == 402 and events[2].to_dict()["status"] == 402


# ----- test connection in hosted mode -----

def test_hosted_test_connection_hits_me(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["auth"] = request.get_header("Authorization")
        me = {"discord_username": "jack", "used_cents": 8, "limit_cents": 50,
              "period": "2026-09", "reset_at": "2026-10-01", "requests_today": 3}
        return _Resp(json.dumps(me).encode())

    monkeypatch.setattr(al, "urlopen", fake_urlopen)
    msg = probe_connection(_hosted(), UrllibTransport())
    assert msg == "Signed in as jack · $0.08 of $0.50 used this month"
    assert seen["url"] == hosted.hosted_me_url() and seen["method"] == "GET"
    assert seen["auth"] == "Bearer ffa_abc"


def test_hosted_test_connection_errors(monkeypatch):
    with pytest.raises(TransportError) as info:
        probe_connection(_hosted(token=""), UrllibTransport())
    assert info.value.message == NO_TOKEN_TEXT

    def bad(request, timeout=None):
        raise _http_error(request.full_url, 401, {"error": {"message": "bad", "code": "bad_token"}})

    monkeypatch.setattr(al, "urlopen", bad)
    with pytest.raises(TransportError) as info:
        probe_connection(_hosted(), UrllibTransport())
    assert info.value.status == 401 and info.value.message == BAD_TOKEN_TEXT

    def down(request, timeout=None):
        raise _http_error(request.full_url, 503, {"error": {"message": "x", "code": "budget_exhausted"}})

    monkeypatch.setattr(al, "urlopen", down)
    with pytest.raises(TransportError) as info:
        probe_connection(_hosted(), UrllibTransport())
    assert info.value.status == 503 and info.value.message == "x"


def test_own_mode_probe_is_unchanged():
    t = FakeTransport([{"model": "own/model", **reply("OK")}])
    cfg = AgentConfig(api_key="k", model="own/model", hosted_token="ffa_unused")
    assert probe_connection(cfg, t) == "Connected — own/model replied."
    assert t.payloads[0]["model"] == "own/model"
