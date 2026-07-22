"""Stats tab — the mission briefing: stat tiles, painted branch/reward bar
charts, and the political-power economy. Lazy like the export panel:
recomputed only while visible, debounced."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.tree_stats import compute_stats

from . import theme as T
from .project_model import ProjectModel
from .widgets import hint, mono_font, panel_header, section_header


def _fmt_days(days: float) -> str:
    if days >= 365:
        return f"{days:,.0f} days (~{days / 365:.1f} years)"
    return f"{days:,.0f} days"


# Reward-effect families, in display order. A focus counts once per family it
# touches — the chart answers "what do completions actually pay out in?"
_REWARD_FAMILIES = [
    ("Treasury", r"treasury_change"),
    ("Political power", r"add_political_power"),
    ("Buildings", r"one_random_|_construction = yes|add_building_construction|"
                  r"dockyards = yes|air_base = yes|fuel_reserve = yes|"
                  r"network_infrastructure = yes|infrastructure = yes"),
    ("Spirits / ideas", r"add_ideas|remove_ideas|add_timed_idea|swap_ideas"),
    ("Stability / war", r"add_stability|add_war_support"),
    ("Events", r"country_event|news_event"),
    ("Experience", r"army_experience|navy_experience|air_experience"),
    ("Opinions", r"change_\w+_opinion|add_opinion_modifier"),
    ("Research", r"add_tech_bonus|add_doctrine_cost_reduction"),
    ("Diplomacy / war", r"create_wargoal|puppet|annex_country|influence_percentage"),
]


def _reward_mix(project) -> list:
    counts = {label: 0 for label, _ in _REWARD_FAMILIES}
    patterns = [(label, re.compile(pat)) for label, pat in _REWARD_FAMILIES]
    for f in project.focuses:
        reward = f.completionReward
        text = "\n".join(getattr(reward, "rawLines", None) or [])
        for item in (getattr(reward, "items", None) or []):
            text += "\n" + getattr(item, "kind", "")
        for label, rx in patterns:
            if rx.search(text):
                counts[label] += 1
    return [(label, n) for label, n in counts.items() if n > 0]


class _HBarChart(QWidget):
    """Horizontal bar rows: label | track+fill | mono value. Pure theme
    colors, no chart library."""

    ROW_H = 22
    _LABEL_FRAC = 0.44

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list = []  # (label, value, value_text)
        self._max = 1

    def set_rows(self, rows) -> None:
        self._rows = [(label, value, text) for label, value, text in rows]
        self._max = max((v for _, v, _ in self._rows), default=1) or 1
        self.setFixedHeight(len(self._rows) * self.ROW_H + 2)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        label_w = int(w * self._LABEL_FRAC)
        value_w = 58
        track_x = label_w + 8
        track_w = max(20, w - track_x - value_w - 8)

        label_font = self.font()
        fm = QFontMetrics(label_font)
        vfont = mono_font(T.TEXT_MICRO)
        vfm = QFontMetrics(vfont)

        for i, (label, value, value_text) in enumerate(self._rows):
            y = i * self.ROW_H
            mid = y + self.ROW_H // 2

            p.setFont(label_font)
            p.setPen(QColor(T.TEXT_SECONDARY))
            p.drawText(QRect(0, y, label_w, self.ROW_H),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(label, Qt.ElideRight, label_w))

            track = QRect(track_x, mid - 4, track_w, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.BG_INSET))
            p.drawRoundedRect(track, 3, 3)
            fill_w = max(2, int(track_w * value / self._max))
            p.setBrush(QColor(T.ACCENT_DIM))
            p.drawRoundedRect(QRect(track_x, mid - 4, fill_w, 8), 3, 3)

            p.setFont(vfont)
            p.setPen(QColor(T.TEXT_MUTED))
            p.drawText(QRect(track_x + track_w + 6, y, value_w, self.ROW_H),
                       Qt.AlignRight | Qt.AlignVCenter,
                       vfm.elidedText(value_text, Qt.ElideRight, value_w))
        p.end()


def _stat_tile(value_label: QLabel, caption: str) -> QFrame:
    tile = QFrame()
    tile.setObjectName("statTile")
    v = QVBoxLayout(tile)
    v.setContentsMargins(T.SPACE_MD, T.SPACE_SM, T.SPACE_MD, T.SPACE_SM)
    v.setSpacing(0)
    value_label.setObjectName("statValue")
    v.addWidget(value_label)
    cap = QLabel(caption)
    cap.setObjectName("statLabel")
    v.addWidget(cap)
    return tile


class StatsPanel(QWidget):
    def __init__(self, model: ProjectModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        holder = QWidget()
        scroll.setWidget(holder)
        v = QVBoxLayout(holder)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)

        v.addWidget(panel_header("Stats"))
        v.addWidget(hint("A balance overview of your tree. Days assume the HOI4 "
                         "rule of 7 days per focus-cost point."))

        # Stat tiles — the headline numbers.
        tiles = QGridLayout()
        tiles.setSpacing(T.SPACE_SM)
        self._tile_focuses = QLabel("0")
        self._tile_days = QLabel("0")
        self._tile_branches = QLabel("0")
        self._tile_choices = QLabel("0")
        tiles.addWidget(_stat_tile(self._tile_focuses, "FOCUSES"), 0, 0)
        tiles.addWidget(_stat_tile(self._tile_days, "LONGEST PATH"), 0, 1)
        tiles.addWidget(_stat_tile(self._tile_branches, "BRANCHES"), 1, 0)
        tiles.addWidget(_stat_tile(self._tile_choices, "EITHER/OR CHOICES"), 1, 1)
        v.addLayout(tiles)

        v.addWidget(section_header("Longest branches"))
        self._branch_chart = _HBarChart()
        v.addWidget(self._branch_chart)
        self._branch_more = QLabel()
        self._branch_more.setObjectName("muted")
        v.addWidget(self._branch_more)

        v.addWidget(section_header("Reward mix"))
        v.addWidget(hint("How many focuses pay out in each effect family — a flat "
                         "profile reads repetitive in-game."))
        self._reward_chart = _HBarChart()
        v.addWidget(self._reward_chart)

        v.addWidget(section_header("Political power"))
        v.addWidget(hint("Counts structured reward items plus recognized raw-script "
                         "effects (imports, AI-bridge edits)."))
        self._pp_form = QFormLayout()
        self._pp_form.setSpacing(T.SPACE_SM)
        v.addLayout(self._pp_form)

        v.addWidget(section_header("Content"))
        self._content_form = QFormLayout()
        self._content_form.setSpacing(T.SPACE_SM)
        v.addLayout(self._content_form)
        v.addStretch(1)

        self._stale = True
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self.refresh)
        self._model.project_changed.connect(self._on_project_changed)

    def _on_project_changed(self) -> None:
        self._stale = True
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._stale:
            self.refresh()

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    @staticmethod
    def _row(form, label: str, value: str) -> None:
        lbl = QLabel(value)
        lbl.setObjectName("muted")
        form.addRow(label, lbl)

    def refresh(self) -> None:
        self._stale = False
        s = compute_stats(self._model.project)

        self._tile_focuses.setText(f"{s['focuses']:,}")
        days = s["longest_path_days"]
        self._tile_days.setText(f"{days / 365:.1f} yr" if days >= 365 else f"{days:,.0f} d")
        self._tile_branches.setText(str(s["roots"]))
        self._tile_choices.setText(str(s["mutex_pairs"]))

        branches = s["branches"][:8]
        self._branch_chart.set_rows(
            [(b["title"], b["focuses"], f"{b['focuses']} · {b['days']:,.0f}d")
             for b in branches])
        extra = len(s["branches"]) - len(branches)
        self._branch_more.setText(f"+{extra} more branches" if extra > 0 else "")
        self._branch_more.setVisible(extra > 0)

        mix = sorted(_reward_mix(self._model.project), key=lambda r: -r[1])
        self._reward_chart.set_rows([(label, n, str(n)) for label, n in mix])

        self._clear(self._pp_form)
        self._row(self._pp_form, "PP granted by rewards", f"{s['pp_gained']:,.0f}")
        self._row(self._pp_form, "PP spent by rewards", f"{s['pp_spent']:,.0f}")
        self._row(self._pp_form, "Reward items", str(s["reward_items"]))
        self._row(self._pp_form, "Focuses with no reward",
                  str(s["focuses_without_rewards"]))

        self._clear(self._content_form)
        self._row(self._content_form, "Deepest chain", f"{s['max_depth']} focuses")
        self._row(self._content_form, "All focuses combined", _fmt_days(s["total_days"]))
        self._row(self._content_form, "Ideas / events",
                  f"{s['ideas']} / {s['events']}")
