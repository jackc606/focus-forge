"""Stats tab: a balance overview of the tree — size, time to complete, the
political-power economy, and per-branch length. Lazy like the export panel:
recomputed only while visible, debounced."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFormLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from core.tree_stats import compute_stats

from . import theme as T
from .project_model import ProjectModel
from .widgets import hint, panel_header, section_header


def _fmt_days(days: float) -> str:
    if days >= 365:
        return f"{days:,.0f} days (~{days / 365:.1f} years)"
    return f"{days:,.0f} days"


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

        v.addWidget(section_header("Tree"))
        self._tree_form = QFormLayout()
        self._tree_form.setSpacing(T.SPACE_SM)
        v.addLayout(self._tree_form)

        v.addWidget(section_header("Political power"))
        self._pp_form = QFormLayout()
        self._pp_form.setSpacing(T.SPACE_SM)
        v.addLayout(self._pp_form)

        v.addWidget(section_header("Longest branches"))
        self._branches_box = QVBoxLayout()
        self._branches_box.setSpacing(T.SPACE_XS)
        v.addLayout(self._branches_box)
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

        self._clear(self._tree_form)
        self._row(self._tree_form, "Focuses", str(s["focuses"]))
        self._row(self._tree_form, "Branches (roots)", str(s["roots"]))
        self._row(self._tree_form, "Deepest chain", f"{s['max_depth']} focuses")
        self._row(self._tree_form, "Longest path", _fmt_days(s["longest_path_days"]))
        self._row(self._tree_form, "All focuses combined", _fmt_days(s["total_days"]))
        self._row(self._tree_form, "Either/or choices", str(s["mutex_pairs"]))
        self._row(self._tree_form, "Ideas / events",
                  f"{s['ideas']} / {s['events']}")

        self._clear(self._pp_form)
        self._row(self._pp_form, "PP granted by rewards", f"{s['pp_gained']:,.0f}")
        self._row(self._pp_form, "PP spent by rewards", f"{s['pp_spent']:,.0f}")
        self._row(self._pp_form, "Reward items", str(s["reward_items"]))
        self._row(self._pp_form, "Focuses with no reward",
                  str(s["focuses_without_rewards"]))

        self._clear(self._branches_box)
        if not s["branches"]:
            empty = QLabel("No focuses yet.")
            empty.setObjectName("muted")
            self._branches_box.addWidget(empty)
        for b in s["branches"][:8]:
            line = QLabel(f"{b['title']}  —  {b['focuses']} focuses, {_fmt_days(b['days'])}")
            line.setObjectName("muted")
            line.setWordWrap(True)
            self._branches_box.addWidget(line)
        if len(s["branches"]) > 8:
            more = QLabel(f"+{len(s['branches']) - 8} more branches")
            more.setObjectName("muted")
            self._branches_box.addWidget(more)
