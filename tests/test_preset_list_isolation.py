"""Preset-list draft isolation: the event/decision editor dialogs must edit a
DEEP COPY of the model's RewardItem lists so Cancel really cancels — writes land
in the model only through the accept path (result_* → model.update_*)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.types import (  # noqa: E402
    AvailabilityRule,
    CompletionReward,
    DecisionData,
    EventData,
    EventOption,
    RewardItem,
)
from ui.preset_list import ConditionListWidget, EffectListWidget  # noqa: E402
from ui.project_model import ProjectModel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _fast_providers(monkeypatch):
    """Never scan real HOI4/MD installs from tests: blank the icon roots and
    pre-seed the tech-provider caches the dialogs touch."""
    from ui.icon_provider import provider
    from ui.tech_provider import tech_provider
    p = provider()
    monkeypatch.setattr(p, "_roots", [])
    monkeypatch.setattr(p, "_extra_roots", [])
    monkeypatch.setattr(p, "_index_built", True)
    monkeypatch.setattr(p, "_index", {})
    tp = tech_provider()
    monkeypatch.setattr(tp, "_decision_categories", [])
    monkeypatch.setattr(tp, "_idea_mod_groups", [])
    monkeypatch.setattr(tp, "_idea_mod_tooltips", {})


def _pp_item(amount=50):
    return RewardItem(kind="political_power", enabled=True, params={"amount": amount})


def _flag_item(flag="my_flag"):
    return RewardItem(kind="has_country_flag", enabled=True, params={"flag": flag})


def _card(widget, index=0):
    return widget._items_box.itemAt(index).widget()


# ----- widget-level isolation -----

def test_effect_list_deep_copies_items(app):
    original = [_pp_item(50)]
    w = EffectListWidget(items=original)
    assert w._items[0] is not original[0]
    assert w._items[0].params is not original[0].params


def test_card_edit_does_not_touch_original(app):
    original = [_pp_item(50)]
    w = EffectListWidget(items=original)
    _card(w)._set_param("amount", 120)
    assert original[0].params["amount"] == 50           # model object untouched
    assert w.items()[0].params["amount"] == 120         # draft carries the edit


def test_card_enable_toggle_does_not_touch_original(app):
    original = [_flag_item()]
    w = ConditionListWidget(items=original)
    _card(w)._toggle_enabled(False)
    assert original[0].enabled is True
    assert w.items()[0].enabled is False


def test_open_does_not_backfill_original_params(app):
    # Older project files may miss param keys; the card back-fills defaults on
    # open — that must hit the draft copy only, never the live model object.
    original = [RewardItem(kind="political_power", enabled=True, params={})]
    EffectListWidget(items=original)
    assert original[0].params == {}


# ----- event editor dialog: cancel vs accept -----

def _model_with_event():
    m = ProjectModel()
    event = EventData(
        id="MEX_forge.100", title="Test Event",
        options=[EventOption(key="a", text="OK", items=[_pp_item(50)])],
        trigger=AvailabilityRule(items=[_flag_item("gate_flag")]),
    )
    m.replace_project(m.project, path=None)  # reset dirty tracking baseline
    m.project.events.append(event)
    return m, event


def test_event_editor_cancel_leaves_model_untouched(app):
    from ui.event_editor import EventEditorDialog
    m, event = _model_with_event()
    dlg = EventEditorDialog(m, event=event)
    # Edit the option's PP amount and the event trigger flag through the cards.
    opt_card = next(iter(dlg._option_cards()))
    _card(opt_card._effects)._set_param("amount", 999)
    _card(dlg._event_trigger)._set_param("flag", "other_flag")
    dlg.reject()
    assert event.options[0].items[0].params["amount"] == 50
    assert event.trigger.items[0].params["flag"] == "gate_flag"
    assert m.is_dirty() is False


def test_event_editor_accept_path_writes_back(app):
    from ui.event_editor import EventEditorDialog
    m, event = _model_with_event()
    dlg = EventEditorDialog(m, event=event)
    opt_card = next(iter(dlg._option_cards()))
    _card(opt_card._effects)._set_param("amount", 999)
    # The events manager's accept path: result_event() → model.update_event().
    m.update_event(event.id, dlg.result_event())
    stored = next(e for e in m.project.events if e.id == "MEX_forge.100")
    assert stored.options[0].items[0].params["amount"] == 999
    assert m.is_dirty() is True


# ----- decision editor dialog: cancel vs accept -----

def _model_with_decision():
    m = ProjectModel()
    decision = DecisionData(
        id="MEX_test_decision", title="Test Decision", category="cat",
        visible=AvailabilityRule(items=[_flag_item("vis_flag")]),
        completeEffect=CompletionReward(items=[_pp_item(25)]),
    )
    m.replace_project(m.project, path=None)
    m.project.decisions.append(decision)
    return m, decision


def test_decision_editor_cancel_leaves_model_untouched(app):
    from ui.decision_editor import DecisionEditorDialog
    m, decision = _model_with_decision()
    dlg = DecisionEditorDialog(m, decision=decision)
    _card(dlg._visible)._set_param("flag", "changed_flag")
    _card(dlg._complete)._set_param("amount", 777)
    dlg.reject()
    assert decision.visible.items[0].params["flag"] == "vis_flag"
    assert decision.completeEffect.items[0].params["amount"] == 25
    assert m.is_dirty() is False


def test_decision_editor_accept_path_writes_back(app):
    from ui.decision_editor import DecisionEditorDialog
    m, decision = _model_with_decision()
    dlg = DecisionEditorDialog(m, decision=decision)
    _card(dlg._complete)._set_param("amount", 777)
    m.update_decision(decision.id, dlg.result_decision())
    stored = next(d for d in m.project.decisions if d.id == "MEX_test_decision")
    assert stored.completeEffect.items[0].params["amount"] == 777
    assert m.is_dirty() is True
