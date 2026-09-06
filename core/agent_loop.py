"""The in-app assistant's brain: an OpenAI-style tool-calling loop over the bridge ops — Qt-free.

Why this lives in ``core``: everything that decides *what happens* (which tool
runs, what the model is told when it makes a mistake, when the user is asked
for approval, how history is kept valid on cancel) is plain Python here, so it
is unit-tested with a fake transport / executor / gate and never needs a
QApplication. The UI (``ui/assistant_panel.py``) only renders the events this
module emits and answers its three blocking questions (send this HTTP request,
run this op, may I do this destructive thing) on the right threads.

Protocol: the hosted provider is any ``/chat/completions`` endpoint that speaks
OpenAI function tools (OpenRouter by default). Tools are the bridge op specs
(``core.bridge_specs.tool_schemas``), so the model edits the project through
exactly the vocabulary the MCP server exposes.
"""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge_specs import tool_schemas

# Ops that destroy work or touch disk: the user is asked before each one.
# `load_project` is listed for completeness even though the default tool set
# excludes it (a caller passing its own tool list still gets the gate).
DESTRUCTIVE_OPS = frozenset({
    "save", "export", "load_project", "delete_focus", "delete_focuses",
    "delete_idea", "delete_event", "delete_decision", "delete_decision_category",
})

# Not offered to the model: hello/guide are baked into the system prompt,
# describe_op is redundant with the tool schemas, and the user opens files.
EXCLUDED_TOOLS = ("hello", "describe_op", "guide", "load_project")

DECLINED_TEXT = ("The user declined this action. Do not retry it; ask them what "
                 "they'd like instead.")
CANCELLED_TOOL = {"ok": False, "error": "cancelled by user"}
STOPPED_TEXT = "(stopped by user)"
ELIDED_TEXT = "[elided earlier tool result]"
NO_REPLY_TEXT = "(no reply)"
CUT_OFF_TEXT = "The reply was cut off (output limit). Ask the assistant to continue."
# Never elide the newest messages: the model needs its own last tool round intact.
KEEP_RECENT = 6

OPENROUTER_HEADERS = {"HTTP-Referer": "https://focusforgemod.com", "X-Title": "Focus Forge"}


# ----- configuration --------------------------------------------------------------

@dataclass
class AgentConfig:
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    model: str = "meta/muse-spark-1.3-contributor"
    max_rounds: int = 40          # tool rounds per user turn
    temperature: float = 0.3
    timeout_s: int = 120
    # Every round resends the whole history, so these two numbers ARE the
    # input-token bill: a 15-focus build at the old 400k budget cost ~1M input
    # tokens. ~35k tokens per request keeps quality (the model rarely needs a
    # focus list it read twenty calls ago) at roughly a third of the cost.
    max_tool_result_chars: int = 8_000    # longer tool results are truncated with a note
    context_budget_chars: int = 140_000   # when exceeded, elide the oldest tool results
    extra_headers: dict = field(default_factory=dict)  # OpenRouter likes HTTP-Referer / X-Title


def default_extra_headers(base_url: str) -> dict:
    """OpenRouter attributes traffic to an app via these headers; other
    providers get none (they'd be ignored, but keep requests minimal)."""
    return dict(OPENROUTER_HEADERS) if "openrouter.ai" in (base_url or "") else {}


# ----- transport -------------------------------------------------------------------

class TransportError(Exception):
    """The provider couldn't be reached or refused the request. ``message`` is
    already user-facing."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Transport(Protocol):
    def chat(self, payload: dict, config: AgentConfig) -> dict: ...


def friendly_http_error(status: int, body: str = "") -> str:
    """Map an HTTP failure to a sentence a modder can act on, keeping the
    provider's own message (``{"error": {"message": ...}}``) when it has one."""
    if status == 401:
        text = "API key rejected"
    elif status == 402:
        text = "Out of credits"
    elif status == 429:
        text = "Rate limited — wait a moment"
    elif status >= 500:
        text = "Provider error"
    else:
        text = f"Request failed (HTTP {status})"
    detail = provider_error_message(body)
    return f"{text}: {detail}" if detail else text


def provider_error_message(body: str) -> str:
    try:
        data = json.loads(body or "")
    except ValueError:
        return ""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or "").strip()
    if isinstance(err, str):
        return err.strip()
    return ""


class UrllibTransport:
    """The real transport. ``urllib`` rather than QtNetwork because TLS via
    urllib is what already works inside the PyInstaller build
    (``core.update_check``); QtNetwork's TLS backend does not ship."""

    def chat(self, payload: dict, config: AgentConfig) -> dict:
        url = config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FocusForge-Assistant",
        }
        headers.update(config.extra_headers or {})
        body = json.dumps(payload).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=config.timeout_s) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8", "replace")
            except Exception:
                err_body = ""
            raise TransportError(exc.code, friendly_http_error(exc.code, err_body)) from exc
        except (URLError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise TransportError(0, f"Couldn't reach the provider ({reason}).") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise TransportError(0, "The provider returned something that wasn't JSON.") from exc
        if not isinstance(data, dict):
            raise TransportError(0, "The provider returned an unexpected response shape.")
        if "error" in data and not data.get("choices"):
            # Some providers answer 200 with an error envelope.
            raise TransportError(0, provider_error_message(raw) or "Provider error")
        return data


def test_connection(config: AgentConfig, transport: Transport) -> str:
    """The settings dialog's 'Test connection': one tiny request. Returns a
    success sentence; raises :class:`TransportError` on failure."""
    if not config.api_key:
        raise TransportError(0, "No API key entered.")
    payload = {"model": config.model,
               "messages": [{"role": "user", "content": "Reply with OK."}],
               "max_tokens": 1}
    data = transport.chat(payload, config)
    model = data.get("model") or config.model
    return f"Connected — {model} replied."


# ----- collaborators the UI provides ------------------------------------------------

class ToolExecutor(Protocol):
    def execute(self, op: str, args: dict) -> dict: ...


class ApprovalGate(Protocol):
    def approve(self, op: str, args: dict) -> bool: ...


# ----- usage --------------------------------------------------------------------------

@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    requests: int = 0

    def cost_usd(self, price_in_per_m: float, price_out_per_m: float,
                 price_cached_per_m: "float | None" = None) -> float:
        """Cached prompt tokens are billed at the cache-read price when the
        model has one; otherwise they cost the same as fresh input."""
        cached = min(self.cached_tokens, self.prompt_tokens)
        fresh = self.prompt_tokens - cached
        cached_price = price_in_per_m if price_cached_per_m is None else price_cached_per_m
        return (fresh * price_in_per_m + cached * cached_price
                + self.completion_tokens * price_out_per_m) / 1_000_000

    def add(self, usage) -> None:
        """Fold one response's ``usage`` block in (tolerates None / partial)."""
        self.requests += 1
        if not isinstance(usage, dict):
            return
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details")
        if isinstance(details, dict):
            self.cached_tokens += int(details.get("cached_tokens") or 0)


# ----- events ------------------------------------------------------------------------

EVENT_KINDS = ("thinking", "tool_call", "tool_result", "assistant", "error", "usage",
               "approval_denied", "cancelled")


@dataclass
class AgentEvent:
    kind: str
    op: str = ""
    args: dict = None
    result: dict = None
    text: str = ""
    usage: Usage = None
    call_id: str = ""

    def to_dict(self) -> dict:
        """Plain dict for a Qt signal / a test assertion."""
        return {
            "kind": self.kind, "op": self.op, "args": self.args, "result": self.result,
            "text": self.text, "call_id": self.call_id,
            "usage": None if self.usage is None else {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "cached_tokens": self.usage.cached_tokens,
                "requests": self.usage.requests,
            },
        }


# ----- system prompt ------------------------------------------------------------------

def default_tools() -> list:
    """The bridge op schemas the model may call (see EXCLUDED_TOOLS)."""
    return [t for t in tool_schemas() if t["function"]["name"] not in EXCLUDED_TOOLS]


def build_system_prompt(project_summary: dict, guide_text: str) -> str:
    """``project_summary`` is the ``hello`` result (or just its ``project`` dict)."""
    summary = project_summary or {}
    if isinstance(summary.get("project"), dict):
        summary = summary["project"]
    counts = ", ".join(f"{summary.get(k, 0)} {k}" for k in ("focuses", "ideas", "events"))
    project_line = (f"Open project: {summary.get('name') or '(unnamed)'} "
                    f"(country tag {summary.get('tag') or '?'}, tree id "
                    f"{summary.get('treeId') or '?'}) — {counts}.")
    return "\n\n".join([
        "You are the Focus Forge assistant. You edit the user's Hearts of Iron IV "
        "Millennium Dawn focus tree by calling tools. The tools are the Focus Forge "
        "bridge ops. Prefer one `batch` per feature. Follow the guide below exactly.",
        project_line + " The canvas updates live as you call tools; the user watches.",
        guide_text or "",
        "Respond to the user in their language, briefly. When you finish, summarise what "
        "you built and where (grid cells). Never claim success for a call that returned "
        "ok=false.",
        "`screenshot` renders a PNG for the USER to see (you cannot view images); call it "
        "after a batch so they can check the layout.",
    ])


# ----- the loop -----------------------------------------------------------------------

def _call_op(call) -> str:
    fn = call.get("function") if isinstance(call, dict) else None
    return str(fn.get("name") or "") if isinstance(fn, dict) else ""


def compact_tool_result(op: str, result) -> object:
    """What goes back into the history for a successful ``batch``: the ids it
    produced, the issue list and the summary — not every per-op result echoed
    back. The model already knows what it sent; re-reading 20 focus summaries
    every round for the rest of the session is where input tokens go."""
    if op != "batch" or not isinstance(result, dict) or not result.get("ok"):
        return result
    inner = result.get("result")
    if not isinstance(inner, dict) or not isinstance(inner.get("results"), list):
        return result
    ids = []
    for r in inner["results"]:
        if isinstance(r, dict):
            v = r.get("id") or r.get("deleted") or r.get("message")
            if v:
                ids.append(v)
    compact = {"count": inner.get("count", len(inner["results"])), "ids": ids}
    for key in ("summary", "issues"):
        if key in inner:
            compact[key] = inner[key]
    return {"ok": True, "result": compact}


def _message_chars(message: dict) -> int:
    try:
        return len(json.dumps(message, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(message))


def needs_approval(op: str, args: dict) -> bool:
    """Destructive ops are gated; a batch is gated once if ANY entry is."""
    if op in DESTRUCTIVE_OPS:
        return True
    if op == "batch" and isinstance(args, dict):
        ops = args.get("ops")
        if isinstance(ops, list):
            return any(isinstance(e, dict) and e.get("op") in DESTRUCTIVE_OPS for e in ops)
    return False


class AgentSession:
    """One conversation: history + usage across turns. ``run_turn`` is
    synchronous and blocking — the UI runs it on a worker thread."""

    def __init__(self, config: AgentConfig, transport: Transport, executor: ToolExecutor,
                 gate: ApprovalGate, tools: "list | None" = None,
                 system_prompt: "str | None" = None,
                 on_event: "Callable[[AgentEvent], None] | None" = None) -> None:
        self.config = config
        self.transport = transport
        self.executor = executor
        self.gate = gate
        self.tools = default_tools() if tools is None else list(tools)
        self.system_prompt = system_prompt
        self.on_event = on_event
        self.messages: list = []
        self.usage = Usage()
        self._call_counter = 0
        self.reset()

    # ----- public -----
    def reset(self) -> None:
        self.messages = []
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})
        self.usage = Usage()

    def tool_names(self) -> list:
        return [t.get("function", {}).get("name", "") for t in self.tools]

    def run_turn(self, user_text: str, cancel: Callable[[], bool] = lambda: False) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for _round in range(self.config.max_rounds):
            if cancel():
                return self._stop()
            self._emit(AgentEvent("thinking"))
            try:
                response = self.transport.chat(self._payload(), self.config)
            except TransportError as exc:
                self._emit(AgentEvent("error", text=exc.message))
                return exc.message
            except Exception as exc:  # a transport bug must surface, not kill the thread
                text = f"Couldn't talk to the provider ({type(exc).__name__}: {exc})."
                self._emit(AgentEvent("error", text=text))
                return text

            self.usage.add(response.get("usage") if isinstance(response, dict) else None)
            self._emit(AgentEvent("usage", usage=self.usage))
            choices = response.get("choices") if isinstance(response, dict) else None
            choice = choices[0] if isinstance(choices, list) and choices else {}
            message = choice.get("message") if isinstance(choice, dict) else None
            if not isinstance(message, dict):
                text = "The provider sent an empty reply."
                self._emit(AgentEvent("error", text=text))
                return text
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                # Verbatim: the provider needs its own tool_calls echoed back.
                self.messages.append(dict(message))
                cancelled = False
                for call in tool_calls:
                    call_id = self._call_id(call)
                    if not cancelled and cancel():
                        cancelled = True
                    if cancelled:
                        result = dict(CANCELLED_TOOL)
                    else:
                        result = self._run_tool(call_id, call)
                    self._append_tool_result(call_id, result, _call_op(call))
                self._enforce_budget()
                if cancelled:
                    return self._stop()
                continue

            content = message.get("content") or ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            self.messages.append({"role": "assistant", "content": content})
            if choice.get("finish_reason") == "length":
                self._emit(AgentEvent("error", text=CUT_OFF_TEXT))
            text = content or NO_REPLY_TEXT
            self._emit(AgentEvent("assistant", text=text))
            return text

        text = f"Stopped after {self.config.max_rounds} tool rounds. Say 'continue' to keep going."
        self._emit(AgentEvent("error", text=text))
        return text

    # ----- internals -----
    def _emit(self, event: AgentEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _payload(self) -> dict:
        payload = {"model": self.config.model, "messages": self.messages,
                   "temperature": self.config.temperature}
        if self.tools:
            payload["tools"] = self.tools
            payload["tool_choice"] = "auto"
        return payload

    def _call_id(self, call) -> str:
        cid = call.get("id") if isinstance(call, dict) else None
        if not cid:
            self._call_counter += 1
            cid = f"call_{self._call_counter}"
        return str(cid)

    def _stop(self) -> str:
        """Cancel: keep the history valid (an assistant tool_calls message must be
        followed by tool messages — already guaranteed) and mark the stop."""
        self._emit(AgentEvent("cancelled", text=STOPPED_TEXT))
        if self.messages and self.messages[-1].get("role") == "tool":
            self.messages.append({"role": "assistant", "content": STOPPED_TEXT})
        return STOPPED_TEXT

    def _run_tool(self, call_id: str, call: dict) -> dict:
        fn = call.get("function") if isinstance(call, dict) else None
        fn = fn if isinstance(fn, dict) else {}
        op = str(fn.get("name") or "")
        raw = fn.get("arguments")
        args, err = self._parse_args(raw)
        if err:
            result = {"ok": False, "error": f"arguments were not valid JSON: {err}. "
                                            "Send a JSON object matching the tool schema."}
            self._emit(AgentEvent("tool_call", op=op, args={"_raw": raw}, call_id=call_id))
            self._emit(AgentEvent("tool_result", op=op, args={"_raw": raw}, result=result,
                                  call_id=call_id))
            return result
        self._emit(AgentEvent("tool_call", op=op, args=args, call_id=call_id))
        names = self.tool_names()
        if op not in names:
            result = {"ok": False, "error": f"Unknown tool '{op}'. Available: {', '.join(names)}"}
        elif needs_approval(op, args) and not self._approved(op, args):
            result = {"ok": False, "error": DECLINED_TEXT}
            self._emit(AgentEvent("approval_denied", op=op, args=args, call_id=call_id))
        else:
            try:
                result = self.executor.execute(op, args)
            except Exception as exc:  # the executor promised not to raise; be safe
                result = {"ok": False, "error": f"Tool failed: {exc}"}
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
        self._emit(AgentEvent("tool_result", op=op, args=args, result=result, call_id=call_id))
        return result

    def _approved(self, op: str, args: dict) -> bool:
        try:
            return bool(self.gate.approve(op, args))
        except Exception:
            return False

    @staticmethod
    def _parse_args(raw):
        """``function.arguments`` is a JSON string per the spec, but some
        providers hand back a parsed object; accept both."""
        if raw is None or raw == "":
            return {}, None
        if isinstance(raw, dict):
            return raw, None
        if not isinstance(raw, str):
            return None, f"expected an object, got {type(raw).__name__}"
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            return None, str(exc)
        if not isinstance(parsed, dict):
            return None, f"expected an object, got {type(parsed).__name__}"
        return parsed, None

    def _append_tool_result(self, call_id: str, result: dict, op: str = "") -> None:
        text = json.dumps(compact_tool_result(op, result), ensure_ascii=False, default=str)
        limit = self.config.max_tool_result_chars
        if len(text) > limit:
            total = len(text)
            text = (text[:max(0, limit - 300)]
                    + f"…[truncated: {total} chars total — use list_focuses prefix/ids/fields "
                      "or reference_data sections to fetch less]")
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": text})

    def _enforce_budget(self) -> None:
        """Elide the oldest tool results (never the system prompt, never the
        newest KEEP_RECENT messages) until the history fits the budget."""
        budget = self.config.context_budget_chars
        total = sum(_message_chars(m) for m in self.messages)
        while total > budget:
            cutoff = len(self.messages) - KEEP_RECENT
            victim = None
            for i in range(cutoff):
                m = self.messages[i]
                if m.get("role") == "tool" and m.get("content") != ELIDED_TEXT:
                    victim = m
                    break
            if victim is None:
                return
            total -= _message_chars(victim)
            victim["content"] = ELIDED_TEXT
            total += _message_chars(victim)
