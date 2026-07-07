"""Country editor: politics/parties, custom leaders, and flags (preset + import)."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QByteArray, Qt
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
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .dds_image import load_dds_qimage, load_flag_qimage
from .no_scroll import NoScrollComboBox as QComboBox
from .no_scroll import NoScrollDoubleSpinBox as QDoubleSpinBox
from .no_scroll import NoScrollSpinBox as QSpinBox

from core.ideologies import IDEOLOGY_TREE, TOP_IDEOLOGIES, sub_ideology_groups
from core.md_parties import MD_PARTIES, MD_PARTY_SUBIDEOLOGY_BY_INDEX
from core.types import CountryData, ElectionLeaderAssignment, LeaderData, PartyData

from . import theme as T
from .chip_selector import ChipSelector
from .country_export import _qimage_from_b64
from .country_provider import country_provider
from .flag_files import default_flag, flag_files
from .icon_picker import IconPickerDialog
from .icon_provider import provider
from .trait_provider import trait_provider
from .widgets import hint, panel_header, pill, section_header

_IMG_FILTER = "Images (*.png *.tga *.jpg *.jpeg *.bmp *.dds);;All files (*)"

# Millennium Dawn party logos are 22×22 px square sprites (exported as .dds).
_PARTY_LOGO_PX = 22
# MD leader portraits are 156×210 px.
_LEADER_PORTRAIT_W, _LEADER_PORTRAIT_H = 156, 210

# In-dialog preview sizes, derived from the in-game asset ratios above.
_LOGO_PREVIEW_PX = 28                                # 22 px logo + breathing room
_PORTRAIT_PREVIEW_W, _PORTRAIT_PREVIEW_H = 34, 40    # leader portrait 156:210
_FLAG_PREVIEW_W, _FLAG_PREVIEW_H = 123, 78           # main flag 82×52 ×1.5
_FLAG_VARIANT_W, _FLAG_VARIANT_H = 62, 40            # variant flag 82×52 ×0.75


def _to_b64_png(img: QImage) -> str:
    img = img.convertToFormat(QImage.Format_ARGB32)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(ba)).decode("ascii")


def _scaled_b64_png(img: QImage, w: int, h: int) -> str:
    """Scale an imported image to the exact in-game size, then encode as PNG b64
    (matches how flags are scaled on export — exact target, smooth)."""
    return _to_b64_png(img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))


def _ideology_combo(current: str) -> QComboBox:
    cb = QComboBox()
    for top, subs in sub_ideology_groups():
        cb.addItem(f"— {top} —", None)
        cb.model().item(cb.count() - 1).setEnabled(False)
        for s in subs:
            cb.addItem(f"  {s}", s)
    idx = cb.findData(current)
    if idx >= 0:
        cb.setCurrentIndex(idx)
    return cb


# ---------------------------------------------------------------------------
class _PartyRow(QFrame):
    def __init__(self, party: PartyData, on_delete, tag: str = "") -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._tag = (tag or "").strip().upper()
        self._logoRef = party.logoRef
        self._logoData = party.logoData
        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_SM, T.SPACE_XS, T.SPACE_SM, T.SPACE_XS)
        v.setSpacing(T.SPACE_SM)

        top = QHBoxLayout()
        top.setSpacing(T.SPACE_SM)
        self.ideo = QComboBox()
        self.ideo.addItems(TOP_IDEOLOGIES)
        if party.ideology:
            self.ideo.setCurrentText(party.ideology)
        self.ideo.setToolTip(
            "Which of HOI4's fixed ideology slots this party fills. Every country "
            "already has one party per ideology, so this RENAMES that slot's party "
            "(and can re-logo it) — it does not add a brand-new party. Use one entry "
            "per ideology; two with the same ideology collide.")
        self.ideo.currentTextChanged.connect(self._on_top_changed)
        self.name = QLineEdit(party.name)
        self.name.setPlaceholderText("name")
        self.name.setToolTip(
            "Short display name for this ideology's party, shown in-game (e.g. the "
            "politics screen). Replaces the existing party name for this country.")
        self.long = QLineEdit(party.longName)
        self.long.setPlaceholderText("long name")
        self.long.setToolTip(
            "Full/formal name (e.g. \"People's Republic of …\"). Falls back to the "
            "short name if left blank.")
        x = QPushButton("×")
        x.setObjectName("deleteButton")
        x.setToolTip("Remove")
        x.setFixedWidth(T.ICON_BUTTON)
        x.clicked.connect(lambda: on_delete(self))
        top.addWidget(self.ideo)
        top.addWidget(self.name, 1)
        top.addWidget(self.long, 1)
        top.addWidget(x)
        v.addLayout(top)

        # Sub-ideology + party logo (preset from MD or custom import).
        bot = QHBoxLayout()
        bot.setSpacing(T.SPACE_SM)
        self.sub = QComboBox()
        self.sub.setToolTip("MD sub-ideology this party represents — required to "
                            "assign it a logo or a description.")
        self._populate_subs(self.ideo.currentText(), party.subIdeology)
        bot.addWidget(self.sub, 1)
        self._logo_prev = QLabel()
        self._logo_prev.setObjectName("iconPreview")
        self._logo_prev.setFixedSize(_LOGO_PREVIEW_PX, _LOGO_PREVIEW_PX)
        self._logo_prev.setAlignment(Qt.AlignCenter)
        bot.addWidget(self._logo_prev)
        pick = QPushButton("Logo…")
        pick.setToolTip("Choose a Millennium Dawn party logo for this country.")
        pick.clicked.connect(self._choose_logo)
        imp = QPushButton("Import…")
        imp.setToolTip(
            f"Import a custom party logo. MD party logos are {_PARTY_LOGO_PX}×"
            f"{_PARTY_LOGO_PX} px square, exported as .dds (.png/.tga/.dds in).")
        imp.clicked.connect(self._import_logo)
        clr = QPushButton("×")
        clr.setObjectName("deleteButton")
        clr.setToolTip("Clear logo")
        clr.setFixedWidth(T.ICON_BUTTON)
        clr.clicked.connect(self._clear_logo)
        bot.addWidget(pick)
        bot.addWidget(imp)
        bot.addWidget(clr)
        v.addLayout(bot)

        # MD party description (<TAG>.<sub>_desc) — shown in the politics screen.
        self.desc = QLineEdit(party.description)
        self.desc.setPlaceholderText("party description (shown in the politics screen)")
        self.desc.setToolTip(
            "Description shown for this party in the in-game politics screen "
            "(MD's <TAG>.<sub-ideology>_desc). Needs a sub-ideology set, like the "
            "logo. Leave blank to keep MD's existing description.")
        v.addWidget(self.desc)
        self._refresh_logo()

    def _on_top_changed(self, top: str) -> None:
        self._populate_subs(top, "")

    def _populate_subs(self, top: str, current: str) -> None:
        self.sub.blockSignals(True)
        self.sub.clear()
        self.sub.addItem("(none)", "")
        for s in IDEOLOGY_TREE.get(top, []):
            self.sub.addItem(s, s)
        idx = self.sub.findData(current)
        if idx >= 0:
            self.sub.setCurrentIndex(idx)
        self.sub.blockSignals(False)

    def _refresh_logo(self) -> None:
        pm = None
        if self._logoData:
            img = _qimage_from_b64(self._logoData)
            pm = QPixmap.fromImage(img) if img else None
        elif self._logoRef:
            pm = provider().pixmap(self._logoRef)
        if pm is not None and not pm.isNull():
            self._logo_prev.setPixmap(
                pm.scaled(_LOGO_PREVIEW_PX, _LOGO_PREVIEW_PX,
                          Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._logo_prev.clear()

    def _choose_logo(self) -> None:
        logos = provider().party_logos(self._tag)
        if not logos:
            QMessageBox.information(
                self, "No party logos",
                f"No Millennium Dawn party logos found for {self._tag or 'this country'}.\n"
                "Use Import… to add a custom logo, or add the MD folder as an icon "
                "source in Settings.")
            return
        dlg = IconPickerDialog(current=self._logoRef, parent=self, sprites=logos,
                               title=f"Choose Party Logo — {self._tag}",
                               loader=load_dds_qimage)
        if dlg.exec() and dlg.selected_name():
            self._logoRef = dlg.selected_name()  # GFX_<TAG>_… party-icon sprite
            self._logoData = ""
            self._refresh_logo()

    def _import_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import party logo — {_PARTY_LOGO_PX}×{_PARTY_LOGO_PX} px square "
            f"(.png/.tga/.dds)",
            "", _IMG_FILTER)
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Import failed",
                                "Couldn't read that image — use a .png, .tga, or .dds.")
            return
        # Auto-scale to the canonical MD party-logo size (22×22) so the export is
        # always the correct dimensions.
        self._logoData = _scaled_b64_png(img, _PARTY_LOGO_PX, _PARTY_LOGO_PX)
        self._logoRef = ""
        self._refresh_logo()

    def _clear_logo(self) -> None:
        self._logoRef = ""
        self._logoData = ""
        self._refresh_logo()

    def value(self) -> PartyData:
        return PartyData(ideology=self.ideo.currentText(),
                         name=self.name.text().strip(),
                         longName=self.long.text().strip(),
                         subIdeology=self.sub.currentData() or "",
                         logoRef=self._logoRef,
                         logoData=self._logoData,
                         description=self.desc.text().strip())


def _is_portrait_path(ref: str) -> bool:
    return "gfx/leaders" in (ref or "").replace("\\", "/").lower()


class _LeaderRow(QFrame):
    def __init__(self, leader: LeaderData, on_delete, tag: str = "") -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._tag = (tag or "").strip().upper()
        self._pictureRef = leader.pictureRef
        self._pictureData = leader.pictureData
        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_SM, T.SPACE_XS, T.SPACE_SM, T.SPACE_XS)
        v.setSpacing(T.SPACE_SM)

        top = QHBoxLayout()
        self.name = QLineEdit(leader.name)
        self.name.setPlaceholderText("Leader name")
        top.addWidget(self.name, 1)
        x = QPushButton("×")
        x.setObjectName("deleteButton")
        x.setToolTip("Remove")
        x.setFixedWidth(T.ICON_BUTTON)
        x.clicked.connect(lambda: on_delete(self))
        top.addWidget(x)
        v.addLayout(top)

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        self.ideo = _ideology_combo(leader.ideology)
        form.addRow("Ideology", self.ideo)
        self.traits = ChipSelector(placeholder="search traits…")
        self.traits.set_grouped_suggestions(trait_provider().trait_groups(self._tag),
                                            trait_provider().trait_tooltips())
        self.traits.set_tokens(leader.traits)
        form.addRow("Traits", self.traits)
        self.desc = QLineEdit(leader.description)
        self.desc.setPlaceholderText("Shown in the leader's in-game tooltip (optional)")
        form.addRow("Description", self.desc)
        v.addLayout(form)

        prow = QHBoxLayout()
        prow.setSpacing(T.SPACE_SM)
        self._preview = QLabel()
        self._preview.setObjectName("iconPreview")
        self._preview.setFixedSize(_PORTRAIT_PREVIEW_W, _PORTRAIT_PREVIEW_H)
        self._preview.setAlignment(Qt.AlignCenter)
        prow.addWidget(self._preview)
        self._pic_label = QLabel()
        self._pic_label.setObjectName("muted")
        prow.addWidget(self._pic_label, 1)
        pick = QPushButton("Choose…")
        pick.clicked.connect(self._choose_portrait)
        imp = QPushButton("Import…")
        imp.setToolTip("Import a custom portrait. MD leader portraits are 156×210 px "
                       "(.dds or .png).")
        imp.clicked.connect(self._import_portrait)
        prow.addWidget(pick)
        prow.addWidget(imp)
        v.addWidget(QLabel("Portrait"))
        pw = QWidget()
        pw.setLayout(prow)
        v.addWidget(pw)
        self._refresh_portrait()

    def _refresh_portrait(self) -> None:
        if self._pictureData:
            self._pic_label.setText("(custom portrait)")
            img = _qimage_from_b64(self._pictureData)
            pm = QPixmap.fromImage(img) if img else None
        elif _is_portrait_path(self._pictureRef):
            self._pic_label.setText(self._pictureRef.rsplit("/", 1)[-1])
            pm = provider().portrait_pixmap(self._pictureRef)
        else:
            self._pic_label.setText(self._pictureRef or "(no portrait)")
            pm = provider().pixmap(self._pictureRef) if self._pictureRef else None
        if pm is not None and not pm.isNull():
            self._preview.setPixmap(pm.scaled(_PORTRAIT_PREVIEW_W, _PORTRAIT_PREVIEW_H,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._preview.clear()

    def _choose_portrait(self) -> None:
        ports = provider().leader_portraits(self._tag)
        if not ports:
            QMessageBox.information(
                self, "No portraits",
                f"No Millennium Dawn leader portraits found for {self._tag or 'this country'}.\n"
                "Use Import… to add a custom portrait, or add the MD folder as an icon "
                "source in Settings.")
            return
        dlg = IconPickerDialog(current=self._pictureRef, parent=self, sprites=ports,
                               title=f"Choose Portrait — {self._tag}",
                               loader=load_dds_qimage)
        if dlg.exec() and dlg.selected_name():
            self._pictureRef = dlg.selected_name()  # gfx/leaders/<TAG>/<file>.dds
            self._pictureData = ""
            self._refresh_portrait()

    def _import_portrait(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import portrait — {_LEADER_PORTRAIT_W}×{_LEADER_PORTRAIT_H} px "
            f"(.png/.tga/.dds)",
            "", _IMG_FILTER)
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Import failed",
                                "Couldn't read that image — use a .png, .tga, or .dds.")
            return
        # Auto-scale to the canonical MD portrait size (156×210).
        self._pictureData = _scaled_b64_png(img, _LEADER_PORTRAIT_W, _LEADER_PORTRAIT_H)
        self._pictureRef = ""
        self._refresh_portrait()

    def value(self) -> LeaderData:
        return LeaderData(
            name=self.name.text().strip(),
            ideology=self.ideo.currentData() or "",
            traits=self.traits.tokens(),
            pictureRef=self._pictureRef,
            pictureData=self._pictureData,
            description=self.desc.text().strip(),
        )


class _ElectionLeaderRow(QFrame):
    def __init__(self, assignment: ElectionLeaderAssignment, on_delete, tag: str = "") -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._last_party_ideology = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_SM, T.SPACE_XS, T.SPACE_SM, T.SPACE_XS)
        v.setSpacing(T.SPACE_SM)

        top = QHBoxLayout()
        top.setSpacing(T.SPACE_SM)
        self.party = QComboBox()
        for idx, label in MD_PARTIES:
            self.party.addItem(f"{idx}: {label}", idx)
        try:
            current_party = int(assignment.partyIndex)
        except (TypeError, ValueError):
            current_party = 14
        idx = self.party.findData(current_party)
        if idx >= 0:
            self.party.setCurrentIndex(idx)
        self.party.setToolTip(
            "Millennium Dawn's global party index. When this party is ruling on or "
            "after the date, the exported hidden event assigns this leader.")
        self.date = QLineEdit(assignment.startDate)
        self.date.setPlaceholderText("2021.1.20")
        self.date.setToolTip("First HOI4 date this leader can be assigned (year.month.day).")
        top.addWidget(self.party, 1)
        top.addWidget(self.date)
        v.addLayout(top)

        leader = assignment.leader or LeaderData()
        party_ideology = self._party_ideology()
        if not leader.ideology and party_ideology:
            leader = LeaderData(name=leader.name, ideology=party_ideology,
                                traits=list(leader.traits or []),
                                pictureRef=leader.pictureRef,
                                pictureData=leader.pictureData,
                                description=leader.description)
        self._last_party_ideology = party_ideology
        self._leader = _LeaderRow(leader, lambda _row: on_delete(self), tag)
        v.addWidget(self._leader)
        self.party.currentIndexChanged.connect(self._on_party_changed)

    def _party_ideology(self) -> str:
        data = self.party.currentData()
        party_index = 14 if data is None else int(data)
        return MD_PARTY_SUBIDEOLOGY_BY_INDEX.get(party_index, "")

    def _on_party_changed(self) -> None:
        new_ideology = self._party_ideology()
        current = self._leader.ideo.currentData() or ""
        if (not current) or current == self._last_party_ideology:
            idx = self._leader.ideo.findData(new_ideology)
            if idx >= 0:
                self._leader.ideo.setCurrentIndex(idx)
        self._last_party_ideology = new_ideology

    def value(self) -> ElectionLeaderAssignment:
        data = self.party.currentData()
        party_index = 14 if data is None else int(data)
        return ElectionLeaderAssignment(
            partyIndex=party_index,
            startDate=self.date.text().strip(),
            leader=self._leader.value(),
        )


# ---------------------------------------------------------------------------
class CountryEditorDialog(QDialog):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle(f"Country — {model.project.countryTag or '?'}")
        self.resize(720, 680)
        self._country = model.project.country or CountryData()
        self._flag_main = self._country.flagMain
        self._flag_variants = dict(self._country.flagVariants or {})

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header(f"Country setup — {model.project.countryTag or '?'}"))

        tabs = QTabWidget()
        tabs.addTab(self._politics_tab(), "Politics")
        tabs.addTab(self._leaders_tab(), "Leaders")
        tabs.addTab(self._flags_tab(), "Flags")
        v.addWidget(tabs, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save Country")
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # ----- Politics -----
    def _politics_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(T.SPACE_MD)

        # MD starting politics for this country — used to seed empty fields and
        # for the "Load MD starting values" button.
        tag = self._model.project.countryTag
        self._md_politics = country_provider().starting_politics(tag)
        # Existing project data wins; only a fresh/blank country auto-fills from MD.
        if not self._country.popularities and self._md_politics:
            seed = self._md_politics
            seed_pops = seed["popularities"]
            seed_ruling = seed["rulingParty"] or "neutrality"
            seed_last, seed_freq, seed_elec = (seed["lastElection"],
                                               seed["electionFrequency"],
                                               seed["electionsAllowed"])
        else:
            seed_pops = self._country.popularities
            seed_ruling = self._country.rulingParty or "neutrality"
            seed_last, seed_freq, seed_elec = (self._country.lastElection,
                                               self._country.electionFrequency,
                                               self._country.electionsAllowed)

        head = QHBoxLayout()
        head.addWidget(section_header("Popularities (%)"))
        head.addStretch(1)
        self._total_label = QLabel()
        self._total_label.setObjectName("muted")
        head.addWidget(self._total_label)
        v.addLayout(head)
        if self._md_politics:
            v.addWidget(hint(f"Pre-filled with {tag}'s Millennium Dawn starting "
                             "popularities — adjust as you like."))
        else:
            v.addWidget(hint(f"No Millennium Dawn starting politics found for {tag} "
                             "(add its mod folder as an icon source, or set values manually)."))

        form = QFormLayout()
        self._pop = {}
        self._pop_pill = {}
        for ideo in TOP_IDEOLOGIES:
            sb = QDoubleSpinBox()
            sb.setRange(0, 100)
            sb.setDecimals(1)
            sb.setSingleStep(1.0)
            sb.setValue(float(seed_pops.get(ideo, 0)))
            sb.valueChanged.connect(lambda *_: self._update_total())
            self._pop[ideo] = sb
            badge = pill("in power", "ok")
            badge.setVisible(False)
            self._pop_pill[ideo] = badge
            field = QWidget()
            fl = QHBoxLayout(field)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(T.SPACE_SM)
            fl.addWidget(sb, 1)
            fl.addWidget(badge)
            form.addRow(ideo, field)
        v.addLayout(form)

        reset = QPushButton("Load MD starting values")
        reset.clicked.connect(self._load_md_values)
        reset.setEnabled(bool(self._md_politics))
        v.addWidget(reset)

        v.addWidget(section_header("Politics"))
        form2 = QFormLayout()
        self._ruling = QComboBox()
        self._ruling.addItems(TOP_IDEOLOGIES)
        self._ruling.setCurrentText(seed_ruling)
        self._ruling.currentTextChanged.connect(lambda *_: self._update_in_power())
        form2.addRow("Ruling party", self._ruling)
        self._last_election = QLineEdit(seed_last)
        self._last_election.setPlaceholderText("2000.1.1")
        form2.addRow("Last election", self._last_election)
        self._freq = QSpinBox()
        self._freq.setRange(0, 600)
        self._freq.setValue(seed_freq)
        form2.addRow("Election frequency (months)", self._freq)
        self._elections = QCheckBox("Elections allowed")
        self._elections.setChecked(seed_elec)
        form2.addRow(self._elections)
        v.addLayout(form2)

        self._update_in_power()
        self._update_total()

        # This country's existing MD parties (for auto-seeding + the Load button).
        self._md_parties = country_provider().parties(tag)

        v.addWidget(section_header("Named parties"))
        v.addWidget(hint("A country runs several parties, one per MD sub-ideology. These "
                         "edit that country's existing parties — name, logo and the "
                         "politics-screen description. Use “Load MD parties” to pull in "
                         "everything the base mod already defines, then tweak."))
        self._party_warn = QLabel()
        self._party_warn.setWordWrap(True)
        self._party_warn.setObjectName("warningText")
        self._party_warn.setVisible(False)
        v.addWidget(self._party_warn)
        self._parties_box = QVBoxLayout()
        self._parties_box.setSpacing(T.SPACE_XS)
        v.addLayout(self._parties_box)
        btn_row = QHBoxLayout()
        add = QPushButton("+ Add party")
        add.setToolTip(
            "Add a party for one MD sub-ideology (its name, logo and description). "
            "Pick the sub-ideology on the new row — each party must use a distinct one.")
        add.clicked.connect(lambda: self._add_party(PartyData(ideology="democratic")))
        load = QPushButton("Load MD parties")
        load.setEnabled(bool(self._md_parties))
        load.setToolTip(
            f"Replace the list with {tag or 'this country'}'s existing Millennium Dawn "
            f"parties (name, logo, description) so you can edit what's already in-game."
            if self._md_parties else
            "No Millennium Dawn parties found for this country (add its mod folder as an "
            "icon source in Settings).")
        load.clicked.connect(self._load_md_parties)
        btn_row.addWidget(add)
        btn_row.addWidget(load)
        btn_row.addStretch(1)
        v.addLayout(btn_row)
        v.addStretch(1)
        # Project data wins; a fresh country auto-seeds from the base mod's parties.
        seed_parties = self._country.parties or self._md_party_data()
        for p in seed_parties:
            self._add_party(p)
        self._check_party_collisions()
        return self._scroll(w)

    def _md_party_data(self) -> list:
        """This country's MD parties as PartyData (from the cached loc import)."""
        return [PartyData(ideology=d["ideology"], name=d["name"], longName=d["longName"],
                          subIdeology=d["subIdeology"], logoRef=d["logoRef"],
                          description=d["description"])
                for d in (self._md_parties or [])]

    def _load_md_parties(self) -> None:
        if not self._md_parties:
            return
        existing = [r for r in self._rows(self._parties_box) if isinstance(r, _PartyRow)]
        if existing:
            ans = QMessageBox.question(
                self, "Load MD parties",
                f"Replace the current {len(existing)} party row(s) with "
                f"{len(self._md_parties)} Millennium Dawn parties for "
                f"{self._model.project.countryTag}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        for r in existing:
            r.setParent(None)
            r.deleteLater()
        for p in self._md_party_data():
            self._add_party(p)
        self._check_party_collisions()

    def _update_in_power(self) -> None:
        """Badge the popularity row of the ruling party as 'in power'."""
        ruling = self._ruling.currentText()
        for ideo, badge in self._pop_pill.items():
            badge.setVisible(ideo == ruling)

    def _update_total(self) -> None:
        total = sum(sb.value() for sb in self._pop.values())
        self._total_label.setText(f"Total: {total:g}%")

    def _load_md_values(self) -> None:
        """Reset the Politics fields to this country's MD starting values."""
        md = self._md_politics
        if not md:
            self._model.status_message.emit(
                f"No MD starting politics for {self._model.project.countryTag}.")
            return
        for ideo, sb in self._pop.items():
            sb.setValue(float(md["popularities"].get(ideo, 0)))
        self._ruling.setCurrentText(md["rulingParty"] or "neutrality")
        self._last_election.setText(md["lastElection"])
        self._freq.setValue(md["electionFrequency"])
        self._elections.setChecked(md["electionsAllowed"])
        self._update_in_power()
        self._update_total()

    def _add_party(self, party: PartyData) -> None:
        row = _PartyRow(party, self._del_row, self._model.project.countryTag)
        # Re-check for ideology collisions whenever a row's ideology changes.
        row.ideo.currentTextChanged.connect(lambda *_: self._check_party_collisions())
        self._parties_box.addWidget(row)
        self._check_party_collisions()

    def _party_collisions(self) -> list:
        """Labels of party slots used by more than one row — these overwrite each
        other on export. MD keys parties on the sub-ideology (a country can run
        several under one top ideology), so collisions are per sub-ideology, or per
        top ideology for rows with no sub-ideology set."""
        seen_sub, seen_top, dupes = set(), set(), []
        for r in self._rows(self._parties_box):
            if not isinstance(r, _PartyRow):
                continue
            sub = r.sub.currentData() or ""
            if sub:
                if sub in seen_sub and sub not in dupes:
                    dupes.append(sub)
                seen_sub.add(sub)
            else:
                top = r.ideo.currentText()
                label = f"{top} (no sub-ideology)"
                if top in seen_top and label not in dupes:
                    dupes.append(label)
                seen_top.add(top)
        return dupes

    def _check_party_collisions(self) -> None:
        dupes = self._party_collisions()
        if dupes:
            self._party_warn.setText(
                "⚠ More than one party shares the same slot (" + ", ".join(dupes) + "). "
                "MD keys each party on its sub-ideology, so these overwrite each other on "
                "export — only the last is kept. Give each party a distinct sub-ideology.")
            self._party_warn.setVisible(True)
        else:
            self._party_warn.setVisible(False)

    # ----- Leaders -----
    def _leaders_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(section_header("Static leaders"))
        v.addWidget(hint("Custom country leaders → create_country_leader in the history file. "
                         "Choose… picks an MD portrait; Import… adds your own (156×210 px .dds/.png)."))
        self._leaders_box = QVBoxLayout()
        self._leaders_box.setSpacing(T.SPACE_SM)
        v.addLayout(self._leaders_box)
        add = QPushButton("+ Add leader")
        add.clicked.connect(lambda: self._add_leader(LeaderData(ideology="Neutral_conservatism")))
        v.addWidget(add)

        v.addWidget(section_header("Election leader timeline"))
        v.addWidget(hint("Assign a leader to an MD party starting on a date. On export, "
                         "Focus Forge writes hidden country events that check the ruling "
                         "party index and create the newest matching leader."))
        self._election_leaders_box = QVBoxLayout()
        self._election_leaders_box.setSpacing(T.SPACE_SM)
        v.addLayout(self._election_leaders_box)
        add_election = QPushButton("+ Add election leader")
        add_election.clicked.connect(lambda: self._add_election_leader(
            ElectionLeaderAssignment(
                partyIndex=14,
                startDate=self._last_election.text().strip() or "2000.1.1",
                leader=LeaderData(ideology="Neutral_conservatism"),
            )))
        v.addWidget(add_election)
        v.addStretch(1)
        for le in self._country.leaders:
            self._add_leader(le)
        for assignment in getattr(self._country, "electionLeaders", None) or []:
            self._add_election_leader(assignment)
        return self._scroll(w)

    def _add_leader(self, leader: LeaderData) -> None:
        self._leaders_box.addWidget(
            _LeaderRow(leader, self._del_row, self._model.project.countryTag))

    def _add_election_leader(self, assignment: ElectionLeaderAssignment) -> None:
        self._election_leaders_box.addWidget(
            _ElectionLeaderRow(assignment, self._del_row, self._model.project.countryTag))

    # ----- Flags -----
    def _flags_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(T.SPACE_MD)
        # MD's current flag for this country (shown until a custom flag is set).
        tag = self._model.project.countryTag
        md_pol = country_provider().starting_politics(tag)
        ruling = ((md_pol or {}).get("rulingParty")
                  or self._country.rulingParty or "neutrality")
        dfp = default_flag(provider().roots(), tag, ruling)
        self._default_flag_img = load_flag_qimage(dfp) if dfp else None

        v.addWidget(section_header("Main flag"))
        v.addWidget(hint("Custom flags must be 82×52 px .tga in-game; import a "
                         ".png/.tga/.dds and it's auto-scaled + converted to .tga "
                         "(large/medium/small) on export. Leave unset to keep MD's flag."))
        self._flag_preview = QLabel()
        self._flag_preview.setFixedSize(_FLAG_PREVIEW_W, _FLAG_PREVIEW_H)
        self._flag_preview.setObjectName("iconPreview")
        self._flag_preview.setAlignment(Qt.AlignCenter)
        v.addWidget(self._flag_preview)
        self._flag_status = QLabel()
        self._flag_status.setObjectName("muted")
        v.addWidget(self._flag_status)
        row = QHBoxLayout()
        bp = QPushButton("Choose preset flag…")
        bp.clicked.connect(lambda: self._set_main(self._pick_preset_flag()))
        bi = QPushButton("Import custom…")
        bi.setToolTip("Import your own flag — 82×52 px (.tga/.png/.dds). It's "
                      "auto-scaled and exported as .tga.")
        bi.clicked.connect(lambda: self._set_main(self._import_image()))
        bc = QPushButton("Clear")
        bc.clicked.connect(lambda: self._set_main(""))
        row.addWidget(bp)
        row.addWidget(bi)
        row.addWidget(bc)
        row.addStretch(1)
        v.addLayout(row)

        v.addWidget(section_header("Government variants (optional)"))
        self._variant_previews = {}
        for ideo in TOP_IDEOLOGIES:
            vr = QHBoxLayout()
            lbl = QLabel(ideo)
            lbl.setFixedWidth(90)
            prev = QLabel()
            prev.setObjectName("iconPreview")
            prev.setFixedSize(_FLAG_VARIANT_W, _FLAG_VARIANT_H)
            self._variant_previews[ideo] = prev
            choose = QPushButton("Choose…")
            choose.clicked.connect(lambda _c=False, i=ideo: self._set_variant(i, self._pick_preset_flag()))
            imp = QPushButton("Import…")
            imp.clicked.connect(lambda _c=False, i=ideo: self._set_variant(i, self._import_image()))
            clr = QPushButton("Clear")
            clr.clicked.connect(lambda _c=False, i=ideo: self._set_variant(i, ""))
            vr.addWidget(lbl)
            vr.addWidget(prev)
            vr.addWidget(choose)
            vr.addWidget(imp)
            vr.addWidget(clr)
            vr.addStretch(1)
            v.addLayout(vr)
        v.addStretch(1)
        self._refresh_flags()
        return self._scroll(w)

    def _pick_preset_flag(self):
        files = flag_files(provider().roots())
        by_name = dict(files)
        dlg = IconPickerDialog(parent=self, sprites=files, title="Choose Flag",
                               loader=load_flag_qimage)
        if dlg.exec() and dlg.selected_name():
            path = by_name.get(dlg.selected_name())
            if path:
                img = load_flag_qimage(path)
                if not img.isNull():
                    return _to_b64_png(img.scaled(82, 52, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        return None

    def _import_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import flag", "", _IMG_FILTER)
        if not path:
            return None
        img = load_flag_qimage(path)
        if img.isNull():
            return None
        return _to_b64_png(img.scaled(82, 52, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def _set_main(self, b64) -> None:
        if b64 is None:
            return
        self._flag_main = b64
        self._refresh_flags()

    def _set_variant(self, ideo, b64) -> None:
        if b64 is None:
            return
        if b64:
            self._flag_variants[ideo] = b64
        else:
            self._flag_variants.pop(ideo, None)
        self._refresh_flags()

    def _refresh_flags(self) -> None:
        tag = self._model.project.countryTag or "this country"
        if self._flag_main:
            self._set_preview(self._flag_preview, self._flag_main)
            self._flag_status.setText("Custom flag — will be exported.")
        elif self._default_flag_img is not None and not self._default_flag_img.isNull():
            self._flag_preview.setPixmap(QPixmap.fromImage(self._default_flag_img).scaled(
                self._flag_preview.width(), self._flag_preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._flag_status.setText(f"MD default flag for {tag} (not exported — the "
                                      "game keeps it). Choose/Import to override.")
        else:
            self._flag_preview.clear()
            self._flag_status.setText("No MD flag found for this tag.")
        for ideo, prev in self._variant_previews.items():
            self._set_preview(prev, self._flag_variants.get(ideo, ""))

    @staticmethod
    def _set_preview(label: QLabel, b64: str) -> None:
        img = _qimage_from_b64(b64) if b64 else None
        if img is not None and not img.isNull():
            label.setPixmap(QPixmap.fromImage(img).scaled(
                label.width(), label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            label.clear()

    # ----- shared -----
    def _scroll(self, w: QWidget) -> QScrollArea:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(w)
        return sc

    def _del_row(self, row) -> None:
        was_party = isinstance(row, _PartyRow)
        row.setParent(None)
        row.deleteLater()
        if was_party:
            self._check_party_collisions()

    def _rows(self, box):
        for i in range(box.count()):
            item = box.itemAt(i)
            w = item.widget() if item else None
            if w is not None:
                yield w

    def _accept(self) -> None:
        dupes = self._party_collisions()
        if dupes:
            ans = QMessageBox.warning(
                self, "Party slot collision",
                "More than one party shares the same slot (" + ", ".join(dupes) + ").\n\n"
                "MD keys each party on its sub-ideology, so on export only the last party "
                "for each slot is written — the others are dropped.\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        c = CountryData()
        c.popularities = {ideo: sb.value() for ideo, sb in self._pop.items() if sb.value()}
        c.rulingParty = self._ruling.currentText()
        c.lastElection = self._last_election.text().strip()
        c.electionFrequency = self._freq.value()
        c.electionsAllowed = self._elections.isChecked()
        c.parties = [r.value() for r in self._rows(self._parties_box) if isinstance(r, _PartyRow)]
        c.leaders = [r.value() for r in self._rows(self._leaders_box) if isinstance(r, _LeaderRow)]
        c.electionLeaders = [r.value() for r in self._rows(self._election_leaders_box)
                             if isinstance(r, _ElectionLeaderRow)]
        c.flagMain = self._flag_main
        c.flagVariants = dict(self._flag_variants)
        self._model.project.country = c
        self._model.project.exportSettings.includeCountry = True
        self._model.notify_changed()
        self._model.status_message.emit("Country data saved.")
        self.accept()
