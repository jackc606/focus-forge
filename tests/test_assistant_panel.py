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
    assert dlg._thread is not None
    # No thread.wait() here: the worker's `finished` -> thread.quit is queued
    # to the GUI thread, so a blocking wait only ever times out; the
    # processEvents loop below is what lets the thread finish.
    t0 = time.time()
    while dlg._worker is not None and time.time() - t0 < 5:
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg._test_status.text() == "Connected — meta/muse-spark-1.3 replied."
    assert dlg._test_btn.isEnabled()


def test_settings_button_has_a_drawn_icon(qapp):
    panel = _panel(qapp)[0]
    assert not panel._settings_btn.icon().isNull()
    assert panel._settings_btn.text() == ""
    from ui.widgets import gear_icon
    pm = gear_icon("#ffffff", 16).pixmap(32, 32)
    img = pm.toImage()
    # something was actually painted (not a blank transparent square)
    assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, 32, 4) for y in range(0, 32, 4))


# ----- hosted mode (0.4.4): settings round-trip, dialog panes, panel header -----

def _ini(tmp_path):
    from PySide6.QtCore import QSettings
    return QSettings(str(tmp_path / "ff.ini"), QSettings.IniFormat)


def _panel_with(qapp, cfg, responses=()):
    from ui.assistant_panel import AssistantPanel
    from ui.project_model import ProjectModel
    model = ProjectModel()
    responses = list(responses)
    return AssistantPanel(model, StubBridge(model), config_loader=lambda: cfg,
                          transport_factory=lambda: FakeTransport(responses))


def test_config_roundtrips_mode_and_token_and_keeps_both_panes(qapp, tmp_path):
    from ui.assistant_settings_dialog import load_config, save_config
    cfg = AgentConfig(mode="hosted", hosted_token="ffa_tok", api_key="sk-own", model="own/m",
                      base_url="https://openrouter.ai/api/v1", max_rounds=9, temperature=0.7)
    save_config(cfg, _ini(tmp_path))
    back = load_config(_ini(tmp_path))
    assert (back.mode, back.hosted_token, back.api_key, back.model) == ("hosted", "ffa_tok", "sk-own", "own/m")
    assert (back.max_rounds, back.temperature) == (9, 0.7)
    assert back.extra_headers == {}                       # relay, not OpenRouter
    assert back.effective_api_key() == "ffa_tok"
    cfg.mode = "own"
    save_config(cfg, _ini(tmp_path))
    back = load_config(_ini(tmp_path))
    assert back.mode == "own" and back.hosted_token == "ffa_tok"   # switching kept the token
    assert back.extra_headers["X-Title"] == "Focus Forge"


def test_config_defaults_fresh_install_hosted_old_install_own(qapp, tmp_path):
    from ui.assistant_settings_dialog import load_config
    fresh = load_config(_ini(tmp_path))
    assert fresh.mode == "hosted" and fresh.hosted_token == "" and not fresh.effective_api_key()
    s = _ini(tmp_path)
    s.beginGroup("assistant")
    s.setValue("api_key", "sk-or-old")          # a 0.4.3 install: key stored, no mode
    s.endGroup()
    s.sync()
    old = load_config(_ini(tmp_path))
    assert old.mode == "own" and old.effective_api_key() == "sk-or-old"


def test_settings_dialog_panes_switch_and_config_carries_both(qapp, monkeypatch):
    from PySide6.QtCore import QUrl
    from ui import assistant_settings_dialog as asd
    from ui.assistant_settings_dialog import AssistantSettingsDialog
    from core.hosted import HOSTED_MODEL_LABEL, hosted_signin_url
    cfg = AgentConfig(mode="hosted", hosted_token="ffa_x", api_key="sk-own", model="own/m")
    dlg = AssistantSettingsDialog(cfg, recent=[], transport_factory=lambda: FakeTransport([]))
    assert dlg._hosted_radio.isChecked() and dlg._panes.currentIndex() == 0
    assert dlg._hosted_token.text() == "ffa_x" and dlg._hosted_model_label.text() == HOSTED_MODEL_LABEL
    assert dlg._panes.currentWidget().isAncestorOf(dlg._signin_btn)
    assert not dlg._panes.currentWidget().isAncestorOf(dlg._api_key)
    dlg._own_radio.setChecked(True)
    assert dlg._panes.currentIndex() == 1
    assert dlg._panes.currentWidget().isAncestorOf(dlg._api_key)
    assert dlg._api_key.text() == "sk-own" and dlg._model.currentText() == "own/m"
    out = dlg.config()
    assert out.mode == "own" and out.hosted_token == "ffa_x" and out.api_key == "sk-own"
    dlg._hosted_radio.setChecked(True)
    out = dlg.config()
    assert out.mode == "hosted" and out.api_key == "sk-own" and out.effective_api_key() == "ffa_x"
    # token show/hide
    from PySide6.QtWidgets import QLineEdit
    assert dlg._hosted_token.echoMode() == QLineEdit.EchoMode.Password
    dlg._show_token.setChecked(True)
    assert dlg._hosted_token.echoMode() == QLineEdit.EchoMode.Normal
    # sign-in opens the relay's Discord start URL
    opened = []
    monkeypatch.setattr(asd.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url)))
    dlg._signin_btn.click()
    assert opened and QUrl(opened[0]).toString() == hosted_signin_url()


def test_settings_dialog_hosted_test_connection_uses_me(qapp):
    from ui.assistant_settings_dialog import AssistantSettingsDialog

    class MeTransport(FakeTransport):
        def hosted_me(self, config):
            assert config.hosted_token == "ffa_x"
            return {"discord_username": "jack", "used_cents": 8, "limit_cents": 50}

    dlg = AssistantSettingsDialog(AgentConfig(mode="hosted", hosted_token="ffa_x"), recent=[],
                                  transport_factory=lambda: MeTransport([]))
    dlg._test()
    t0 = time.time()
    while dlg._worker is not None and time.time() - t0 < 5:
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg._test_status.text() == "Signed in as jack · $0.08 of $0.50 used this month"


def test_panel_hosted_without_token_shows_sign_in(qapp):
    from ui.assistant_panel import HOSTED_SETUP_BUTTON, OWN_SETUP_BUTTON
    from core.hosted import HOSTED_MODEL_LABEL
    panel = _panel_with(qapp, AgentConfig(mode="hosted", api_key="sk-own-unused"))
    assert not panel.has_key() and panel._stack.currentIndex() == 0
    assert panel._setup_btn.text() == HOSTED_SETUP_BUTTON
    assert "Discord" in panel._setup_hint.text()
    assert panel._model_label.text() == HOSTED_MODEL_LABEL
    own = _panel_with(qapp, AgentConfig(mode="own", hosted_token="ffa_unused"))
    assert not own.has_key() and own._setup_btn.text() == OWN_SETUP_BUTTON
    ready = _panel_with(qapp, AgentConfig(mode="hosted", hosted_token="ffa_x"))
    assert ready.has_key() and ready._stack.currentIndex() == 1


def test_panel_header_shows_allotment_after_quota_event(qapp):
    panel = _panel_with(qapp, AgentConfig(mode="hosted", hosted_token="ffa_x"))
    panel.render_event({"kind": "usage", "usage": {"prompt_tokens": 12_400, "completion_tokens": 2_100}})
    assert panel._usage_label.text() == "12.4k in · 2.1k out"          # no ~$ estimate in hosted mode
    panel.render_event({"kind": "quota", "quota": {"used_cents": 8.0, "limit_cents": 50.0,
                                                   "reset": "2026-10-01"}})
    assert panel._usage_label.text() == "12.4k in · 2.1k out · $0.08 of $0.50 used · resets Oct 1"
    assert "$0.08 of $0.50" in panel._usage_label.text()
    panel._new_chat()
    qapp.processEvents()
    assert panel._usage_label.text() == "$0.08 of $0.50 used · resets Oct 1"   # monthly figure outlives the chat
    # own-key mode keeps the estimate and ignores the allotment
    own = _panel_with(qapp, AgentConfig(api_key="k", model="test/model"))
    own.render_event({"kind": "usage", "usage": {"prompt_tokens": 12_400, "completion_tokens": 2_100}})
    own.render_event({"kind": "quota", "quota": {"used_cents": 8.0, "limit_cents": 50.0, "reset": ""}})
    assert own._usage_label.text() == "12.4k in · 2.1k out · ~$?"


def test_panel_402_error_adds_open_settings_button(qapp):
    from PySide6.QtWidgets import QPushButton
    panel = _panel_with(qapp, AgentConfig(mode="hosted", hosted_token="ffa_x"))
    base = _card_count(panel)
    panel.render_event({"kind": "error", "text": "Allotment used — resets Oct 1.", "status": 402})
    assert _card_count(panel) == base + 2
    holder = panel._transcript_layout.itemAt(base + 1).widget()
    btn = holder.findChild(QPushButton)
    assert btn is not None and btn.text() == "Open settings"
    panel.render_event({"kind": "error", "text": "Provider error", "status": 500})
    assert _card_count(panel) == base + 3


# ----- review fixes: thread affinity, 401 button, token shape, button copy -----

def _pump_until_probe_done(qapp, dlg, timeout=5.0):
    t0 = time.time()
    while dlg._worker is not None and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert dlg._worker is None, "test-connection probe did not finish"


def test_test_connection_result_is_handled_on_the_gui_thread(qapp):
    """The worker's succeeded/failed signals must land on the dialog's thread
    (a bound @Slot on a GUI-thread QObject is queued); a lambda receiver has
    no affinity and would restyle the QLabel from the worker thread."""
    import threading
    from ui.assistant_settings_dialog import AssistantSettingsDialog
    main_ident = threading.get_ident()
    probe = [{"model": "meta/muse-spark-1.3", **_reply("OK")}]
    dlg = AssistantSettingsDialog(AgentConfig(api_key="abc", model="meta/muse-spark-1.3"), recent=[],
                                  transport_factory=lambda: FakeTransport(probe))
    seen = []
    original = dlg._set_status

    def recording_set_status(text, ok):
        seen.append((threading.get_ident(), text, ok))
        original(text, ok)

    dlg._set_status = recording_set_status
    dlg._test()
    _pump_until_probe_done(qapp, dlg)
    texts = [t for _, t, _ in seen]
    assert texts == ["Testing…", "Connected — meta/muse-spark-1.3 replied."]
    assert [ident for ident, _, _ in seen] == [main_ident, main_ident]
    assert dlg._test_status.text() == "Connected — meta/muse-spark-1.3 replied."
    assert dlg._test_status.objectName() == "pillOk" and dlg._test_btn.isEnabled()


def test_test_connection_failure_is_handled_on_the_gui_thread(qapp):
    import threading
    from core.agent_loop import TransportError
    from ui.assistant_settings_dialog import AssistantSettingsDialog

    class Failing(FakeTransport):
        def chat(self, payload, config):
            assert threading.get_ident() != threading.main_thread().ident   # really off-thread
            raise TransportError(401, "API key rejected")

    dlg = AssistantSettingsDialog(AgentConfig(api_key="abc", model="m/x"), recent=[],
                                  transport_factory=lambda: Failing([]))
    idents = []
    original = dlg._set_status
    dlg._set_status = lambda text, ok: (idents.append(threading.get_ident()), original(text, ok))
    dlg._test()
    _pump_until_probe_done(qapp, dlg)
    assert idents == [threading.get_ident()] * 2
    assert dlg._test_status.text() == "API key rejected"
    assert dlg._test_status.objectName() == "issueTextError"


def test_panel_hosted_401_adds_open_settings_button_own_401_does_not(qapp):
    from PySide6.QtWidgets import QPushButton
    panel = _panel_with(qapp, AgentConfig(mode="hosted", hosted_token="ffa_x"))
    base = _card_count(panel)
    panel.render_event({"kind": "error", "text": "That token isn't valid.", "status": 401})
    assert _card_count(panel) == base + 2
    holder = panel._transcript_layout.itemAt(base + 1).widget()
    btn = holder.findChild(QPushButton)
    assert btn is not None and btn.text() == "Open settings"
    own = _panel_with(qapp, AgentConfig(api_key="k", model="test/model"))
    base = _card_count(own)
    own.render_event({"kind": "error", "text": "API key rejected", "status": 401})
    assert _card_count(own) == base + 1                     # own-key 401: no button
    own.render_event({"kind": "error", "text": "Out of credits", "status": 402})
    assert _card_count(own) == base + 3                     # 402 still gets one in both modes


def test_panel_hosted_has_key_requires_ffa_prefix(qapp):
    for bad in ("abc", "sk-or-v1-x", "Token: ffa_x"):
        panel = _panel_with(qapp, AgentConfig(mode="hosted", hosted_token=bad))
        assert not panel.has_key() and panel._stack.currentIndex() == 0, bad
    ok = _panel_with(qapp, AgentConfig(mode="hosted", hosted_token="ffa_x"))
    assert ok.has_key() and ok._stack.currentIndex() == 1
    # own-key mode is unchanged: any non-empty key counts
    own = _panel_with(qapp, AgentConfig(mode="own", api_key="anything"))
    assert own.has_key()


def test_settings_dialog_strips_token_and_rejects_bad_shape_without_blocking_save(qapp):
    from core.agent_loop import BAD_TOKEN_SHAPE_TEXT
    from ui.assistant_settings_dialog import AssistantSettingsDialog
    calls = []

    class MeTransport(FakeTransport):
        def hosted_me(self, config):
            calls.append(config.hosted_token)
            return {"discord_username": "jack", "used_cents": 8, "limit_cents": 50}

    dlg = AssistantSettingsDialog(AgentConfig(mode="hosted"), recent=[],
                                  transport_factory=lambda: MeTransport([]))
    # CRLF from a clipboard copy is stripped before anything sees the token
    dlg._hosted_token.setText("ffa_abc\r\n")
    assert dlg.config().hosted_token == "ffa_abc"
    dlg._test()
    _pump_until_probe_done(qapp, dlg)
    assert calls == ["ffa_abc"]
    assert dlg._test_status.text().startswith("Signed in as jack")
    # a 'Token: ffa_...' paste is kept as typed (save isn't blocked) but the probe says why it's wrong
    for bad in ("Token: ffa_abc", "abc"):
        dlg._hosted_token.setText(bad)
        assert dlg.config().hosted_token == bad
        dlg._test()
        _pump_until_probe_done(qapp, dlg)
        assert dlg._test_status.text() == BAD_TOKEN_SHAPE_TEXT
        assert dlg._test_status.objectName() == "issueTextError"
        assert dlg._test_btn.isEnabled()
    assert calls == ["ffa_abc"]                              # no request went out for the bad ones


def test_hosted_setup_button_copy_says_it_opens_settings(qapp):
    from ui.assistant_panel import HOSTED_SETUP_BUTTON
    assert HOSTED_SETUP_BUTTON == "Set up: sign in with Discord"
    panel = _panel_with(qapp, AgentConfig(mode="hosted"))
    assert panel._setup_btn.text() == "Set up: sign in with Discord"
