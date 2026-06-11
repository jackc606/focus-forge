"""Dialog to author a HOI4 / Millennium Dawn event: country or news event, with a
picture, fire settings (is_triggered_only / mtth / hidden / major / fire_only_once),
an optional event-level trigger, and a list of options. Each option has a button
text, structured effects (reusing the focus reward presets), an optional per-option
trigger, and an optional ai_chance. Produces an ``EventData``.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.exporters import export_events
from core.types import (
    AvailabilityRule,
    EventData,
    EventOption,
    ExportSettings,
    FocusForgeProject,
)

from . import theme as T
from .country_editor import _scaled_b64_png
from .country_export import _qimage_from_b64
from .icon_picker import IconPickerDialog
from .icon_provider import provider
from .no_scroll import NoScrollComboBox, NoScrollSpinBox
from .preset_list import ConditionListWidget, EffectListWidget
from .widgets import hint, panel_header, section_header

# HOI4 event pictures are wide banner images, exported as .dds. The well-known
# standard is 420×175 px; MD's own are typically ~217×163 (report) or ~397×153
# (news). Aspect ratio matters more than exact size — keep it a wide ~2.4:1 banner.
_EVENT_PIC_W, _EVENT_PIC_H = 420, 175
# In-dialog thumbnail of the banner above, at roughly 1/5 scale.
_PIC_PREVIEW_W, _PIC_PREVIEW_H = 84, 40
_IMG_FILTER = "Images (*.png *.tga *.jpg *.jpeg *.bmp *.dds);;All files (*)"

# Curated set of common HOI4 / MD event pictures. The combo stays editable, so any
# GFX_… sprite name can be typed.
EVENT_PICTURES = [
    "GFX_report_event_generic_parliament",
    "GFX_report_event_political_meeting",
    "GFX_report_event_election_results",
    "GFX_report_event_press_conference",
    "GFX_report_event_journalists",
    "GFX_report_event_generic_factory",
    "GFX_report_event_economy",
    "GFX_report_event_military_parade",
    "GFX_report_event_soldiers_marching",
    "GFX_report_event_protest",
    "GFX_report_event_generic_rally",
    "GFX_report_event_generic_sign_treaty1",
    "GFX_report_event_generic_sign_treaty2",
    "GFX_report_event_crowd_cheering",
]

_OPTION_KEYS = "abcdefghijklmnopqrstuvwxyz"


class _OptionCard(QFrame):
    """One event option: key, button text, effects, optional trigger + ai_chance."""

    def __init__(self, option: EventOption, *, country_tag, idea_refs, event_refs,
                 focus_ids, on_change, on_delete, on_move, leader_refs=()) -> None:
        super().__init__()
        self.setObjectName("optionCard")
        self.setFrameShape(QFrame.StyledPanel)
        self._on_change = on_change
        self._on_delete = on_delete
        self._on_move = on_move

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_MD, T.SPACE_MD, T.SPACE_MD, T.SPACE_MD)
        v.setSpacing(T.SPACE_SM)

        header = QHBoxLayout()
        self._title = QLabel("<b>Option</b>")
        header.addWidget(self._title)
        header.addStretch(1)
        up = QPushButton("↑")
        up.setFixedWidth(T.ICON_BUTTON)
        up.setToolTip("Move option up")
        up.clicked.connect(lambda: self._on_move(self, -1))
        down = QPushButton("↓")
        down.setFixedWidth(T.ICON_BUTTON)
        down.setToolTip("Move option down")
        down.clicked.connect(lambda: self._on_move(self, 1))
        delete = QPushButton("×")
        delete.setObjectName("deleteButton")
        delete.setFixedWidth(T.ICON_BUTTON)
        delete.setToolTip("Remove option")
        delete.clicked.connect(lambda: self._on_delete(self))
        header.addWidget(up)
        header.addWidget(down)
        header.addWidget(delete)
        v.addLayout(header)

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        self._key = QLineEdit(option.key or "")
        self._key.setMaximumWidth(120)
        self._key.textChanged.connect(lambda *_: self._on_change())
        form.addRow("Key", self._key)
        self._text = QLineEdit(option.text or "")
        self._text.setPlaceholderText("Button text shown in-game")
        self._text.textChanged.connect(lambda *_: self._on_change())
        form.addRow("Button text", self._text)
        v.addLayout(form)

        v.addWidget(section_header("Effects"))
        self._effects = EffectListWidget(
            items=option.items, raw_lines=option.effectRawLines,
            country_tag=country_tag, idea_refs=idea_refs, event_refs=event_refs,
            leader_refs=leader_refs, on_change=self._on_change)
        v.addWidget(self._effects)

        # Optional per-option trigger.
        self._trigger_chk = QCheckBox("Only show this option when conditions are met")
        has_trigger = bool(option.trigger and (option.trigger.items or option.trigger.rawLines))
        self._trigger_chk.setChecked(has_trigger)
        self._trigger_chk.toggled.connect(self._toggle_trigger)
        v.addWidget(self._trigger_chk)
        self._trigger = ConditionListWidget(
            items=(option.trigger.items if option.trigger else None),
            raw_lines=(option.trigger.rawLines if option.trigger else None),
            country_tag=country_tag, focus_ids=focus_ids, on_change=self._on_change)
        self._trigger.setVisible(has_trigger)
        v.addWidget(self._trigger)

        # Optional ai_chance.
        ai_row = QHBoxLayout()
        self._ai_chk = QCheckBox("AI chance (base)")
        self._ai_chk.setChecked(option.aiChance is not None)
        self._ai_chk.toggled.connect(self._toggle_ai)
        self._ai_spin = NoScrollSpinBox()
        self._ai_spin.setRange(0, 1000)
        self._ai_spin.setValue(int(option.aiChance) if option.aiChance is not None else 10)
        self._ai_spin.setEnabled(option.aiChance is not None)
        self._ai_spin.valueChanged.connect(lambda *_: self._on_change())
        ai_row.addWidget(self._ai_chk)
        ai_row.addWidget(self._ai_spin)
        ai_row.addStretch(1)
        v.addLayout(ai_row)

    def set_label(self, idx: int, event_id: str) -> None:
        fallback = _OPTION_KEYS[idx] if idx < len(_OPTION_KEYS) else "?"
        key = self._key.text().strip() or fallback
        self._title.setText(f"<b>Option {idx + 1}</b>  ·  {event_id}.{key}")

    def _toggle_trigger(self, checked: bool) -> None:
        self._trigger.setVisible(checked)
        self._on_change()

    def _toggle_ai(self, checked: bool) -> None:
        self._ai_spin.setEnabled(checked)
        self._on_change()

    def result_option(self) -> EventOption:
        trigger = None
        if self._trigger_chk.isChecked():
            items = self._trigger.items()
            raw = self._trigger.raw_lines()
            if items or raw:
                trigger = AvailabilityRule(items=items, rawLines=raw)
        ai = float(self._ai_spin.value()) if self._ai_chk.isChecked() else None
        return EventOption(
            key=self._key.text().strip(),
            text=self._text.text().strip(),
            items=self._effects.items(),
            trigger=trigger,
            aiChance=ai,
            effectRawLines=self._effects.raw_lines() or [],
        )


class EventEditorDialog(QDialog):
    def __init__(self, model, event: EventData = None, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._editing = event is not None
        self.setWindowTitle("Edit Event" if self._editing else "New Event")
        self.resize(620, 760)
        self._built = False

        tag = model.project.countryTag
        self._idea_refs = [(i.id, f"{i.title or i.id} ({i.id})") for i in model.project.ideas]
        self._event_refs = [(e.id, f"{e.title or e.id} ({e.id})") for e in model.project.events]
        self._focus_ids = [f.id for f in model.project.focuses]
        self._country_tag = tag
        from .leader_options import build_leader_refs
        self._leader_refs = build_leader_refs(model.project)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        root.setSpacing(T.SPACE_MD)
        root.addWidget(panel_header("Event"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_MD)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ----- core fields -----
        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)

        self._id = QLineEdit(event.id if event else self._suggest_id())
        self._id.textChanged.connect(lambda *_: self._refresh_preview())
        # While editing a new event the id tracks the title (<prefix>.<slug>); a
        # manual id edit (textEdited, not our programmatic setText) detaches it.
        self._id_edited = self._editing
        self._id.textEdited.connect(lambda *_: setattr(self, "_id_edited", True))
        form.addRow("ID", self._id)

        self._title = QLineEdit(event.title if event else "")
        self._title.textChanged.connect(self._on_title)
        form.addRow("Title", self._title)

        self._desc = QPlainTextEdit(event.description if event else "")
        self._desc.setMaximumHeight(T.TEXTAREA_MEDIUM)
        form.addRow("Description", self._desc)

        self._type = NoScrollComboBox()
        self._type.addItem("Country event", "country_event")
        self._type.addItem("News event", "news_event")
        self._type.setCurrentIndex(0 if (not event or event.eventType != "news_event") else 1)
        self._type.currentIndexChanged.connect(lambda *_: self._refresh_preview())
        form.addRow("Type", self._type)

        # Picture: a visual preview + picker (in-game pictures shown as thumbnails,
        # not text rows) + custom image import.
        self._picture_name = (event.picture if event else "") or EVENT_PICTURES[0]
        self._picture_data = (event.pictureData if event else "") or ""
        pic_row = QWidget()
        pic_h = QHBoxLayout(pic_row)
        pic_h.setContentsMargins(0, 0, 0, 0)
        pic_h.setSpacing(T.SPACE_SM)
        self._pic_prev = QLabel()
        self._pic_prev.setObjectName("iconPreview")
        self._pic_prev.setFixedSize(_PIC_PREVIEW_W, _PIC_PREVIEW_H)
        self._pic_prev.setAlignment(Qt.AlignCenter)
        pic_h.addWidget(self._pic_prev)
        self._pic_name_lbl = QLabel()
        self._pic_name_lbl.setWordWrap(True)
        pic_h.addWidget(self._pic_name_lbl, 1)
        choose = QPushButton("Picture…")
        choose.setToolTip("Choose an in-game event picture from a visual grid.")
        choose.clicked.connect(self._choose_picture)
        imp = QPushButton("Import…")
        imp.setToolTip(
            f"Import a custom event picture. HOI4 event pictures are wide banners, "
            f"~{_EVENT_PIC_W}×{_EVENT_PIC_H} px, exported as .dds (.png/.tga/.dds in).")
        imp.clicked.connect(self._import_picture)
        pic_h.addWidget(choose)
        pic_h.addWidget(imp)
        form.addRow("Picture", pic_row)

        # ----- fire settings -----
        flags_row = QHBoxLayout()
        self._triggered_only = QCheckBox("is_triggered_only")
        self._triggered_only.setChecked(event.isTriggeredOnly if event else True)
        self._triggered_only.setToolTip("Only fires when another script (e.g. a focus) "
                                        "calls it. Recommended for focus-fired events.")
        self._triggered_only.toggled.connect(self._on_triggered_toggle)
        self._hidden = QCheckBox("hidden")
        self._hidden.setChecked(event.hidden if event else False)
        self._hidden.toggled.connect(lambda *_: self._refresh_preview())
        self._major = QCheckBox("major")
        self._major.setChecked(event.major if event else False)
        self._major.toggled.connect(lambda *_: self._refresh_preview())
        self._fire_once = QCheckBox("fire_only_once")
        self._fire_once.setChecked(event.fireOnlyOnce if event else False)
        self._fire_once.toggled.connect(lambda *_: self._refresh_preview())
        for w in (self._triggered_only, self._hidden, self._major, self._fire_once):
            flags_row.addWidget(w)
        flags_row.addStretch(1)
        v.addLayout(flags_row)

        mtth_row = QHBoxLayout()
        self._mtth_label = QLabel("Mean time to happen (days)")
        self._mtth = NoScrollSpinBox()
        self._mtth.setRange(0, 100000)
        self._mtth.setSpecialValueText("(off)")
        self._mtth.setValue(int(event.meanTimeToHappen) if (event and event.meanTimeToHappen) else 0)
        self._mtth.valueChanged.connect(lambda *_: self._refresh_preview())
        mtth_row.addWidget(self._mtth_label)
        mtth_row.addWidget(self._mtth)
        mtth_row.addStretch(1)
        v.addLayout(mtth_row)
        v.addWidget(hint("Mean time to happen only applies when is_triggered_only is off."))

        # ----- fire on an exact date -----
        date_row = QHBoxLayout()
        self._fire_date_chk = QCheckBox("Fire on exact date")
        has_fire_date = bool(event and (event.fireOnDate or "").strip())
        self._fire_date_chk.setChecked(has_fire_date)
        self._fire_date_chk.toggled.connect(self._on_fire_date_toggle)
        self._fire_date = QLineEdit((event.fireOnDate or "").strip() if event else "")
        self._fire_date.setPlaceholderText("year.month.day — e.g. 2003.3.20")
        self._fire_date.setMaximumWidth(220)
        self._fire_date.textChanged.connect(lambda *_: self._refresh_preview())
        date_row.addWidget(self._fire_date_chk)
        date_row.addWidget(self._fire_date)
        date_row.addStretch(1)
        v.addLayout(date_row)
        v.addWidget(hint("Lands exactly once, on that date, for this country: exports as "
                         "is_triggered_only + fire_only_once with a date trigger, attempted "
                         "daily from an on_daily on_action (a small on_actions file is added "
                         "to the export)."))

        # ----- event-level trigger -----
        v.addWidget(section_header("Event trigger (optional)"))
        v.addWidget(hint("Conditions that must hold for this event to be able to fire."))
        self._event_trigger = ConditionListWidget(
            items=(event.trigger.items if (event and event.trigger) else None),
            raw_lines=(event.trigger.rawLines if (event and event.trigger) else None),
            country_tag=tag, focus_ids=self._focus_ids, on_change=self._refresh_preview)
        v.addWidget(self._event_trigger)

        # ----- options -----
        v.addWidget(section_header("Options"))
        v.addWidget(hint("Every visible event needs at least one option (the button "
                         "the player clicks)."))
        self._options_box = QVBoxLayout()
        self._options_box.setSpacing(T.SPACE_SM)
        v.addLayout(self._options_box)
        add_opt = QPushButton("+ Add option")
        add_opt.clicked.connect(lambda: self._add_option())
        v.addWidget(add_opt)

        # ----- live preview -----
        v.addWidget(section_header("Generated event"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setObjectName("scriptPreview")
        self._preview.setMinimumHeight(120)
        v.addWidget(self._preview)

        # ----- buttons -----
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save Event")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Seed options.
        seed = list(event.options) if (event and event.options) else [EventOption(key="a", text="")]
        for opt in seed:
            self._add_option(opt)

        self._built = True
        self._on_triggered_toggle(self._triggered_only.isChecked())
        self._on_fire_date_toggle(self._fire_date_chk.isChecked())
        self._refresh_picture_preview()
        self._refresh_preview()

    # ----- id suggestion -----
    def _loc_prefix(self) -> str:
        return (self._model.project.exportSettings.localisationPrefix or "").strip() or "namespace"

    def _suggest_id(self) -> str:
        prefix = self._loc_prefix()
        nums = []
        for e in self._model.project.events:
            m = re.match(rf"^{re.escape(prefix)}\.(\d+)$", e.id or "")
            if m:
                nums.append(int(m.group(1)))
        return f"{prefix}.{(max(nums) + 1) if nums else 1}"

    def _auto_id_from_title(self, title: str) -> str:
        """``<prefix>.<slug>`` from a title (event ids must keep the add_namespace
        prefix), e.g. 'The First Draft' → 'MEX_forge.the_first_draft'. Falls back to
        the numbered suggestion while the title is still empty."""
        slug = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
        return f"{self._loc_prefix()}.{slug}" if slug else self._suggest_id()

    def _on_title(self, text: str) -> None:
        # Auto-fill the id from the title until the user hand-edits the id.
        if self._id_edited:
            return
        self._id.setText(self._auto_id_from_title(text))

    # ----- picture -----
    def _refresh_picture_preview(self) -> None:
        pm = None
        if self._picture_data:
            img = _qimage_from_b64(self._picture_data)
            if img is not None and not img.isNull():
                pm = QPixmap.fromImage(img)
            self._pic_name_lbl.setText("(custom image)")
        elif self._picture_name:
            pm = provider().pixmap(self._picture_name)
            label = self._picture_name
            self._pic_name_lbl.setText(label[4:] if label.lower().startswith("gfx_") else label)
        else:
            self._pic_name_lbl.setText("(none)")
        if pm is not None and not pm.isNull():
            self._pic_prev.setPixmap(pm.scaled(
                self._pic_prev.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._pic_prev.clear()

    def _choose_picture(self) -> None:
        sprites = provider().event_picture_sprites()
        if not sprites:
            QMessageBox.information(
                self, "No event pictures",
                "No in-game event pictures found. Add your HOI4 / mod folders in "
                "Settings → In-game Icons, or use Import… for a custom image.")
            return
        dlg = IconPickerDialog(current=self._picture_name, parent=self, sprites=sprites,
                               title="Choose Event Picture")
        if dlg.exec() and dlg.selected_name():
            self._picture_name = dlg.selected_name()
            self._picture_data = ""
            self._refresh_picture_preview()
            self._refresh_preview()

    def _import_picture(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import event picture — ~{_EVENT_PIC_W}×{_EVENT_PIC_H} px wide banner "
            f"(.png/.tga/.dds)",
            "", _IMG_FILTER)
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Import failed",
                                "Couldn't read that image — use a .png, .tga, or .dds.")
            return
        # Auto-scale to the standard HOI4 event-picture banner size (420×175).
        self._picture_data = _scaled_b64_png(img, _EVENT_PIC_W, _EVENT_PIC_H)
        self._refresh_picture_preview()
        self._refresh_preview()

    # ----- options management -----
    def _option_cards(self):
        for i in range(self._options_box.count()):
            w = self._options_box.itemAt(i).widget()
            if isinstance(w, _OptionCard):
                yield w

    def _next_key(self) -> str:
        used = {c._key.text().strip() for c in self._option_cards()}
        for k in _OPTION_KEYS:
            if k not in used:
                return k
        return ""

    def _add_option(self, option: EventOption = None) -> None:
        if option is None:
            option = EventOption(key=self._next_key(), text="")
        card = _OptionCard(
            option, country_tag=self._country_tag, idea_refs=self._idea_refs,
            event_refs=self._event_refs, focus_ids=self._focus_ids,
            on_change=self._refresh_preview, on_delete=self._delete_option,
            on_move=self._move_option, leader_refs=self._leader_refs)
        self._options_box.addWidget(card)
        self._relabel_options()
        self._refresh_preview()

    def _delete_option(self, card: _OptionCard) -> None:
        self._options_box.removeWidget(card)
        card.deleteLater()
        self._relabel_options()
        self._refresh_preview()

    def _move_option(self, card: _OptionCard, delta: int) -> None:
        idx = self._options_box.indexOf(card)
        new_idx = idx + delta
        if 0 <= new_idx < self._options_box.count():
            self._options_box.removeWidget(card)
            self._options_box.insertWidget(new_idx, card)
            self._relabel_options()
            self._refresh_preview()

    def _relabel_options(self) -> None:
        eid = self._id.text().strip() or "event"
        for i, card in enumerate(self._option_cards()):
            card.set_label(i, eid)

    # ----- triggered-only / mtth / fire date -----
    def _on_triggered_toggle(self, checked: bool) -> None:
        # mtth is meaningless for triggered-only events.
        scheduled = getattr(self, "_fire_date_chk", None) and self._fire_date_chk.isChecked()
        self._mtth.setEnabled(not checked and not scheduled)
        self._mtth_label.setEnabled(not checked and not scheduled)
        self._refresh_preview()

    def _on_fire_date_toggle(self, checked: bool) -> None:
        # A date-scheduled event is forced is_triggered_only + fire_only_once on
        # export, so those checkboxes (and mtth) don't apply while it's on.
        self._fire_date.setEnabled(checked)
        self._triggered_only.setEnabled(not checked)
        self._fire_once.setEnabled(not checked)
        self._on_triggered_toggle(self._triggered_only.isChecked())

    # ----- preview -----
    def _refresh_preview(self) -> None:
        if not self._built:
            return
        self._relabel_options()
        try:
            event = self.result_event()
            proj = FocusForgeProject(
                countryTag=self._country_tag,
                events=[event],
                exportSettings=ExportSettings(localisationPrefix=self._loc_prefix()),
            )
            text = export_events(proj)
            lines = text.split("\n")
            # drop the leading "add_namespace = …" + blank line
            body = "\n".join(lines[2:]).strip("\n")
            self._preview.setPlainText(body)
        except Exception as exc:  # never let a preview error block editing
            self._preview.setPlainText(f"(preview unavailable: {exc})")

    # ----- result -----
    def result_event(self) -> EventData:
        items = self._event_trigger.items()
        raw = self._event_trigger.raw_lines()
        event_trigger = AvailabilityRule(items=items, rawLines=raw) if (items or raw) else None
        mtth = self._mtth.value()
        return EventData(
            id=self._id.text().strip(),
            title=self._title.text().strip(),
            description=self._desc.toPlainText().strip(),
            picture=self._picture_name.strip() or "GFX_report_event_generic_parliament",
            pictureData=self._picture_data,
            eventType=self._type.currentData() or "country_event",
            isTriggeredOnly=self._triggered_only.isChecked(),
            hidden=self._hidden.isChecked(),
            major=self._major.isChecked(),
            fireOnlyOnce=self._fire_once.isChecked(),
            meanTimeToHappen=(mtth if (mtth > 0 and not self._triggered_only.isChecked()) else None),
            fireOnDate=(self._fire_date.text().strip() if self._fire_date_chk.isChecked() else ""),
            trigger=event_trigger,
            options=[c.result_option() for c in self._option_cards()],
        )
