"""Assistant tab: chat with a hosted model that edits the open project through the bridge ops.

Thin shell over ``core.agent_loop.AgentSession``. The session's blocking
``run_turn`` runs on a worker QThread (``run_in_thread``); everything that
touches the project or a widget happens on the GUI thread:

* the worker-side ``ToolExecutor`` / ``ApprovalGate`` emit ``tool_requested`` /
  ``approval_requested`` on a relay QObject that lives on the GUI thread (so the
  connection is queued) and then block on a ``queue.Queue`` for the answer;
* the panel's slots run the op via ``AgentBridge.run_op`` (or show the approval
  dialog) and put the answer in that queue;
* loop events arrive through the relay's ``event(dict)`` signal and are rendered
  as transcript cards; the Stop button sets a ``threading.Event`` the loop polls.

The model mutates the project on the GUI thread, so the canvas repaints via the
normal ``project_changed`` path with zero cross-thread widget access.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import uuid

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.agent_loop import CANCELLED_TOOL, AgentConfig, AgentSession, UrllibTransport
from core.agent_pricing import format_usage
from core.bridge_dispatch import dispatch
from core.md_focus_guide import MD_FOCUS_GUIDE

from . import theme as T
from .assistant_settings_dialog import AssistantSettingsDialog, load_config
from .update_worker import run_in_thread
from .widgets import ClickableFrame, hint, issue_card, mono_font, panel_header

# How long a blocked worker waits between checks that the panel is still alive.
_WAIT_TICK_S = 0.5
_ARGS_PREVIEW_CHARS = 400


# ----- cross-thread plumbing -------------------------------------------------------

class _GuiRelay(QObject):
    """Lives on the GUI thread. The worker thread emits these signals (Qt
    queues them because the receiver is here) and then waits on the matching
    queue; the panel's slots answer. ``abort`` unblocks a waiter whose GUI has
    gone away so a QThread can never hang the process at exit."""

    event = Signal(object)                        # AgentEvent.to_dict()
    tool_requested = Signal(str, str, object)     # call_id, op, args
    approval_requested = Signal(str, str, object)  # call_id, op, args

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tool_q: queue.Queue = queue.Queue()
        self._approval_q: queue.Queue = queue.Queue()
        self.abort = threading.Event()

    # GUI side
    def deliver_tool_result(self, call_id: str, result: dict) -> None:
        self._tool_q.put((call_id, result))

    def deliver_approval(self, call_id: str, ok: bool) -> None:
        self._approval_q.put((call_id, bool(ok)))

    # worker side
    def wait_tool(self, call_id: str) -> dict:
        return self._wait(self._tool_q, call_id, dict(CANCELLED_TOOL))

    def wait_approval(self, call_id: str) -> bool:
        return self._wait(self._approval_q, call_id, False)

    def _wait(self, q: queue.Queue, call_id: str, fallback):
        while True:
            try:
                got_id, value = q.get(timeout=_WAIT_TICK_S)
            except queue.Empty:
                if self.abort.is_set():
                    return fallback
                continue
            if got_id == call_id:
                return value
            # A stale answer from an earlier, abandoned request — ignore it.


class _QueuedExecutor:
    def __init__(self, relay: _GuiRelay) -> None:
        self._relay = relay

    def execute(self, op: str, args: dict) -> dict:
        call_id = uuid.uuid4().hex
        self._relay.tool_requested.emit(call_id, op, args)
        return self._relay.wait_tool(call_id)


class _QueuedGate:
    def __init__(self, relay: _GuiRelay) -> None:
        self._relay = relay

    def approve(self, op: str, args: dict) -> bool:
        call_id = uuid.uuid4().hex
        self._relay.approval_requested.emit(call_id, op, args)
        return self._relay.wait_approval(call_id)


class _TurnWorker(QObject):
    """Runs one ``run_turn`` off the GUI thread; ``finished`` always fires."""

    finished = Signal()

    def __init__(self, session: AgentSession, text: str, cancel: threading.Event,
                 relay: _GuiRelay) -> None:
        super().__init__()
        self._session = session
        self._text = text
        self._cancel = cancel
        self._relay = relay

    @Slot()
    def run(self) -> None:
        try:
            self._session.run_turn(self._text, cancel=self._cancel.is_set)
        except Exception as exc:  # the loop catches its own errors; this is the last net
            self._relay.event.emit({"kind": "error", "op": "", "args": None, "result": None,
                                    "text": f"The assistant crashed: {type(exc).__name__}: {exc}",
                                    "usage": None, "call_id": ""})
        finally:
            self.finished.emit()


# ----- transcript cards -----------------------------------------------------------------

def _subject(op: str, args) -> str:
    """The one-line hint after the op name: `add_focus MEX_x`, `batch 12 ops`."""
    if not isinstance(args, dict):
        return ""
    if op == "batch" and isinstance(args.get("ops"), list):
        return f"{len(args['ops'])} ops"
    for key in ("id", "target", "a", "query", "new_id", "path", "prefix"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    for key in ("ids", "focus_ids"):
        val = args.get(key)
        if isinstance(val, list) and val:
            return f"{len(val)} ids"
    for key in ("idea", "event", "decision", "category"):
        val = args.get(key)
        if isinstance(val, dict) and val.get("id"):
            return str(val["id"])
    return ""


def _pretty(data) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(data)


class _ToolCard(QFrame):
    """Collapsed one-liner `▸ add_focus MEX_x  ✓`; click to expand args + result."""

    def __init__(self, op: str, args, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("helpCard")
        self._expanded = False
        self._op = op
        self._args = args

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_SM, T.SPACE_XS, T.SPACE_SM, T.SPACE_XS)
        v.setSpacing(T.SPACE_XS)

        head = ClickableFrame()
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T.SPACE_SM)
        self._chevron = QLabel("▸")
        self._chevron.setObjectName("helpChevron")
        self._chevron.setFixedWidth(14)
        self._title = QLabel(f"{op} {_subject(op, args)}".strip())
        self._title.setObjectName("helpTitle")
        self._title.setFont(mono_font(T.TEXT_BODY))
        self._status = QLabel("…")
        self._status.setObjectName("hint")
        row.addWidget(self._chevron)
        row.addWidget(self._title, 1)
        row.addWidget(self._status)
        v.addWidget(head)

        self._body = QLabel(f"args:\n{_pretty(args)}")
        self._body.setObjectName("helpBody")
        self._body.setFont(mono_font(T.TEXT_MICRO))
        self._body.setTextFormat(Qt.PlainText)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setVisible(False)
        v.addWidget(self._body)
        head.clicked.connect(self.toggle)

    def set_result(self, result) -> None:
        ok = isinstance(result, dict) and bool(result.get("ok"))
        self._status.setText("✓" if ok else "×")
        self._status.setObjectName("pillOk" if ok else "issueTextError")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        if not ok:
            self.setObjectName("issueCardError")
            self.style().unpolish(self)
            self.style().polish(self)
        self._body.setText(f"args:\n{_pretty(self._args)}\n\nresult:\n{_pretty(result)}")

    def set_status_text(self, text: str) -> None:
        self._status.setText(text)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._chevron.setText("▾" if self._expanded else "▸")


def _bubble(text: str, role: str) -> QFrame:
    """A chat message. Assistant text is markdown-lite; user text stays literal."""
    card = QFrame()
    card.setObjectName("helpCard" if role == "assistant" else "helpQuickStart")
    v = QVBoxLayout(card)
    v.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_SM)
    v.setSpacing(T.SPACE_XS)
    who = QLabel("Assistant" if role == "assistant" else "You")
    who.setObjectName("sectionHeader")
    v.addWidget(who)
    body = QLabel(text)
    body.setObjectName("helpBody")
    body.setWordWrap(True)
    body.setTextFormat(Qt.MarkdownText if role == "assistant" else Qt.PlainText)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    body.setOpenExternalLinks(True)
    v.addWidget(body)
    return card


class _InputEdit(QPlainTextEdit):
    """Multi-line prompt box; Ctrl+Enter submits (Enter alone inserts a newline
    so multi-paragraph requests are natural)."""

    submitted = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.ControlModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


# ----- the panel -------------------------------------------------------------------------

class AssistantPanel(QWidget):
    """``bridge`` must provide ``run_op(op, args) -> dict`` (``AgentBridge`` does;
    tests pass a stub). ``config_loader`` / ``transport_factory`` are injectable
    so the panel is testable without QSettings or a network."""

    def __init__(self, model, bridge, parent=None, config_loader=load_config,
                 transport_factory=UrllibTransport) -> None:
        super().__init__(parent)
        self._model = model
        self._bridge = bridge
        self._transport_factory = transport_factory
        self._config: AgentConfig = config_loader()
        self._session: "AgentSession | None" = None
        self._worker = None
        self._thread = None
        self._cancel: "threading.Event | None" = None
        self._running = False
        self._cards: dict = {}   # call_id -> _ToolCard awaiting its result

        self._relay = _GuiRelay(self)
        self._relay.event.connect(self.render_event)
        self._relay.tool_requested.connect(self._on_tool_requested)
        self._relay.approval_requested.connect(self._on_approval_requested)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._relay.abort.set)

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        # Header: title + model + usage + settings / new chat
        head = QHBoxLayout()
        head.setSpacing(T.SPACE_SM)
        head.addWidget(panel_header("Assistant"))
        head.addStretch(1)
        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setToolTip("Assistant settings (provider, key, model)")
        self._settings_btn.setFixedWidth(T.ICON_BUTTON)
        self._settings_btn.clicked.connect(self._open_settings)
        self._new_btn = QPushButton("New chat")
        self._new_btn.setToolTip("Forget this conversation and start fresh")
        self._new_btn.clicked.connect(self._new_chat)
        head.addWidget(self._settings_btn)
        head.addWidget(self._new_btn)
        v.addLayout(head)

        meta = QHBoxLayout()
        meta.setSpacing(T.SPACE_SM)
        self._model_label = QLabel("")
        self._model_label.setObjectName("metaChip")
        self._usage_label = QLabel("")
        self._usage_label.setObjectName("hint")
        meta.addWidget(self._model_label)
        meta.addWidget(self._usage_label, 1)
        v.addLayout(meta)

        # Transcript
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._transcript = QWidget()
        self._transcript_layout = QVBoxLayout(self._transcript)
        self._transcript_layout.setContentsMargins(0, 0, T.SPACE_XS, 0)
        self._transcript_layout.setSpacing(T.SPACE_SM)
        self._transcript_layout.addStretch(1)
        self._scroll.setWidget(self._transcript)
        self._scroll.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: self._scroll.verticalScrollBar().setValue(hi))
        v.addWidget(self._scroll, 1)

        self._activity = QLabel("")
        self._activity.setObjectName("hint")
        v.addWidget(self._activity)

        # Bottom: setup page vs compose page
        self._stack = QStackedWidget()
        setup_page = QWidget()
        sv = QVBoxLayout(setup_page)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(T.SPACE_SM)
        sv.addWidget(hint("Bring your own API key (OpenRouter by default) and the assistant "
                          "builds and edits this tree for you, live on the canvas."))
        self._setup_btn = QPushButton("Set up the assistant")
        self._setup_btn.setObjectName("primary")
        self._setup_btn.clicked.connect(self._open_settings)
        sv.addWidget(self._setup_btn)
        self._stack.addWidget(setup_page)

        compose = QWidget()
        cv = QVBoxLayout(compose)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(T.SPACE_SM)
        self._input = _InputEdit()
        self._input.setPlaceholderText("Ask for a branch, a fix, a review… (Ctrl+Enter to send)")
        self._input.setFixedHeight(T.TEXTAREA_MEDIUM)
        self._input.submitted.connect(self._send)
        cv.addWidget(self._input)
        row = QHBoxLayout()
        row.setSpacing(T.SPACE_SM)
        row.addStretch(1)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setObjectName("danger")
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.hide()
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._send)
        row.addWidget(self._stop_btn)
        row.addWidget(self._send_btn)
        cv.addLayout(row)
        self._stack.addWidget(compose)
        v.addWidget(self._stack)

        self._refresh_header()
        self._refresh_key_state()

    # ----- state -----
    def has_key(self) -> bool:
        return bool(self._config.api_key)

    def is_running(self) -> bool:
        return self._running

    def _refresh_key_state(self) -> None:
        self._stack.setCurrentIndex(1 if self.has_key() else 0)

    def _refresh_header(self) -> None:
        self._model_label.setText(self._config.model)
        usage = self._session.usage if self._session is not None else None
        self._usage_label.setText(format_usage(usage, self._config.model) if usage else "")

    def _set_running(self, running: bool) -> None:
        self._running = running
        self._input.setEnabled(not running)
        self._send_btn.setVisible(not running)
        self._stop_btn.setVisible(running)
        self._new_btn.setEnabled(not running)
        self._settings_btn.setEnabled(not running)
        self._activity.setText("Thinking…" if running else "")

    # ----- session -----
    def _ensure_session(self) -> AgentSession:
        if self._session is None:
            hello = dispatch(self._model, "hello", {})
            summary = hello.get("result", {}) if hello.get("ok") else {}
            self._session = AgentSession(
                self._config, self._transport_factory(),
                _QueuedExecutor(self._relay), _QueuedGate(self._relay),
                system_prompt=_system_prompt(summary),
                on_event=lambda ev: self._relay.event.emit(ev.to_dict()))
        else:
            self._session.config = self._config
        return self._session

    def _new_chat(self) -> None:
        if self._running:
            return
        self._session = None
        self._cards.clear()
        self._clear_transcript()
        self._refresh_header()

    def _clear_transcript(self) -> None:
        lay = self._transcript_layout
        while lay.count() > 1:  # keep the trailing stretch
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # ----- sending / stopping -----
    def _send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text or self._running or not self.has_key():
            return
        session = self._ensure_session()
        self._input.clear()
        self._add_card(_bubble(text, "user"))
        self._cancel = threading.Event()
        self._set_running(True)
        worker = _TurnWorker(session, text, self._cancel, self._relay)
        worker.finished.connect(self._turn_finished)
        self._worker = worker
        self._thread = run_in_thread(worker, parent=self)

    def _stop(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self._activity.setText("Stopping after the current step…")

    def _turn_finished(self) -> None:
        self._worker = None
        self._thread = None
        self._set_running(False)
        self._refresh_header()

    # ----- GUI-thread answers to the worker -----
    @Slot(str, str, object)
    def _on_tool_requested(self, call_id: str, op: str, args) -> None:
        try:
            result = self._bridge.run_op(op, dict(args or {}))
            if not isinstance(result, dict):
                result = {"ok": False, "error": "The op returned a non-dict result."}
        except Exception as exc:  # never leave the worker blocked
            result = {"ok": False, "error": f"Tool failed: {type(exc).__name__}: {exc}"}
        self._relay.deliver_tool_result(call_id, result)

    @Slot(str, str, object)
    def _on_approval_requested(self, call_id: str, op: str, args) -> None:
        preview = _pretty(args)
        if len(preview) > _ARGS_PREVIEW_CHARS:
            preview = preview[:_ARGS_PREVIEW_CHARS] + "…"
        answer = QMessageBox.question(
            self, "Allow this action?",
            f"The assistant wants to run `{op}` — this deletes work or writes to disk.\n\n"
            f"{preview}\n\nAllow it?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        self._relay.deliver_approval(call_id, answer == QMessageBox.Yes)

    # ----- rendering -----
    @Slot(object)
    def render_event(self, event) -> None:
        """Render one loop event (a dict from ``AgentEvent.to_dict``)."""
        if not isinstance(event, dict):
            return
        kind = event.get("kind")
        op = event.get("op") or ""
        if kind == "thinking":
            self._activity.setText("Thinking…")
        elif kind == "tool_call":
            card = _ToolCard(op, event.get("args"))
            self._cards[event.get("call_id") or id(card)] = card
            self._add_card(card)
            self._activity.setText(f"Running {op}…")
        elif kind == "tool_result":
            result = event.get("result")
            card = self._cards.pop(event.get("call_id"), None)
            if card is None:
                card = _ToolCard(op, event.get("args"))
                self._add_card(card)
            card.set_result(result)
            if op == "screenshot" and isinstance(result, dict) and result.get("ok"):
                self._add_screenshot((result.get("result") or {}).get("path"))
            self._activity.setText("Thinking…")
        elif kind == "assistant":
            self._add_card(_bubble(event.get("text") or "", "assistant"))
        elif kind == "error":
            self._add_card(issue_card("error", event.get("text") or "Unknown error"))
        elif kind == "approval_denied":
            self._add_card(issue_card("warning", f"You declined {op}."))
        elif kind == "cancelled":
            self._add_card(hint("Stopped."))
        elif kind == "usage":
            usage = event.get("usage")
            if isinstance(usage, dict):
                self._usage_label.setText(format_usage(_UsageView(usage), self._config.model))

    def _add_card(self, widget: QWidget) -> None:
        lay = self._transcript_layout
        lay.insertWidget(lay.count() - 1, widget)

    def _add_screenshot(self, path) -> None:
        """The PNG `screenshot` wrote — the user's view of the layout the model
        just built (the model itself can't see images)."""
        if not path or not os.path.isfile(str(path)):
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            return
        width = max(200, self._scroll.viewport().width() - T.SPACE_LG)
        if pix.width() > width:
            pix = pix.scaledToWidth(width, Qt.SmoothTransformation)
        lbl = QLabel()
        lbl.setPixmap(pix)
        lbl.setObjectName("iconPreview")
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._add_card(lbl)

    # ----- settings -----
    def _open_settings(self) -> None:
        if self._running:
            return
        dlg = AssistantSettingsDialog(self._config, parent=self,
                                      transport_factory=self._transport_factory)
        if dlg.exec():
            self._config = dlg.config()
            if self._session is not None:
                self._session.config = self._config
            self._refresh_header()
            self._refresh_key_state()


class _UsageView:
    """Duck-typed stand-in for ``Usage`` built from an event dict, for the label."""

    def __init__(self, data: dict) -> None:
        self.prompt_tokens = int(data.get("prompt_tokens") or 0)
        self.completion_tokens = int(data.get("completion_tokens") or 0)
        self.cached_tokens = int(data.get("cached_tokens") or 0)
        self.cache_write_tokens = int(data.get("cache_write_tokens") or 0)

    def cost_usd(self, price_in_per_m: float, price_out_per_m: float,
                 price_cached_per_m=None) -> float:
        cached = min(self.cached_tokens, self.prompt_tokens)
        fresh = self.prompt_tokens - cached
        cached_price = price_in_per_m if price_cached_per_m is None else price_cached_per_m
        return (fresh * price_in_per_m + cached * cached_price
                + self.completion_tokens * price_out_per_m) / 1_000_000


def _system_prompt(hello_result: dict) -> str:
    from core.agent_loop import build_system_prompt
    return build_system_prompt(hello_result, MD_FOCUS_GUIDE)
