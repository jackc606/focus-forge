"""Manage the project's custom ideas / national spirits — list, create, edit, delete.

The authoring widget itself is ``IdeaEditorDialog``; this dialog is the browser
that lets you pick an existing idea to edit (or make a new one). Scaffolding
lives in ``ListManagerDialog``.
"""
from __future__ import annotations

from .idea_editor import IdeaEditorDialog
from .list_manager_dialog import ListManagerDialog


def _modifier_count(idea) -> int:
    return sum(1 for ln in (idea.modifierRawLines or [])
              if ln.strip() and not ln.strip().startswith("modifier")
              and ln.strip() not in ("{", "}"))


class IdeasManagerDialog(ListManagerDialog):
    _kind = "idea"
    _empty_text = "No ideas yet — click New… to author one."

    def __init__(self, model, parent=None) -> None:
        super().__init__(
            model,
            window_title="Ideas",
            header="Ideas / National Spirits",
            hint_text="Custom ideas you've authored in this project. Select one "
                      "to edit, or create a new one.",
            parent=parent,
        )

    def _items(self):
        return self._model.project.ideas

    def _item_label(self, idea) -> str:
        n = _modifier_count(idea)
        return f"{idea.title or idea.id}\n{idea.id}  ·  {n} modifier{'s' if n != 1 else ''}"

    def _edit_entity(self, existing=None):
        dlg = IdeaEditorDialog(self._model, idea=existing, parent=self)
        return dlg.result_idea() if dlg.exec() else None

    def _model_add(self, idea) -> str:
        return self._model.add_idea(idea)

    def _model_update(self, old_id: str, idea) -> str:
        return self._model.update_idea(old_id, idea)

    def _model_delete(self, idea_id: str) -> None:
        self._model.delete_idea(idea_id)

    def _reference_count(self, idea_id: str) -> int:
        return self._model.idea_reference_count(idea_id)
