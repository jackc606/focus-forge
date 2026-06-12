"""Shared factory that builds the editor widget for a reward/availability param.

Used by both the reward editor and the availability editor so widget behaviour
(select / number / textarea / string / state / focus) lives in one place.
``set_value(value)`` is called whenever the widget's value changes.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter, QLineEdit, QPlainTextEdit

from core.country_tags import MD_COUNTRY_TAGS
from core.md_parties import MD_PARTIES
from core.reward_presets import EQUIPMENT_TYPES

from .no_scroll import NoScrollComboBox as QComboBox
from .no_scroll import NoScrollDoubleSpinBox as QDoubleSpinBox
from .state_provider import state_provider
from .tech_provider import tech_provider

_COUNTRY_ITEMS = [(t.tag, f"{t.tag} — {t.name}") for t in MD_COUNTRY_TAGS]


def _fmt_opinion(val) -> str:
    """'+25' / '-10' / '+0.5' — signed, trimming a trailing .0."""
    iv = int(val)
    return f"{iv:+d}" if float(val) == iv else f"{val:+g}"


def make_param_widget(param, current, set_value, *, country_tag: str = "",
                      focus_ids=(), idea_refs=(), event_refs=(), leader_refs=()):
    if param.type == "select":
        cb = QComboBox()
        cb.addItems(param.options or [])
        cur = str(current)
        if cur and cb.findText(cur) < 0:
            cb.addItem(cur)  # legacy/unknown stored value — keep it selectable
        cb.setCurrentText(cur)
        cb.currentTextChanged.connect(lambda val: set_value(val))
        return cb
    if param.type == "equipment":
        items = [(e, e) for e in EQUIPMENT_TYPES]
        return _id_combo(items, current, set_value, numeric=False, completer=True,
                         empty_tip="Type an MD equipment id")
    if param.type == "state":
        states = state_provider().states_for_country(country_tag)
        return _id_combo(states, current, set_value, numeric=True,
                         empty_tip="No MD states for this tag — type a state id")
    if param.type == "focus":
        items = [(fid, fid) for fid in (focus_ids or [])]
        return _id_combo(items, current, set_value, numeric=False,
                         empty_tip="Type a focus id")
    if param.type == "tech":
        return _grouped_combo(tech_provider().tech_groups(), current, set_value,
                              empty_tip="No MD technologies found — type a tech id")
    if param.type == "tech_category":
        cats = tech_provider().tech_categories()
        return _id_combo([(c, c) for c in cats], current, set_value, numeric=False,
                         completer=True, empty_tip="No MD categories — type a CAT_ name")
    if param.type == "building":
        blds = tech_provider().buildings()  # [(id, display_name)]
        items = [(bid, f"{name}  ({bid})" if name != bid else bid) for bid, name in blds]
        return _id_combo(items, current, set_value, numeric=False,
                         completer=True, empty_tip="No MD buildings — type a building id")
    if param.type == "opinion_modifier":
        mods = tech_provider().opinion_modifiers()
        items = [(mid, f"{mid}  ({_fmt_opinion(val)})" if val is not None else mid)
                 for mid, val in mods]
        return _id_combo(items, current, set_value, numeric=False, completer=True,
                         empty_tip="No MD opinion modifiers — type a modifier id")
    if param.type == "country_tag":
        return _id_combo(_COUNTRY_ITEMS, current, set_value, numeric=False,
                         completer=True, empty_tip="Type a country tag")
    if param.type == "party_index":
        items = [(idx, f"{name}  ({idx})") for idx, name in MD_PARTIES]
        return _id_combo(items, current, set_value, numeric=True, completer=True,
                         empty_tip="Pick an MD party, or type its index")
    if param.type == "idea_ref":
        return _id_combo(list(idea_refs or []), current, set_value, numeric=False,
                         completer=True, empty_tip="Type an idea id")
    if param.type == "event_ref":
        return _id_combo(list(event_refs or []), current, set_value, numeric=False,
                         completer=True, empty_tip="Type an event id (e.g. MEX_forge.1)")
    if param.type == "leader_ref":
        return _leader_combo(list(leader_refs or []), current, set_value)
    if param.type == "number":
        sb = QDoubleSpinBox()
        sb.setRange(-1e9, 1e9)
        sb.setDecimals(4)
        try:
            sb.setValue(float(current))
        except (TypeError, ValueError):
            sb.setValue(0)
        if param.step:
            sb.setSingleStep(param.step)
        sb.valueChanged.connect(lambda val: set_value(val))
        return sb
    if param.type == "textarea":
        te = QPlainTextEdit()
        te.setMaximumHeight(60)
        te.setPlainText(str(current or ""))
        te.textChanged.connect(lambda: set_value(te.toPlainText()))
        return te
    le = QLineEdit()
    le.setText(str(current or ""))
    if param.placeholder:
        le.setPlaceholderText(param.placeholder)
    le.editingFinished.connect(lambda: set_value(le.text()))
    return le


def _id_combo(items, current, set_value, *, numeric: bool, empty_tip: str,
              completer: bool = False):
    """Editable combo of (value, label); stays typable. ``numeric`` stores an int.

    ``items`` is a list of (value, label). For states value is the int id; for
    focuses/categories value == the stored string.
    """
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    for value, label in items:
        cb.addItem(label, value)
    if completer and items:
        strings = sorted({str(v) for v, _l in items} | {str(l) for _v, l in items})
        comp = QCompleter(strings, cb)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        cb.setCompleter(comp)
    # NB: ``current or ""`` would collapse a legitimate stored 0 (party index 0,
    # for example) into an empty field.
    cur = "" if current is None or current == "" else str(current).strip()
    idx = -1
    if cur != "":
        idx = cb.findData(int(cur)) if (numeric and cur.lstrip("-").isdigit()) else cb.findData(cur)
        if idx < 0 and not numeric:
            idx = cb.findText(cur)
    if idx >= 0:
        cb.setCurrentIndex(idx)
    else:
        cb.setEditText(cur)
    cb.setToolTip(f"{len(items)} options; or type a value" if items else empty_tip)

    def commit():
        i = cb.currentIndex()
        if i >= 0 and cb.currentText() == cb.itemText(i):
            set_value(cb.itemData(i))
            return
        text = cb.currentText().strip()
        # The completer can fill the line edit with a display LABEL without
        # updating the combo index — map it back to its item value, never store
        # the decorated label (or 0) in the params.
        j = cb.findText(text)
        if j >= 0 and cb.itemData(j) is not None:
            set_value(cb.itemData(j))
            return
        if numeric:
            m = re.search(r"-?\d+", text)
            set_value(int(m.group(0)) if m else 0)
        else:
            set_value(text)

    cb.currentIndexChanged.connect(lambda _i: commit())
    cb.lineEdit().editingFinished.connect(commit)
    return cb


def _leader_combo(groups, current, set_value):
    """Non-editable combo of leaders grouped into 'Preset MD leaders' / 'Custom
    leaders'. ``groups`` = [(group_label, [(encoded_value, display_name)])]; the
    item data is the opaque encoded leader value the reward builder decodes."""
    cb = QComboBox()
    cb.addItem("(choose a leader)", "")
    for label, items in groups:
        if not items:
            continue
        cb.addItem(f"— {label} —", None)
        cb.model().item(cb.count() - 1).setEnabled(False)
        for value, name in items:
            cb.addItem(f"  {name}", value)
    cur = str(current or "")
    idx = cb.findData(cur) if cur else 0
    if cur and idx < 0:
        # Stored leader isn't in the current lists (e.g. edited project) — keep it.
        from core.reward_presets import decode_leader
        data = decode_leader(cur)
        name = (data or {}).get("name") or "current selection"
        cb.insertItem(1, f"  {name}", cur)
        idx = 1
    cb.setCurrentIndex(idx if idx >= 0 else 0)
    if not any(items for _l, items in groups):
        cb.setToolTip("No leaders found — add custom leaders in the Country editor, "
                      "or configure your MD folder in Settings.")
    cb.currentIndexChanged.connect(lambda i: set_value(cb.itemData(i) or ""))
    return cb


def _grouped_combo(groups, current, set_value, *, empty_tip: str):
    """Editable combo with disabled group headers; items store an id in data.
    ``groups`` = [(group_label, [(id, display)])]. Stays typable (raw id)."""
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    cb.setMaxVisibleItems(24)
    all_strings = []
    cb.addItem("", "")  # blank
    for label, items in groups:
        cb.addItem(f"— {label} —", None)
        cb.model().item(cb.count() - 1).setEnabled(False)
        for tid, display in items:
            cb.addItem(f"  {display}", tid)
            all_strings.append(display)
            all_strings.append(tid)
    cur = str(current or "").strip()
    idx = cb.findData(cur) if cur else -1
    if idx >= 0:
        cb.setCurrentIndex(idx)
    else:
        cb.setEditText(cur)
    cb.setToolTip("Pick a technology by research category, or type a tech id"
                  if groups else empty_tip)
    if all_strings:
        comp = QCompleter(sorted(set(all_strings)), cb)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        cb.setCompleter(comp)

    def commit():
        i = cb.currentIndex()
        data = cb.itemData(i) if (i >= 0 and cb.currentText() == cb.itemText(i)) else None
        if data:
            set_value(data)
        else:
            set_value(cb.currentText().strip().lstrip("— ").strip())

    cb.currentIndexChanged.connect(lambda _i: commit())
    cb.lineEdit().editingFinished.connect(commit)
    return cb
