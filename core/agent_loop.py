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
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge_specs import tool_schemas
from .hosted import (
    HOSTED_ERROR_CODES,
    HOSTED_MODEL_ID,
    format_dollars,
    hosted_chat_base,
    hosted_me_url,
    parse_quota_headers,
)

# Ops that destroy work or touch disk: the user is asked before each one.
# `load_project` is listed for completeness even though the default tool set
# excludes it (a caller passing its own tool list still gets the gate).
DESTRUCTIVE_OPS = frozenset({
    "save", "export", "load_project", "delete_focus", "delete_focuses",
    "delete_idea", "delete_event", "delete_decision", "delete_decision_category",
})

# Not offered to the model: hello/guide are baked into the system prompt,
# describe_op is redundant with the tool schemas, and the user opens files.
# hello stays available: the guide (shared with MCP clients) tells the model to
# call it, and a model that cannot will invent a name for it.
EXCLUDED_TOOLS = ("guide", "load_project")

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

MODE_OWN = "own"
MODE_HOSTED = "hosted"


@dataclass
class AgentConfig:
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    model: str = "meta/muse-spark-1.3-contributor"
    # "own": the fields above are the provider. "hosted": the Focus Forge relay
    # is the provider and ``hosted_token`` (an ``ffa_…`` token from Discord
    # sign-in) is the credential. Both panes' values are kept so switching
    # never erases the other one; ``effective_*`` resolve whichever is active.
    mode: str = MODE_OWN
    hosted_token: str = ""
    max_rounds: int = 80          # tool rounds per user turn (a 20-focus build with
                                  # per-focus verification calls needs ~60)
    temperature: float = 0.3
    timeout_s: int = 120
    # Every round resends the whole history, so these two numbers ARE the
    # input-token bill: a 15-focus build at the old 400k budget cost ~1M input
    # tokens. ~35k tokens per request keeps quality (the model rarely needs a
    # focus list it read twenty calls ago) at roughly a third of the cost.
    max_tool_result_chars: int = 8_000    # longer tool results are truncated with a note
    context_budget_chars: int = 140_000   # when exceeded, elide the oldest tool results
    # Provider prompt caching: a stable session_id pins follow-up requests to
    # the provider holding the warm cache, and the top-level cache_control
    # marker asks OpenRouter to cache up to the last cacheable block. Cache
    # reads on Muse Spark contributor cost 1/50th of fresh input.
    prompt_caching: bool = True
    extra_headers: dict = field(default_factory=dict)  # OpenRouter likes HTTP-Referer / X-Title

    def is_hosted(self) -> bool:
        return self.mode == MODE_HOSTED

    def effective_base_url(self) -> str:
        return hosted_chat_base() if self.is_hosted() else self.base_url

    def effective_api_key(self) -> str:
        return self.hosted_token if self.is_hosted() else self.api_key

    def effective_model(self) -> str:
        return HOSTED_MODEL_ID if self.is_hosted() else self.model


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

    def hosted_me(self, config: AgentConfig) -> dict:
        """``GET /v1/me`` on the hosted relay (the settings dialog's probe).
        A transport without a hosted endpoint raises :class:`TransportError`."""
        ...


SERVICE_UNAVAILABLE_TEXT = ("The assistant service is unavailable right now — try again "
                            "in a minute")


def friendly_http_error(status: int, body: str = "") -> str:
    """Map an HTTP failure to a sentence a modder can act on, keeping the
    provider's own message (``{"error": {"message": ...}}``) when it has one.

    The hosted relay's messages are already written for the user (they name
    the reset date, say "try again tomorrow", suggest switching to your own
    key) and are recognisable by their ``error.code``, so those are shown
    verbatim; a raw provider message still gets the generic prefix."""
    detail = provider_error_message(body)
    if detail and relay_error_code(body) in HOSTED_ERROR_CODES:
        return detail
    if status == 401:
        text = "API key rejected"
    elif status == 402:
        text = "Out of credits"
    elif status == 429:
        text = "Rate limited — wait a moment"
    elif status == 503:
        text = SERVICE_UNAVAILABLE_TEXT
    elif status >= 500:
        text = "Provider error"
    else:
        text = f"Request failed (HTTP {status})"
    return f"{text}: {detail}" if detail else text


def _error_envelope(body: str):
    try:
        data = json.loads(body or "")
    except ValueError:
        return None
    return data.get("error") if isinstance(data, dict) else None


def provider_error_message(body: str) -> str:
    err = _error_envelope(body)
    if isinstance(err, dict):
        return str(err.get("message") or "").strip()
    if isinstance(err, str):
        return err.strip()
    return ""


def relay_error_code(body: str) -> str:
    """``error.code`` from an OpenAI-style envelope ('' when absent)."""
    err = _error_envelope(body)
    return str(err.get("code") or "").strip() if isinstance(err, dict) else ""


BAD_TOKEN_TEXT = "That token isn't valid — sign in with Discord again to get a new one."
NO_TOKEN_TEXT = "No token entered — sign in with Discord to get one."
HOSTED_TOKEN_PREFIX = "ffa_"
BAD_TOKEN_SHAPE_TEXT = ("That doesn't look like a Focus Forge token — it starts with ffa_. "
                        "Copy the whole token from the sign-in page.")


def looks_like_hosted_token(token) -> bool:
    """A relay token is ``ffa_…`` and nothing else: a pasted ``Token: ffa_…``
    line or a stray key from another provider is rejected before any request
    goes out, so the user gets a sentence about the paste rather than a 401."""
    return str(token or "").strip().startswith(HOSTED_TOKEN_PREFIX)


def _lower_headers(message) -> dict:
    """Response headers as a plain lower-cased dict (``None``-safe: the fakes
    in tests and some error paths have none)."""
    try:
        return {str(k).lower(): str(v) for k, v in message.items()}
    except AttributeError:
        return {}


class UrllibTransport:
    """The real transport. ``urllib`` rather than QtNetwork because TLS via
    urllib is what already works inside the PyInstaller build
    (``core.update_check``); QtNetwork's TLS backend does not ship.

    ``last_headers`` holds the most recent response's headers (lower-cased
    keys) — the hosted relay reports the remaining allotment there, and the
    session turns it into a ``quota`` event."""

    def __init__(self) -> None:
        self.last_headers: dict = {}

    def chat(self, payload: dict, config: AgentConfig) -> dict:
        url = config.effective_base_url().rstrip("/") + "/chat/completions"
        headers = self._headers(config)
        headers["Content-Type"] = "application/json"
        headers.update(config.extra_headers or {})
        body = json.dumps(payload).encode("utf-8")
        raw = self._send(Request(url, data=body, headers=headers, method="POST"), config)
        data = self._parse(raw)
        if "error" in data and not data.get("choices"):
            # Some providers answer 200 with an error envelope.
            raise TransportError(0, provider_error_message(raw) or "Provider error")
        return data

    def hosted_me(self, config: AgentConfig) -> dict:
        """``GET /v1/me`` on the relay: who the token belongs to and what is
        left of the allotment. A 401 here means the token, not a key."""
        request = Request(hosted_me_url(), headers=self._headers(config), method="GET")
        try:
            return self._parse(self._send(request, config))
        except TransportError as exc:
            if exc.status == 401:
                raise TransportError(401, BAD_TOKEN_TEXT) from exc
            raise

    def _headers(self, config: AgentConfig) -> dict:
        return {
            "Authorization": f"Bearer {config.effective_api_key()}",
            "Accept": "application/json",
            "User-Agent": "FocusForge-Assistant",
        }

    def _send(self, request: Request, config: AgentConfig) -> str:
        # Cleared first so a network failure never re-emits the previous
        # response's allotment headers as if they were this request's.
        self.last_headers = {}
        try:
            with urlopen(request, timeout=config.timeout_s) as resp:
                self.last_headers = _lower_headers(getattr(resp, "headers", None))
                return resp.read().decode("utf-8", "replace")
        except HTTPError as exc:
            self.last_headers = _lower_headers(getattr(exc, "headers", None))
            try:
                err_body = exc.read().decode("utf-8", "replace")
            except Exception:
                err_body = ""
            raise TransportError(exc.code, friendly_http_error(exc.code, err_body)) from exc
        except (URLError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", None) or exc
            who = "the assistant service" if config.is_hosted() else "the provider"
            raise TransportError(0, f"Couldn't reach {who} ({reason}).") from exc

    @staticmethod
    def _parse(raw: str) -> dict:
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise TransportError(0, "The provider returned something that wasn't JSON.") from exc
        if not isinstance(data, dict):
            raise TransportError(0, "The provider returned an unexpected response shape.")
        return data


def test_connection(config: AgentConfig, transport: Transport) -> str:
    """The settings dialog's 'Test connection'. Own key: one tiny chat request.
    Hosted: ``/v1/me``, which costs nothing and also tells the user who they
    are signed in as. Returns a success sentence; raises
    :class:`TransportError` on failure."""
    if config.is_hosted():
        return _test_hosted(config, transport)
    if not config.api_key:
        raise TransportError(0, "No API key entered.")
    payload = {"model": config.model,
               "messages": [{"role": "user", "content": "Reply with OK."}],
               "max_tokens": 1}
    data = transport.chat(payload, config)
    model = data.get("model") or config.model
    return f"Connected — {model} replied."


def _test_hosted(config: AgentConfig, transport) -> str:
    if not str(config.hosted_token or "").strip():
        raise TransportError(0, NO_TOKEN_TEXT)
    if not looks_like_hosted_token(config.hosted_token):
        raise TransportError(0, BAD_TOKEN_SHAPE_TEXT)
    me = transport.hosted_me(config)
    name = me.get("discord_username") or "?"
    return (f"Signed in as {name} · {format_dollars(me.get('used_cents'))} of "
            f"{format_dollars(me.get('limit_cents'))} used this month")


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
    cache_write_tokens: int = 0

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
            self.cache_write_tokens += int(details.get("cache_write_tokens") or 0)


# ----- events ------------------------------------------------------------------------

EVENT_KINDS = ("thinking", "tool_call", "tool_result", "assistant", "error", "usage",
               "approval_denied", "cancelled", "quota")


@dataclass
class AgentEvent:
    kind: str
    op: str = ""
    args: dict = None
    result: dict = None
    text: str = ""
    usage: Usage = None
    call_id: str = ""
    quota: dict = None      # "quota": {used_cents, limit_cents, reset} from the relay
    status: int = 0         # "error": the HTTP status behind it (0 = not HTTP)

    def to_dict(self) -> dict:
        """Plain dict for a Qt signal / a test assertion."""
        return {
            "kind": self.kind, "op": self.op, "args": self.args, "result": self.result,
            "text": self.text, "call_id": self.call_id, "quota": self.quota,
            "status": self.status,
            "usage": None if self.usage is None else {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "cached_tokens": self.usage.cached_tokens,
                "requests": self.usage.requests,
                "cache_write_tokens": self.usage.cache_write_tokens,
            },
        }


# ----- system prompt ------------------------------------------------------------------

def default_tools() -> list:
    """The bridge op schemas the model may call (see EXCLUDED_TOOLS)."""
    return [t for t in tool_schemas() if t["function"]["name"] not in EXCLUDED_TOOLS]


CAPABILITIES_TEXT = (
    "What you can do for the user (say it in these words when asked, never as tool "
    "names): design and build whole focus branches; edit, re-link or re-lay-out existing "
    "focuses; write national spirits, events and decisions and wire them into "
    "focus rewards; check the tree for errors and the exported files for load "
    "problems; read the game's error.log after a launch and map "
    "errors back to focuses; take a screenshot of the canvas for the user; review the "
    "tree and recommend what to build next; explain any Millennium Dawn focus, reward "
    "or condition. When asked what you can do, answer in those terms and offer two or "
    "three concrete starting prompts for THIS project — call tree_overview first so each "
    "one names a real gap or an existing focus to build from, never something the tree "
    "already has.\n"
    "What you will not do: open, save or export the project or delete anything unless "
    "the user explicitly asks in this conversation; view images (screenshots are for "
    "the user); change app settings or the user's game files; launch the game. If you "
    "cannot do something, say so plainly and suggest the nearest thing you can do."
)


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
        CAPABILITIES_TEXT,
        "Procedure step 1 is already done: this message IS the guide and the project "
        "summary. Do not call `guide`; `hello` only if you need fresh counts.",
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


ELIDED_ARGS = '{"_elided": "see the tool result"}'


def _elidable(message: dict) -> bool:
    """Old tool results AND the assistant's own old tool-call arguments. In a
    real session the arguments (whole batches of focuses as JSON) are the bulk
    of the history — measured at ~80% — and the compacted tool result already
    records what they produced, so keeping them verbatim buys nothing."""
    role = message.get("role")
    if role == "tool":
        return message.get("content") != ELIDED_TEXT
    if role == "assistant":
        for call in message.get("tool_calls") or []:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(fn, dict) and fn.get("arguments") not in (None, ELIDED_ARGS):
                return True
    return False


def _elide(message: dict) -> None:
    if message.get("role") == "tool":
        message["content"] = ELIDED_TEXT
        return
    for call in message.get("tool_calls") or []:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and "arguments" in fn:
            fn["arguments"] = ELIDED_ARGS


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
        self.session_id = ""
        self._call_counter = 0
        self._dropped_keys_seen: set = set()
        self.reset()

    # ----- public -----
    def reset(self) -> None:
        self.messages = []
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})
        self.usage = Usage()
        # One id per conversation: the provider cache is keyed on the prefix,
        # and sticky routing is keyed on this.
        self.session_id = "ff-" + uuid.uuid4().hex

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
                self._emit_quota()
                self._emit(AgentEvent("error", text=exc.message, status=exc.status))
                return exc.message
            except Exception as exc:  # a transport bug must surface, not kill the thread
                text = f"Couldn't talk to the provider ({type(exc).__name__}: {exc})."
                self._emit(AgentEvent("error", text=text))
                return text

            self.usage.add(response.get("usage") if isinstance(response, dict) else None)
            self._log_request(_round, response)
            self._emit(AgentEvent("usage", usage=self.usage))
            self._emit_quota()
            choices = response.get("choices") if isinstance(response, dict) else None
            choice = choices[0] if isinstance(choices, list) and choices else {}
            message = choice.get("message") if isinstance(choice, dict) else None
            if not isinstance(message, dict):
                text = "The provider sent an empty reply."
                self._emit(AgentEvent("error", text=text))
                return text
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                # The provider needs its own tool_calls echoed back — but only
                # role/content/tool_calls. Anything else it attaches (reasoning
                # blocks, annotations) is never elided and would be resent for
                # the rest of the session.
                self.messages.append(self._history_message(message))
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

    def _emit_quota(self) -> None:
        """The relay's allotment headers ride on every response, including a
        402 (so the panel can show "$0.50 of $0.50" next to the refusal).
        Own-key providers don't send them, so this is usually a no-op."""
        quota = parse_quota_headers(getattr(self.transport, "last_headers", None))
        if quota is not None:
            self._emit(AgentEvent("quota", quota=quota))

    _HISTORY_KEYS = ("role", "content", "tool_calls")

    def _history_message(self, message: dict) -> dict:
        kept = {k: message[k] for k in self._HISTORY_KEYS if k in message}
        kept.setdefault("role", "assistant")
        dropped = {k: len(json.dumps(message[k], default=str)) for k in message if k not in kept}
        if dropped and dropped.keys() != self._dropped_keys_seen:
            self._dropped_keys_seen = set(dropped)
            try:
                from .applog import logger
                logger().info("assistant reply carried extra fields (dropped from history): %s", dropped)
            except Exception:
                pass
        return kept

    def _log_request(self, round_index: int, response) -> None:
        """One INFO line per provider request in the app log, so a session's
        token bill can be reconstructed afterwards: which round, how big the
        history was, what the provider counted, and how much of it was cached."""
        try:
            from .applog import logger
            u = response.get("usage") if isinstance(response, dict) else None
            u = u if isinstance(u, dict) else {}
            details = u.get("prompt_tokens_details") or {}
            tool_calls = 0
            try:
                tool_calls = len(response["choices"][0]["message"].get("tool_calls") or [])
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
            logger().info(
                "assistant request round=%d msgs=%d history_chars=%d prompt=%s cached=%s "
                "cache_write=%s completion=%s tool_calls=%d session=%s",
                round_index + 1, len(self.messages),
                sum(_message_chars(m) for m in self.messages),
                u.get("prompt_tokens"), details.get("cached_tokens"),
                details.get("cache_write_tokens"), u.get("completion_tokens"),
                tool_calls, self.session_id[-8:])
        except Exception:  # logging must never break a turn
            pass

    def _payload(self) -> dict:
        payload = {"model": self.config.effective_model(), "messages": self.messages,
                   "temperature": self.config.temperature}
        if self.tools:
            payload["tools"] = self.tools
            payload["tool_choice"] = "auto"
        if self.config.prompt_caching:
            payload["session_id"] = self.session_id
            payload["cache_control"] = {"type": "ephemeral"}
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
        if op not in names and "." in op and op.rsplit(".", 1)[-1] in names:
            op = op.rsplit(".", 1)[-1]        # "default.hello" -> "hello" (namespaced by the model)
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
        newest KEEP_RECENT messages) once the history exceeds the budget.

        Hysteresis on purpose: rewriting an old message changes the request
        prefix, which throws away the provider's prompt cache for everything
        after it. Eliding one message per round would do that every round for
        the rest of the session; eliding down to half the budget in one pass
        breaks the cache rarely, and the rounds in between are cache reads."""
        budget = self.config.context_budget_chars
        total = sum(_message_chars(m) for m in self.messages)
        if total <= budget:
            return
        target = budget // 2
        while total > target:
            cutoff = len(self.messages) - KEEP_RECENT
            victim = None
            for i in range(cutoff):
                m = self.messages[i]
                if _elidable(m):
                    victim = m
                    break
            if victim is None:
                self._log_residue(total, target)
                return
            total -= _message_chars(victim)
            _elide(victim)
            total += _message_chars(victim)

    def _log_residue(self, total: int, target: int) -> None:
        """Nothing left to elide but still over target: say what the history is
        made of, by role, so the next design change is aimed at the right thing."""
        try:
            from .applog import logger
            by_role: dict = {}
            for m in self.messages:
                by_role[m.get("role")] = by_role.get(m.get("role"), 0) + _message_chars(m)
            logger().warning("assistant history %d chars > target %d with nothing elidable; by role: %s",
                             total, target, by_role)
        except Exception:
            pass
