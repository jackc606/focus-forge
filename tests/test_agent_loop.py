"""The assistant's tool-calling loop, driven by a fake transport / executor / gate.

No network, no Qt: every branch of ``core.agent_loop`` (argument parsing,
gating, truncation, elision, cancel bookkeeping, error mapping) is exercised
with canned OpenAI-shaped responses, plus one integration test against a real
headless ``ProjectModel`` through ``bridge_dispatch``.
"""
from __future__ import annotations

import copy
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from core import agent_loop as al
from core.agent_loop import (
    AgentConfig,
    AgentSession,
    TransportError,
    UrllibTransport,
    Usage,
    build_system_prompt,
    default_extra_headers,
    default_tools,
    friendly_http_error,
    needs_approval,
    test_connection as probe_connection,
)
from core.agent_pricing import format_cost, format_usage, prices_for
from core.bridge_dispatch import dispatch
from core.md_focus_guide import MD_FOCUS_GUIDE


# ----- fakes ---------------------------------------------------------------------

class FakeTransport:
    """Hands back canned responses in order; an Exception entry is raised."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.payloads: list = []

    def chat(self, payload, config):
        self.payloads.append(copy.deepcopy(payload))
        if not self.responses:
            raise AssertionError("FakeTransport ran out of responses")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _usage(p=100, c=20, cached=0):
    u = {"prompt_tokens": p, "completion_tokens": c}
    if cached:
        u["prompt_tokens_details"] = {"cached_tokens": cached}
    return u


def reply(text, finish="stop", usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": finish}],
            "usage": usage or _usage()}


def tool_reply(calls, usage=None):
    """``calls``: list of (id, name, arguments) — arguments as str or dict."""
    tcs = [{"id": cid, "type": "function",
            "function": {"name": name, "arguments": args}} for cid, name, args in calls]
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": tcs},
                         "finish_reason": "tool_calls"}],
            "usage": usage or _usage()}


class RecordingExecutor:
    def __init__(self, fn=None) -> None:
        self.calls: list = []
        self._fn = fn

    def execute(self, op, args):
        self.calls.append((op, args))
        if self._fn is not None:
            return self._fn(op, args)
        return {"ok": True, "result": {"id": args.get("id", "x")}}


class Gate:
    def __init__(self, answer=True) -> None:
        self.answer = answer
        self.calls: list = []

    def approve(self, op, args):
        self.calls.append((op, args))
        return self.answer


TOOLS = default_tools()


def _session(responses, executor=None, gate=None, config=None, tools=TOOLS,
             system_prompt="SYS"):
    events: list = []
    executor = executor or RecordingExecutor()
    gate = gate or Gate(True)
    s = AgentSession(config or AgentConfig(api_key="k"), FakeTransport(responses),
                     executor, gate, tools=tools, system_prompt=system_prompt,
                     on_event=lambda e: events.append(e))
    return s, executor, gate, events


def _kinds(events):
    return [e.kind for e in events]


# ----- happy path ------------------------------------------------------------------

def test_happy_path_tool_call_then_answer():
    s, ex, _gate, events = _session([
        tool_reply([("c1", "add_focus", json.dumps({"id": "MEX_a", "title": "A"}))],
                   usage=_usage(100, 10, cached=40)),
        reply("Built MEX_a at (0, 5).", usage=_usage(200, 30)),
    ])
    out = s.run_turn("add a focus")
    assert out == "Built MEX_a at (0, 5)."
    assert ex.calls == [("add_focus", {"id": "MEX_a", "title": "A"})]
    # history: system, user, assistant(tool_calls), tool, assistant
    roles = [m["role"] for m in s.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    tool_msg = s.messages[3]
    assert tool_msg["tool_call_id"] == "c1"
    assert json.loads(tool_msg["content"]) == {"ok": True, "result": {"id": "MEX_a"}}
    assert s.messages[2]["tool_calls"][0]["id"] == "c1"   # echoed verbatim
    # usage accumulates over both requests
    assert (s.usage.prompt_tokens, s.usage.completion_tokens, s.usage.cached_tokens,
            s.usage.requests) == (300, 40, 40, 2)
    assert _kinds(events) == ["thinking", "usage", "tool_call", "tool_result",
                              "thinking", "usage", "assistant"]
    payload = s.transport.payloads[0]
    assert payload["model"] == "meta/muse-spark-1.3-contributor"
    assert payload["tool_choice"] == "auto" and payload["tools"] is not None
    assert payload["temperature"] == 0.3


def test_two_tool_calls_in_one_message_yield_two_tool_messages_in_order():
    s, ex, _g, _e = _session([
        tool_reply([("c1", "add_focus", {"id": "A"}), ("c2", "add_focus", {"id": "B"})]),
        reply("done"),
    ])
    s.run_turn("go")
    assert [c[1]["id"] for c in ex.calls] == ["A", "B"]
    tools = [m for m in s.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tools] == ["c1", "c2"]


def test_empty_reply_becomes_no_reply_placeholder():
    s, *_ = _session([reply("")])
    assert s.run_turn("hi") == "(no reply)"


# ----- model mistakes --------------------------------------------------------------

def test_malformed_json_arguments_get_a_self_correcting_error():
    s, ex, _g, events = _session([
        tool_reply([("c1", "add_focus", '{"id": "MEX_a", ')]),
        tool_reply([("c2", "add_focus", '{"id": "MEX_a"}')]),
        reply("fixed"),
    ])
    assert s.run_turn("go") == "fixed"
    first = json.loads(s.messages[3]["content"])
    assert first["ok"] is False
    assert first["error"].startswith("arguments were not valid JSON:")
    assert "JSON object matching the tool schema" in first["error"]
    assert ex.calls == [("add_focus", {"id": "MEX_a"})]   # only the corrected call ran


def test_unknown_tool_name_lists_available_tools():
    s, ex, _g, _e = _session([
        tool_reply([("c1", "make_focus", "{}")]),
        reply("ok"),
    ])
    s.run_turn("go")
    res = json.loads(s.messages[3]["content"])
    assert res["ok"] is False
    assert res["error"].startswith("Unknown tool 'make_focus'. Available: ")
    assert "add_focus" in res["error"] and "batch" in res["error"]
    assert ex.calls == []


# ----- gating -----------------------------------------------------------------------

def test_gated_op_approved_executes():
    gate = Gate(True)
    s, ex, _g, events = _session([
        tool_reply([("c1", "delete_focus", {"id": "MEX_a"})]), reply("deleted"),
    ], gate=gate)
    s.run_turn("delete it")
    assert gate.calls == [("delete_focus", {"id": "MEX_a"})]
    assert ex.calls == [("delete_focus", {"id": "MEX_a"})]
    assert "approval_denied" not in _kinds(events)


def test_gated_op_denied_is_not_executed():
    gate = Gate(False)
    s, ex, _g, events = _session([
        tool_reply([("c1", "save", {})]), reply("ok, not saving"),
    ], gate=gate)
    s.run_turn("save")
    assert ex.calls == []
    res = json.loads(s.messages[3]["content"])
    assert res["ok"] is False and "declined" in res["error"]
    denied = [e for e in events if e.kind == "approval_denied"]
    assert len(denied) == 1 and denied[0].op == "save"


def test_non_destructive_ops_never_hit_the_gate():
    gate = Gate(False)
    s, ex, _g, _e = _session([
        tool_reply([("c1", "list_focuses", {})]), reply("ok"),
    ], gate=gate)
    s.run_turn("list")
    assert gate.calls == [] and len(ex.calls) == 1


def test_batch_containing_delete_is_gated_exactly_once():
    gate = Gate(True)
    batch_args = {"ops": [{"op": "delete_focus", "args": {"id": "a"}},
                          {"op": "delete_focus", "args": {"id": "b"}},
                          {"op": "add_focus", "args": {"id": "c"}}]}
    s, ex, _g, _e = _session([
        tool_reply([("c1", "batch", batch_args)]), reply("ok"),
    ], gate=gate)
    s.run_turn("go")
    assert len(gate.calls) == 1 and gate.calls[0][0] == "batch"
    assert ex.calls == [("batch", batch_args)]
    assert needs_approval("batch", {"ops": [{"op": "add_focus", "args": {}}]}) is False
    assert needs_approval("batch", batch_args) is True
    assert needs_approval("export", {}) is True


# ----- size management -------------------------------------------------------------

def test_huge_tool_result_is_truncated_with_note():
    big = {"ok": True, "result": {"blob": "x" * 50_000}}
    cfg = AgentConfig(api_key="k", max_tool_result_chars=2_000)
    s, ex, _g, _e = _session([
        tool_reply([("c1", "get_project", {})]), reply("ok"),
    ], executor=RecordingExecutor(lambda op, a: big), config=cfg)
    s.run_turn("go")
    content = s.messages[3]["content"]
    total = len(json.dumps(big, ensure_ascii=False))
    assert content.endswith("or reference_data sections to fetch less]")
    assert f"…[truncated: {total} chars total" in content
    assert len(content) <= 2_000 - 300 + 200   # body bound + the note


def test_context_elision_replaces_oldest_tool_results_only():
    payload = {"ok": True, "result": {"blob": "y" * 3_000}}
    cfg = AgentConfig(api_key="k", context_budget_chars=12_000)
    calls = [(f"c{i}", "list_focuses", {}) for i in range(6)]
    s, ex, _g, _e = _session([
        tool_reply(calls), reply("done"),
    ], executor=RecordingExecutor(lambda op, a: payload), config=cfg)
    s.run_turn("go")
    # Turn 1 is ~19k chars, over budget, but the six tool results ARE the last
    # six messages when the budget is enforced — protected, so nothing is elided.
    assert all(m["content"] != al.ELIDED_TEXT for m in s.messages)
    assert s.messages[0] == {"role": "system", "content": "SYS"}
    # Turn 2 pushes them out of the protected window: oldest go first, and only
    # as many as needed to get back under budget.
    s.transport.responses = [tool_reply([("d1", "list_focuses", {})]), reply("again")]
    s.run_turn("more")
    tools = [m for m in s.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tools] == ["c0", "c1", "c2", "c3", "c4", "c5", "d1"]
    elided = [m["tool_call_id"] for m in tools if m["content"] == al.ELIDED_TEXT]
    # Oldest first, a contiguous prefix, never the two inside the protected
    # window (c4, c5 are among the last six messages) nor the fresh d1.
    assert elided and elided == [f"c{i}" for i in range(len(elided))]
    assert len(elided) <= 4
    assert s.messages[0]["content"] == "SYS"
    assert all(m.get("content") != al.ELIDED_TEXT for m in s.messages[-6:])
    assert sum(al._message_chars(m) for m in s.messages) <= 12_000


# ----- cancel ----------------------------------------------------------------------

def test_cancel_between_tool_calls_keeps_history_valid():
    flag = {"stop": False}

    def executor_fn(op, args):
        flag["stop"] = True          # user hits Stop while the first tool runs
        return {"ok": True, "result": {"id": args["id"]}}

    ex = RecordingExecutor(executor_fn)
    s, _ex, _g, events = _session([
        tool_reply([("c1", "add_focus", {"id": "A"}), ("c2", "add_focus", {"id": "B"}),
                    ("c3", "add_focus", {"id": "C"})]),
        reply("never reached"),
    ], executor=ex)
    out = s.run_turn("go", cancel=lambda: flag["stop"])
    assert out == "(stopped by user)"
    assert [c[1]["id"] for c in ex.calls] == ["A"]        # only the first ran
    tools = [m for m in s.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tools] == ["c1", "c2", "c3"]   # every call answered
    assert json.loads(tools[1]["content"]) == {"ok": False, "error": "cancelled by user"}
    assert s.messages[-1] == {"role": "assistant", "content": "(stopped by user)"}
    assert "cancelled" in _kinds(events)
    assert len(s.transport.responses) == 1     # no second request was made


def test_cancel_before_first_request_makes_no_call():
    s, ex, _g, events = _session([reply("x")])
    out = s.run_turn("go", cancel=lambda: True)
    assert out == "(stopped by user)" and s.transport.payloads == []
    assert s.messages[-1]["role"] == "user"   # nothing synthetic needed after a user msg
    assert _kinds(events) == ["cancelled"]


# ----- limits & errors --------------------------------------------------------------

def test_max_rounds_exhausted_message():
    cfg = AgentConfig(api_key="k", max_rounds=2)
    s, ex, _g, events = _session([
        tool_reply([("c1", "list_focuses", {})]),
        tool_reply([("c2", "list_focuses", {})]),
        reply("unreached"),
    ], config=cfg)
    out = s.run_turn("go")
    assert out == "Stopped after 2 tool rounds. Say 'continue' to keep going."
    assert events[-1].kind == "error" and events[-1].text == out
    assert len(ex.calls) == 2


def test_finish_reason_length_emits_error_and_returns_text():
    s, _ex, _g, events = _session([reply("half a sen", finish="length")])
    assert s.run_turn("go") == "half a sen"
    errs = [e for e in events if e.kind == "error"]
    assert errs and "cut off" in errs[0].text
    assert events[-1].kind == "assistant"


@pytest.mark.parametrize("status,expected", [
    (401, "API key rejected"), (402, "Out of credits"),
    (429, "Rate limited — wait a moment"), (503, "Provider error"),
])
def test_transport_error_is_friendly_and_keeps_user_message(status, expected):
    body = json.dumps({"error": {"message": "nope"}})
    s, _ex, _g, events = _session([TransportError(status, friendly_http_error(status, body))])
    out = s.run_turn("go")
    assert out.startswith(expected) and out.endswith(": nope")
    assert events[-1].kind == "error" and events[-1].text == out
    assert s.messages[-1] == {"role": "user", "content": "go"}   # retryable


def test_friendly_http_error_without_body():
    assert friendly_http_error(401) == "API key rejected"
    assert friendly_http_error(418) == "Request failed (HTTP 418)"
    assert friendly_http_error(500, "not json") == "Provider error"


def test_urllib_transport_maps_http_and_network_errors(monkeypatch):
    cfg = AgentConfig(api_key="secret", base_url="https://openrouter.ai/api/v1/",
                      extra_headers={"X-Title": "Focus Forge"})
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode("utf-8"))
        raise HTTPError(request.full_url, 402, "Payment Required", {},
                        io.BytesIO(b'{"error":{"message":"add credits"}}'))

    monkeypatch.setattr(al, "urlopen", fake_urlopen)
    with pytest.raises(TransportError) as info:
        UrllibTransport().chat({"model": "m", "messages": []}, cfg)
    assert info.value.status == 402
    assert info.value.message == "Out of credits: add credits"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer secret"
    assert seen["headers"]["x-title"] == "Focus Forge"
    assert seen["body"]["model"] == "m"

    def down(request, timeout=None):
        raise URLError("no route")

    monkeypatch.setattr(al, "urlopen", down)
    with pytest.raises(TransportError) as info:
        UrllibTransport().chat({}, cfg)
    assert info.value.status == 0 and "Couldn't reach the provider" in info.value.message


def test_urllib_transport_parses_success(monkeypatch):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(al, "urlopen",
                        lambda request, timeout=None: Resp(json.dumps(reply("hi")).encode()))
    data = UrllibTransport().chat({"model": "m"}, AgentConfig(api_key="k"))
    assert data["choices"][0]["message"]["content"] == "hi"


# ----- system prompt / tools / config ----------------------------------------------

def test_build_system_prompt_contains_guide_project_and_screenshot_note():
    hello = dispatch(__import__("ui.project_model", fromlist=["ProjectModel"]).ProjectModel(),
                     "hello", {})["result"]
    text = build_system_prompt(hello, MD_FOCUS_GUIDE)
    assert text.startswith("You are the Focus Forge assistant.")
    assert hello["project"]["name"] in text and "country tag MEX" in text
    assert "## Procedure (follow in order)" in text          # the guide is in
    assert "`screenshot` renders a PNG for the USER" in text
    assert "The canvas updates live" in text
    assert text.index("Open project:") < text.index("## Procedure")
    assert text.index("## Procedure") < text.index("Never claim success")
    # also accepts the bare project dict
    assert "Open project: X" in build_system_prompt({"name": "X"}, "")


def test_default_tools_exclude_panel_affairs():
    names = {t["function"]["name"] for t in default_tools()}
    assert not names & {"hello", "describe_op", "guide", "load_project"}
    assert {"add_focus", "batch", "save", "export", "screenshot", "search_icons"} <= names


def test_openrouter_headers_only_for_openrouter():
    assert default_extra_headers("https://openrouter.ai/api/v1") == {
        "HTTP-Referer": "https://focusforgemod.com", "X-Title": "Focus Forge"}
    assert default_extra_headers("http://localhost:1234/v1") == {}


def test_reset_clears_history_but_keeps_system_prompt():
    s, *_ = _session([reply("a")])
    s.run_turn("x")
    s.reset()
    assert s.messages == [{"role": "system", "content": "SYS"}]
    assert s.usage.requests == 0


def test_test_connection_with_fake_transport():
    t = FakeTransport([{"model": "meta/muse-spark-1.3-contributor", **reply("OK")}])
    msg = probe_connection(AgentConfig(api_key="k"), t)
    assert msg == "Connected — meta/muse-spark-1.3-contributor replied."
    assert t.payloads[0]["max_tokens"] == 1
    with pytest.raises(TransportError) as info:
        probe_connection(AgentConfig(api_key=""), t)
    assert "No API key" in info.value.message
    with pytest.raises(TransportError):
        probe_connection(AgentConfig(api_key="k"), FakeTransport([TransportError(401, "API key rejected")]))


def test_usage_cost_and_labels():
    u = Usage(prompt_tokens=12_400, completion_tokens=2_100)
    assert u.cost_usd(0.10, 0.20) == pytest.approx((12_400 * 0.10 + 2_100 * 0.20) / 1e6)
    assert prices_for("meta/muse-spark-1.3-contributor") == (0.10, 0.20, 0.002)
    assert prices_for("meta/muse-spark-1.3-contributor:nitro") == (0.10, 0.20, 0.002)
    assert prices_for("someone/unknown") is None
    assert format_usage(u, "meta/muse-spark-1.3-contributor") == "12.4k in · 2.1k out · ~$0.002"
    assert format_cost(u, "someone/unknown") == "~$?"


def test_cached_tokens_are_billed_at_cache_price_and_shown():
    # 1M input of which 820k were cache hits: fresh 180k @0.10 + cached 820k @0.002 + 30k out @0.20
    u = Usage(prompt_tokens=1_000_000, completion_tokens=30_000, cached_tokens=820_000)
    assert u.cost_usd(0.10, 0.20, 0.002) == pytest.approx(
        (180_000 * 0.10 + 820_000 * 0.002 + 30_000 * 0.20) / 1e6)
    assert u.cost_usd(0.10, 0.20) == pytest.approx((1_000_000 * 0.10 + 30_000 * 0.20) / 1e6)
    assert format_usage(u, "meta/muse-spark-1.3-contributor") == "1.0M in (82% cached) · 30.0k out · ~$0.03"
    # cached can never exceed prompt (defensive against odd provider numbers)
    assert Usage(prompt_tokens=10, cached_tokens=50).cost_usd(1.0, 1.0, 0.0) == 0.0


def test_successful_batch_results_are_compacted_in_history():
    full = {"ok": True, "result": {"results": [{"id": "MEX_a"}, {"id": "MEX_b"}, {"message": "Linked a > b"}],
                                   "count": 3, "summary": {"errors": 0, "warnings": 1},
                                   "issues": [{"severity": "warning", "code": "x", "message": "m"}]}}
    c = al.compact_tool_result("batch", full)
    assert c == {"ok": True, "result": {"count": 3, "ids": ["MEX_a", "MEX_b", "Linked a > b"],
                                        "summary": {"errors": 0, "warnings": 1},
                                        "issues": [{"severity": "warning", "code": "x", "message": "m"}]}}
    failed = {"ok": False, "error": "Batch failed at op 1"}
    assert al.compact_tool_result("batch", failed) is failed
    other = {"ok": True, "result": {"results": [1, 2]}}
    assert al.compact_tool_result("list_focuses", other) is other


def test_batch_compaction_reaches_the_history():
    big = {"ok": True, "result": {"results": [{"id": f"MEX_{i}", "title": "t" * 200} for i in range(20)],
                                  "count": 20, "summary": {"errors": 0, "warnings": 0}, "issues": []}}
    s, _ex, _g, _ev = _session([tool_reply([("c1", "batch", {"ops": []})]), reply("done")],
                                executor=RecordingExecutor(lambda op, args: big))
    s.run_turn("go")
    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert "MEX_19" in tool_msg["content"] and '"title"' not in tool_msg["content"]


def test_default_budget_keeps_requests_small():
    cfg = AgentConfig()
    assert cfg.context_budget_chars <= 160_000 and cfg.max_tool_result_chars <= 8_000


def test_event_to_dict_is_plain():
    e = al.AgentEvent("usage", usage=Usage(1, 2, 3, 4))
    d = e.to_dict()
    assert d["kind"] == "usage" and d["usage"] == {
        "prompt_tokens": 1, "completion_tokens": 2, "cached_tokens": 3, "requests": 4,
        "cache_write_tokens": 0}


def test_payload_carries_session_id_and_cache_control():
    s, _ex, _g, _e = _session([reply("hi")])
    s.run_turn("hello")
    sent = s.transport.payloads[0]
    assert sent["cache_control"] == {"type": "ephemeral"}
    assert sent["session_id"].startswith("ff-") and len(sent["session_id"]) < 256
    first = sent["session_id"]
    s.transport.responses = [reply("again")]
    s.run_turn("more")
    assert s.transport.payloads[1]["session_id"] == first, "stable within a conversation"
    s.reset()
    assert s.session_id != first, "new chat, new cache identity"
    off, _ex, _g, _e = _session([reply("hi")], config=AgentConfig(api_key="k", prompt_caching=False))
    off.run_turn("hello")
    assert "session_id" not in off.transport.payloads[0] and "cache_control" not in off.transport.payloads[0]


def test_elision_uses_hysteresis_so_the_prefix_changes_rarely():
    payload = {"ok": True, "result": {"blob": "y" * 3_000}}
    cfg = AgentConfig(api_key="k", context_budget_chars=40_000)
    # Ten 3k results in turn 1 (~31k, under budget: nothing elided).
    s, _ex, _g, _e = _session([tool_reply([(f"c{i}", "list_focuses", {}) for i in range(10)]), reply("ok")],
                              executor=RecordingExecutor(lambda op, a: payload), config=cfg)
    s.run_turn("go")
    assert all(m.get("content") != al.ELIDED_TEXT for m in s.messages)
    # Turn 2 adds four more (~43k > 40k): one pass drops to <= half the budget,
    # not just barely under it — so turn 3 (another ~3k) is a pure cache read.
    s.transport.responses = [tool_reply([(f"d{i}", "list_focuses", {}) for i in range(4)]), reply("ok")]
    s.run_turn("more")
    total_after = sum(al._message_chars(m) for m in s.messages)
    assert total_after <= 20_000
    snapshot = [dict(m) for m in s.messages]
    s.transport.responses = [tool_reply([("e0", "list_focuses", {})]), reply("ok")]
    s.run_turn("again")
    assert s.messages[:len(snapshot)] == snapshot, "no earlier message was rewritten"


def test_elision_also_blanks_old_tool_call_arguments():
    # The model's own batch arguments dominate a real history; tool results are
    # tiny after compaction. Elision must be able to reclaim the arguments.
    big_args = json.dumps({"ops": [{"op": "add_focus", "args": {"id": f"MEX_{i}", "description": "d" * 400}} for i in range(20)]})
    cfg = AgentConfig(api_key="k", context_budget_chars=30_000)
    small = {"ok": True, "result": {"count": 20, "ids": ["MEX_0"], "issues": []}}
    s, _ex, _g, _e = _session([tool_reply([("b1", "batch", big_args)]), reply("built")],
                              executor=RecordingExecutor(lambda op, a: small), config=cfg)
    s.run_turn("go")                       # ~9k chars, under budget
    s.transport.responses = [tool_reply([("b2", "batch", big_args)]), reply("built")]
    s.run_turn("more")                     # ~18k, still under
    s.transport.responses = [tool_reply([("b3", "batch", big_args)]), tool_reply([("b4", "batch", big_args)]), reply("built")]
    s.run_turn("again")                    # crosses 30k -> elide to <= 15k
    total = sum(al._message_chars(m) for m in s.messages)
    # b3 and b4 sit inside the protected recent window (~9k each), so the floor
    # is what they weigh; everything older must have been reclaimed.
    assert total < 24_000, total
    calls = [m for m in s.messages if m.get("role") == "assistant" and m.get("tool_calls")]
    assert [c["tool_calls"][0]["function"]["arguments"] == al.ELIDED_ARGS for c in calls] == [True, True, False, False]
    assert calls[0]["tool_calls"][0]["id"] == "b1", "ids kept so tool messages still pair"
    last_call = [m for m in s.messages if m.get("role") == "assistant" and m.get("tool_calls")][-1]
    assert last_call["tool_calls"][0]["function"]["arguments"] == big_args, "recent window untouched"


def test_assistant_history_keeps_only_role_content_tool_calls():
    calls = [("c1", "list_focuses", {})]
    resp = tool_reply(calls)
    resp["choices"][0]["message"]["reasoning"] = "x" * 5000
    resp["choices"][0]["message"]["annotations"] = [{"a": 1}]
    s, _ex, _g, _e = _session([resp, reply("done")])
    s.run_turn("go")
    stored = s.messages[2]
    assert set(stored) == {"role", "content", "tool_calls"}
    assert stored["tool_calls"][0]["id"] == "c1"
    assert AgentConfig().max_rounds >= 60


def test_cache_primed_label():
    u = Usage(prompt_tokens=20_000, completion_tokens=500, cache_write_tokens=9_000)
    assert format_usage(u, "meta/muse-spark-1.3-contributor").startswith("20.0k in (cache primed)")
    u = Usage(prompt_tokens=20_000, completion_tokens=500, cached_tokens=9_000, cache_write_tokens=9_000)
    assert "(45% cached)" in format_usage(u, "meta/muse-spark-1.3-contributor")


# ----- executor integration: real model through bridge_dispatch ---------------------

class DispatchExecutor:
    def __init__(self, model) -> None:
        self.model = model

    def execute(self, op, args):
        return dispatch(self.model, op, args)


def test_batch_through_real_project_model():
    from ui.project_model import ProjectModel
    m = ProjectModel()   # sample MEX project (3 focuses)
    before = len(m.project.focuses)
    batch = {"ops": [
        {"op": "add_focus", "args": {"id": "MEX_ag_a", "title": "A", "x": 0, "y": 20, "cost": 10}},
        {"op": "add_focus", "args": {"id": "MEX_ag_b", "title": "B", "x": 0, "y": 21, "cost": 5,
                                     "prerequisites": ["MEX_ag_a"]}},
        {"op": "add_focus", "args": {"id": "MEX_ag_c", "title": "C", "x": 2, "y": 21, "cost": 5,
                                     "prerequisites": ["MEX_ag_a"]}},
    ]}
    s, _ex, _g, events = _session([
        tool_reply([("c1", "batch", json.dumps(batch))]),
        reply("Added three focuses under row 20."),
    ], executor=DispatchExecutor(m))
    out = s.run_turn("add a 3-focus branch")
    assert out.startswith("Added three")
    assert len(m.project.focuses) == before + 3
    assert {f.id for f in m.project.focuses} >= {"MEX_ag_a", "MEX_ag_b", "MEX_ag_c"}
    result = json.loads(s.messages[3]["content"])
    assert result["ok"] and result["result"]["count"] == 3
    assert "issues" in result["result"] and "summary" in result["result"]
    tr = [e for e in events if e.kind == "tool_result"][0]
    assert tr.op == "batch" and tr.result["ok"]
