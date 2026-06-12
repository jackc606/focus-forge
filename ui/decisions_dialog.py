"""Manage the project's decisions and decision categories — list, create,
edit, delete. Authoring lives in ``decision_editor``; scaffolding in
``ListManagerDialog``.
"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from .decision_editor import DecisionCategoryEditorDialog, DecisionEditorDialog
from .list_manager_dialog import ListManagerDialog


class DecisionCategoriesManagerDialog(ListManagerDialog):
    _kind = "category"
    _ref_noun = "decision"
    _empty_text = "No custom categories yet — decisions can also use MD's existing ones."

    def __init__(self, model, parent=None) -> None:
        super().__init__(
            model,
            window_title="Decision Categories",
            header="Decision Categories",
            hint_text="Tabs in the in-game decisions panel. Your decisions can use "
                      "these or any existing Millennium Dawn category.",
            parent=parent,
        )

    def _items(self):
        return self._model.project.decisionCategories

    def _item_label(self, cat) -> str:
        n = self._model.decision_category_reference_count(cat.id)
        return f"{cat.title or cat.id}\n{cat.id}  ·  {n} decision{'s' if n != 1 else ''}"

    def _edit_entity(self, existing=None):
        dlg = DecisionCategoryEditorDialog(self._model, category=existing, parent=self)
        return dlg.result_category() if dlg.exec() else None

    def _model_add(self, cat) -> str:
        return self._model.add_decision_category(cat)

    def _model_update(self, old_id: str, cat) -> str:
        return self._model.update_decision_category(old_id, cat)

    def _model_delete(self, cat_id: str) -> None:
        self._model.delete_decision_category(cat_id)

    def _reference_count(self, cat_id: str) -> int:
        return self._model.decision_category_reference_count(cat_id)


class DecisionsManagerDialog(ListManagerDialog):
    _kind = "decision"
    _empty_text = "No decisions yet — click New… to author one."

    def __init__(self, model, parent=None) -> None:
        super().__init__(
            model,
            window_title="Decisions",
            header="Decisions",
            hint_text="Custom decisions you've authored in this project. They show "
                      "in-game under their category in the decisions panel.",
            parent=parent,
        )

    def _extra_buttons(self) -> list:
        btn = QPushButton("Categories…")
        btn.setToolTip("Manage this project's custom decision categories.")
        btn.clicked.connect(self._manage_categories)
        return [btn]

    def _manage_categories(self) -> None:
        DecisionCategoriesManagerDialog(self._model, parent=self).exec()
        self._refresh()  # category renames may have rewritten decision labels

    def _items(self):
        return self._model.project.decisions

    def _item_label(self, d) -> str:
        parts = []
        if (d.category or "").strip():
            parts.append(d.category.strip())
        if d.cost is not None:
            parts.append(f"{d.cost:g} PP")
        if d.daysRemove is not None:
            parts.append(f"{d.daysRemove}d timer")
        if d.daysMissionTimeout is not None:
            parts.append("mission")
        tail = "  ·  ".join(parts) if parts else "—"
        return f"{d.title or d.id}\n{d.id}  ·  {tail}"

    def _edit_entity(self, existing=None):
        dlg = DecisionEditorDialog(self._model, decision=existing, parent=self)
        return dlg.result_decision() if dlg.exec() else None

    def _model_add(self, decision) -> str:
        return self._model.add_decision(decision)

    def _model_update(self, old_id: str, decision) -> str:
        return self._model.update_decision(old_id, decision)

    def _model_delete(self, decision_id: str) -> None:
        self._model.delete_decision(decision_id)
