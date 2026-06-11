"""Manage the project's custom events — list, create, edit, delete.

The authoring widget itself is ``EventEditorDialog``; this dialog is the browser
that lets you pick an existing event to edit (or make a new one). Scaffolding
lives in ``ListManagerDialog``.
"""
from __future__ import annotations

from .event_editor import EventEditorDialog
from .list_manager_dialog import ListManagerDialog


class EventsManagerDialog(ListManagerDialog):
    _kind = "event"
    _empty_text = "No events yet — click New… to author one."

    def __init__(self, model, parent=None) -> None:
        super().__init__(
            model,
            window_title="Events",
            header="Events",
            hint_text="Custom country/news events you've authored in this project. "
                      "Fire them from a focus reward (Country Event) or another event.",
            parent=parent,
        )

    def _items(self):
        return self._model.project.events

    def _item_label(self, event) -> str:
        opt_n = len(event.options or [])
        refs = self._model.event_reference_count(event.id)
        parts = [f"{opt_n} option{'s' if opt_n != 1 else ''}"]
        if refs:
            parts.append(f"{refs} ref{'s' if refs != 1 else ''}")
        if (event.fireOnDate or "").strip():
            parts.append(f"fires {event.fireOnDate.strip()}")
        return f"{event.title or event.id}\n{event.id}  ·  {'  ·  '.join(parts)}"

    def _edit_entity(self, existing=None):
        dlg = EventEditorDialog(self._model, event=existing, parent=self)
        return dlg.result_event() if dlg.exec() else None

    def _model_add(self, event) -> str:
        return self._model.add_event(event)

    def _model_update(self, old_id: str, event) -> str:
        return self._model.update_event(old_id, event)

    def _model_delete(self, event_id: str) -> None:
        self._model.delete_event(event_id)

    def _reference_count(self, event_id: str) -> int:
        return self._model.event_reference_count(event_id)
