"""Offscreen smoke tests for the Assistant tab and its settings dialog.

The brain is covered in tests/test_agent_loop.py; here we check the shell:
key-less setup state, event rendering, and — with a fake transport on a real
worker QThread — that tool calls and approvals are answered on the GUI thread
through the relay queues and the project actually changes.
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from core.agent_loop import AgentConfig
from core.bridge_dispatch import dispatch


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class StubBridge:
    """What AgentBridge.run_op does, minus the status-bar narration."""

    def __init__(self, model) -> None:
        self.model = model
        self.ops: list = []

    def run_op(self, op, args):
        self.ops.append(op)
        return dispatch(self.model, op, args)


class FakeTransport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)

    def chat(self, payload, config):
        return self.responses.pop(0)


def _reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 50}}


def _tool_reply(cid, name, args):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50}}


def _panel(qapp, key="k", responses=()):
    from ui.assistant_panel import AssistantPanel
    from ui.project_model import ProjectModel
    model = ProjectModel()
    bridge = StubBridge(model)
    responses = list(responses)
    panel = AssistantPanel(model, bridge,
                           config_loader=lambda: AgentConfig(api_key=key, model="test/model"),
                           transport_factory=lambda: FakeTransport(responses))
    return panel, model, bridge


def _pump_until_idle(qapp, panel, timeout=15.0):
    t0 = time.time()
    while panel.is_running() and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert not panel.is_running(), "turn did not finish in time"


def _card_count(panel):
    return panel._transcript_layout.count() - 1   # minus the trailing stretch


# ----- static state -----

def test_no_key_shows_setup_button(qapp):
    panel, *_ = _panel(qapp, key="")
    assert not panel.has_key()
    assert panel._stack.currentIndex() == 0
    assert panel._stack.currentWidget().findChild(type(panel._setup_btn)) is not None


def test_with_key_shows_input(qapp):
    panel, *_ = _panel(qapp, key="sk-or-x")
    assert panel.has_key()
    assert panel._stack.currentIndex() == 1
    assert panel._input.isEnabled()
    assert panel._model_label.text() == "test/model"


def test_render_events_makes_cards_without_raising(qapp):
    panel, *_ = _panel(qapp)
    base = _card_count(panel)
    panel.render_event({"kind": "thinking"})
    panel.render_event({"kind": "tool_call", "op": "add_focus", "args": {"id": "MEX_x"},
                        "call_id": "c1"})
    assert _card_count(panel) == base + 1
    card = panel._cards["c1"]
    assert card._title.text() == "add_focus MEX_x"
    panel.render_event({"kind": "tool_result", "op": "add_focus", "args": {"id": "MEX_x"},
                        "result": {"ok": True, "result": {"id": "MEX_x"}}, "call_id": "c1"})
    assert "c1" not in panel._cards and card._status.text() == "✓"
    card.toggle()
    assert card._body.isVisibleTo(panel) and "MEX_x" in card._body.text()
    panel.render_event({"kind": "tool_result", "op": "save", "args": {},
                        "result": {"ok": False, "error": "nope"}, "call_id": "zz"})
    panel.render_event({"kind": "assistant", "text": "**Done.** Built it at (0, 5)."})
    panel.render_event({"kind": "error", "text": "API key rejected"})
    panel.render_event({"kind": "approval_denied", "op": "delete_focus"})
    panel.render_event({"kind": "cancelled", "text": "(stopped by user)"})
    panel.render_event({"kind": "usage", "usage": {"prompt_tokens": 12_400,
                                                   "completion_tokens": 2_100}})
    assert _card_count(panel) == base + 6
    assert panel._usage_label.text() == "12.4k in · 2.1k out · ~$?"
    panel.render_event("not a dict")   # ignored


def test_new_chat_clears_transcript(qapp):
    panel, *_ = _panel(qapp)
    panel.render_event({"kind": "assistant", "text": "hi"})
    assert _card_count(panel) == 1
    panel._new_chat()
    qapp.processEvents()
    assert _card_count(panel) == 0 and panel._session is None


# ----- a real turn on a worker thread -----

def test_turn_runs_tool_on_gui_thread_and_edits_project(qapp):
    panel, model, bridge = _panel(qapp, responses=[
        _tool_reply("c1", "add_focus", {"id": "MEX_assist_a", "title": "A", "x": 0, "y": 30}),
        _reply("Added MEX_assist_a at (0, 30)."),
    ])
    panel._input.setPlainText("add a focus")
    panel._send()
    assert panel.is_running() and not panel._input.isEnabled()
    _pump_until_idle(qapp, panel)
    assert bridge.ops == ["add_focus"]
    assert model.find_focus("MEX_assist_a") is not None
    assert panel._input.isEnabled() and panel._stop_btn.isHidden()
    assert panel._usage_label.text().startswith("2.0k in")
    roles = [m["role"] for m in panel._session.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert "Focus Forge assistant" in panel._session.messages[0]["content"]


def test_gated_op_asks_on_gui_thread(qapp, monkeypatch):
    from ui import assistant_panel as ap
    asked = []

    def fake_question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.No

    monkeypatch.setattr(ap.QMessageBox, "question", staticmethod(fake_question))
    panel, model, bridge = _panel(qapp, responses=[
        _tool_reply("c1", "delete_focus", {"id": "MEX_forge_national_assessment"}),
        _reply("Understood, leaving it."),
    ])
    panel._input.setPlainText("delete the opener")
    panel._send()
    _pump_until_idle(qapp, panel)
    assert len(asked) == 1 and "delete_focus" in asked[0]
    assert bridge.ops == []                                    # declined → never ran
    assert model.find_focus("MEX_forge_national_assessment") is not None
    tool_msg = json.loads(panel._session.messages[3]["content"])
    assert "declined" in tool_msg["error"]


def test_stop_button_cancels_turn(qapp):
    panel, model, bridge = _panel(qapp, responses=[
        _tool_reply("c1", "list_focuses", {}),
        _tool_reply("c2", "list_focuses", {}),
        _reply("unreached"),
    ])
    original = bridge.run_op

    def run_op(op, args):
        panel._stop()            # user presses Stop while the first tool runs
        return original(op, args)

    bridge.run_op = run_op
    panel._input.setPlainText("list")
    panel._send()
    _pump_until_idle(qapp, panel)
    assert panel._session.messages[-1]["content"] == "(stopped by user)"
    assert len(bridge.ops) == 1


# ----- settings dialog -----

def test_settings_dialog_roundtrip_and_test_connection(qapp):
    from ui.assistant_settings_dialog import AssistantSettingsDialog
    cfg = AgentConfig(api_key="abc", model="meta/muse-spark-1.3", max_rounds=7,
                      temperature=0.5, base_url="https://openrouter.ai/api/v1")
    probe = [{"model": "meta/muse-spark-1.3", **_reply("OK")}]
    dlg = AssistantSettingsDialog(cfg, recent=["custom/model"],
                                  transport_factory=lambda: FakeTransport(probe))
    out = dlg.config()
    assert (out.api_key, out.model, out.max_rounds, out.temperature) == ("abc", "meta/muse-spark-1.3", 7, 0.5)
    assert out.extra_headers["X-Title"] == "Focus Forge"
    items = [dlg._model.itemText(i) for i in range(dlg._model.count())]
    assert "custom/model" in items and "meta/muse-spark-1.3-contributor" in items
    # show/hide toggle
    dlg._show_key.setChecked(True)
    from PySide6.QtWidgets import QLineEdit
    assert dlg._api_key.echoMode() == QLineEdit.EchoMode.Normal
    dlg._show_key.setChecked(False)
    assert dlg._api_key.echoMode() == QLineEdit.EchoMode.Password
    # Test connection on a worker thread with the fake transport
    dlg._test()
    thread = dlg._thread
    assert thread is not None
    thread.wait(5000)
    t0 = time.time()
    while dlg._worker is not None and time.time() - t0 < 5:
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg._test_status.text() == "Connected — meta/muse-spark-1.3 replied."
    assert dlg._test_btn.isEnabled()
