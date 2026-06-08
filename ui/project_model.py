"""Single-source-of-truth project state, exposed to the UI via signals."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.exporters import export_project_files
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.types import (
    CompletionReward,
    FocusForgeProject,
    FocusNodeData,
    FocusPosition,
)
from core.validation import validate_project


_VALID_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")


class ProjectModel(QObject):
    project_changed = Signal()
    selection_changed = Signal(str)  # focus id, "" for none
    validation_changed = Signal(list)  # list[ValidationIssue]
    status_message = Signal(str)
    project_path_changed = Signal(str)  # "" for unsaved
    dirty_changed = Signal(bool)        # True when there are unsaved changes

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._project: FocusForgeProject = make_sample_project()
        self._path: Optional[Path] = None
        self._selected_id: str = ""
        self._dirty = False  # unsaved changes since last load/save

    # ----- accessors -----
    @property
    def project(self) -> FocusForgeProject:
        return self._project

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def selected_id(self) -> str:
        return self._selected_id

    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, value: bool) -> None:
        if value != self._dirty:
            self._dirty = value
            self.dirty_changed.emit(value)

    def find_focus(self, focus_id: str) -> Optional[FocusNodeData]:
        for f in self._project.focuses:
            if f.id == focus_id:
                return f
        return None

    def issues(self) -> list:
        return validate_project(self._project)

    # ----- mutation -----
    def replace_project(self, project: FocusForgeProject, path: Optional[Path] = None) -> None:
        self._project = project
        self._path = path
        self._selected_id = project.focuses[0].id if project.focuses else ""
        self._emit_all()
        self._set_dirty(False)  # a freshly loaded/created project is clean
        self.project_path_changed.emit(str(path) if path else "")

    def set_selection(self, focus_id: str) -> None:
        if focus_id == self._selected_id:
            return
        self._selected_id = focus_id or ""
        self.selection_changed.emit(self._selected_id)

    def add_prerequisite(self, target_id: str, prereq_id: str) -> str:
        """Make ``target`` depend on ``prereq`` (prereq is a prerequisite of
        target). Returns a status message. No-ops on self/dup; refuses cycles."""
        if not target_id or not prereq_id or target_id == prereq_id:
            return ""
        target = self.find_focus(target_id)
        if not target or not self.find_focus(prereq_id):
            return ""
        if prereq_id in target.prerequisites:
            return ""
        if self._depends_on(prereq_id, target_id):
            return f"Skipped: {prereq_id} → {target_id} would create a cycle."
        target.prerequisites = list(target.prerequisites) + [prereq_id]
        self._emit_all()
        return f"Linked {prereq_id} → {target_id}"

    def remove_prerequisite(self, target_id: str, prereq_id: str) -> str:
        target = self.find_focus(target_id)
        if target and prereq_id in target.prerequisites:
            target.prerequisites = [p for p in target.prerequisites if p != prereq_id]
            self._emit_all()
            return f"Removed {prereq_id} → {target_id}"
        return ""

    def remove_mutex(self, a_id: str, b_id: str) -> str:
        a = self.find_focus(a_id)
        b = self.find_focus(b_id)
        changed = False
        if a and b_id in a.mutuallyExclusive:
            a.mutuallyExclusive = [x for x in a.mutuallyExclusive if x != b_id]
            changed = True
        if b and a_id in b.mutuallyExclusive:
            b.mutuallyExclusive = [x for x in b.mutuallyExclusive if x != a_id]
            changed = True
        if changed:
            self._emit_all()
            return f"Removed mutual exclusivity {a_id} ↔ {b_id}"
        return ""

    def _depends_on(self, start_id: str, goal_id: str) -> bool:
        """Does ``start`` reach ``goal`` by following prerequisites (transitively)?"""
        seen = set()
        stack = [start_id]
        while stack:
            cur = stack.pop()
            focus = self.find_focus(cur)
            if not focus:
                continue
            for p in focus.prerequisites:
                if p == goal_id:
                    return True
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return False

    def update_focus(self, focus_id: str, **fields) -> None:
        focus = self.find_focus(focus_id)
        if not focus:
            return
        for key, value in fields.items():
            setattr(focus, key, value)
        self._emit_all()

    def update_project_meta(self, **fields) -> None:
        for key, value in fields.items():
            setattr(self._project, key, value)
        self._emit_all()

    def update_export_settings(self, **fields) -> None:
        for key, value in fields.items():
            setattr(self._project.exportSettings, key, value)
        self._emit_all()

    def add_focus(self) -> str:
        max_y = max((f.position.y for f in self._project.focuses), default=-1)
        return self.add_focus_at(0, max_y + 2)

    def _focus_id_prefix(self) -> str:
        """Country-tag prefix for new focus IDs (HOI4 convention), e.g. 'LBY'."""
        return re.sub(r"[^A-Za-z0-9]", "", (self._project.countryTag or "")).upper()

    def add_focus_at(self, grid_x: int, grid_y: int, prerequisites=None) -> str:
        """Create a new blank focus at a grid cell, optionally pre-linked.
        IDs are auto-prefixed with the country tag (e.g. LBY_new_focus_001)."""
        n = len(self._project.focuses) + 1
        prefix = self._focus_id_prefix()
        base = f"{prefix}_new_focus_{n:03d}" if prefix else f"new_focus_{n:03d}"
        new_id = self._unique_id(base)
        focus = FocusNodeData(
            id=new_id,
            title=f"New Focus {n}",
            description="",
            icon="",
            position=FocusPosition(x=int(grid_x), y=int(grid_y)),
            cost=5,
            filters=[],
            prerequisites=list(prerequisites or []),
            mutuallyExclusive=[],
            completionReward=CompletionReward(),
        )
        self._project.focuses.append(focus)
        self._selected_id = new_id
        self._emit_all()
        self.selection_changed.emit(new_id)
        return new_id

    def delete_focus(self, focus_id: str) -> None:
        self.delete_focuses([focus_id])

    def delete_focuses(self, focus_ids) -> None:
        """Delete one or more focuses in a single update, stripping every
        reference (prerequisites / mutually exclusive / completed-focus checks)."""
        present = {f.id for f in self._project.focuses}
        ids = {fid for fid in focus_ids if fid in present}
        if not ids:
            return
        self._project.focuses = [f for f in self._project.focuses if f.id not in ids]
        # Strip references
        for f in self._project.focuses:
            f.prerequisites = [p for p in f.prerequisites if p not in ids]
            f.mutuallyExclusive = [m for m in f.mutuallyExclusive if m not in ids]
            if f.available and f.available.completedFocuses:
                f.available.completedFocuses = [c for c in f.available.completedFocuses if c not in ids]
        if self._selected_id in ids:
            self._selected_id = self._project.focuses[0].id if self._project.focuses else ""
            self.selection_changed.emit(self._selected_id)
        self._emit_all()

    def rename_focus(self, old_id: str, new_id: str) -> str:
        """Rename a focus (de-duping the new id) and rewrite every reference —
        prerequisites, mutual exclusions, and availability completed-focus checks.
        Returns the final id. Shared by the inspector and the AI bridge."""
        focus = self.find_focus(old_id)
        new_id = (new_id or "").strip()
        if not focus or not new_id or new_id == old_id:
            return old_id
        new_id = self._unique_id(new_id)
        focus.id = new_id
        for other in self._project.focuses:
            other.prerequisites = [new_id if p == old_id else p for p in other.prerequisites]
            other.mutuallyExclusive = [new_id if m == old_id else m for m in other.mutuallyExclusive]
            if other.available and other.available.completedFocuses:
                other.available.completedFocuses = [new_id if c == old_id else c
                                                    for c in other.available.completedFocuses]
        if self._selected_id == old_id:
            self.set_selection(new_id)
        self._emit_all()
        return new_id

    def set_mutually_exclusive(self, a_id: str, b_id: str) -> str:
        """Make two focuses mutually exclusive (symmetric). Returns a status message."""
        a = self.find_focus(a_id)
        b = self.find_focus(b_id)
        if not a or not b or a_id == b_id:
            return ""
        changed = False
        if b_id not in a.mutuallyExclusive:
            a.mutuallyExclusive = list(a.mutuallyExclusive) + [b_id]
            changed = True
        if a_id not in b.mutuallyExclusive:
            b.mutuallyExclusive = list(b.mutuallyExclusive) + [a_id]
            changed = True
        if changed:
            self._emit_all()
            return f"Linked {a_id} ↔ {b_id}"
        return ""

    # ----- ideas (national spirits) -----
    def _unique_idea_id(self, base: str, ignore: str = "") -> str:
        existing = {i.id for i in self._project.ideas if i.id != ignore}
        if base and base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def add_idea(self, idea) -> str:
        """Append a new idea (de-duping its id) and return the final id."""
        idea.id = self._unique_idea_id(idea.id)
        self._project.ideas.append(idea)
        self._project.exportSettings.includeIdeas = True
        self._emit_all()
        return idea.id

    def update_idea(self, old_id: str, new_idea) -> str:
        """Replace the idea identified by old_id with new_idea. If the id changed,
        de-dupe it and rewrite every focus reward that referenced the old id."""
        idx = next((i for i, it in enumerate(self._project.ideas) if it.id == old_id), -1)
        if idx < 0:
            return self.add_idea(new_idea)
        if new_idea.id != old_id:
            new_idea.id = self._unique_idea_id(new_idea.id, ignore=old_id)
            self._rename_idea_references(old_id, new_idea.id)
        self._project.ideas[idx] = new_idea
        self._project.exportSettings.includeIdeas = True
        self._emit_all()
        return new_idea.id

    def delete_idea(self, idea_id: str) -> None:
        before = len(self._project.ideas)
        self._project.ideas = [i for i in self._project.ideas if i.id != idea_id]
        if len(self._project.ideas) == before:
            return
        self._emit_all()

    def idea_reference_count(self, idea_id: str) -> int:
        """How many focus reward items reference this idea (for delete warnings)."""
        return sum(1 for _f, _it, val in self._iter_idea_refs() if val == idea_id)

    def _iter_idea_refs(self):
        """Yield (focus, reward_item, value) for every idea_ref reward param."""
        from core.reward_presets import get_reward_preset
        for f in self._project.focuses:
            reward = f.completionReward
            for item in (reward.items or []) if reward else []:
                preset = get_reward_preset(item.kind)
                if not preset:
                    continue
                for p in preset.params:
                    if p.type == "idea_ref":
                        yield f, item, item.params.get(p.key)

    def _rename_idea_references(self, old_id: str, new_id: str) -> None:
        from core.reward_presets import get_reward_preset
        for f in self._project.focuses:
            reward = f.completionReward
            for item in (reward.items or []) if reward else []:
                preset = get_reward_preset(item.kind)
                if not preset:
                    continue
                for p in preset.params:
                    if p.type == "idea_ref" and item.params.get(p.key) == old_id:
                        item.params[p.key] = new_id

    # ----- events -----
    def _unique_event_id(self, base: str, ignore: str = "") -> str:
        existing = {e.id for e in self._project.events if e.id != ignore}
        if base and base not in existing:
            return base
        # event ids look like NS.<n>; bump the trailing number, else append _<n>.
        m = re.match(r"^(.*?)(\d+)$", base or "")
        if m:
            stem, n = m.group(1), int(m.group(2)) + 1
            while f"{stem}{n}" in existing:
                n += 1
            return f"{stem}{n}"
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def add_event(self, event) -> str:
        """Append a new event (de-duping its id) and return the final id."""
        event.id = self._unique_event_id(event.id)
        self._project.events.append(event)
        self._project.exportSettings.includeEvents = True
        self._emit_all()
        return event.id

    def update_event(self, old_id: str, new_event) -> str:
        """Replace the event identified by old_id. If the id changed, de-dupe it
        and rewrite every focus reward that referenced the old id."""
        idx = next((i for i, ev in enumerate(self._project.events) if ev.id == old_id), -1)
        if idx < 0:
            return self.add_event(new_event)
        if new_event.id != old_id:
            new_event.id = self._unique_event_id(new_event.id, ignore=old_id)
            self._rename_event_references(old_id, new_event.id)
        self._project.events[idx] = new_event
        self._project.exportSettings.includeEvents = True
        self._emit_all()
        return new_event.id

    def delete_event(self, event_id: str) -> None:
        before = len(self._project.events)
        self._project.events = [e for e in self._project.events if e.id != event_id]
        if len(self._project.events) == before:
            return
        self._emit_all()

    def event_reference_count(self, event_id: str) -> int:
        """How many focus reward references point at this event (delete warnings)."""
        return sum(1 for val in self._iter_event_refs() if val == event_id)

    def _iter_event_refs(self):
        """Yield every focus-reward value that references an event id — both
        ``country_event`` reward-item params (type ``event_ref``) and the
        structured ``EventReward`` entries in ``reward.events``."""
        from core.reward_presets import get_reward_preset
        for f in self._project.focuses:
            reward = f.completionReward
            if not reward:
                continue
            for ev in (reward.events or []):
                yield ev.id
            for item in (reward.items or []):
                preset = get_reward_preset(item.kind)
                if not preset:
                    continue
                for p in preset.params:
                    if p.type == "event_ref":
                        yield item.params.get(p.key)

    def _rename_event_references(self, old_id: str, new_id: str) -> None:
        from core.reward_presets import get_reward_preset
        for f in self._project.focuses:
            reward = f.completionReward
            if not reward:
                continue
            for ev in (reward.events or []):
                if ev.id == old_id:
                    ev.id = new_id
            for item in (reward.items or []):
                preset = get_reward_preset(item.kind)
                if not preset:
                    continue
                for p in preset.params:
                    if p.type == "event_ref" and item.params.get(p.key) == old_id:
                        item.params[p.key] = new_id

    def _unique_id(self, base: str) -> str:
        existing = {f.id for f in self._project.focuses}
        if base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    # ----- I/O -----
    def load_from_file(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text)
        self.replace_project(project_from_dict(data), path=path)
        self.status_message.emit(f"Opened {path}")

    def save_to_file(self, path: Path) -> None:
        text = json.dumps(project_to_dict(self._project), indent=2, ensure_ascii=False)
        path.write_bytes(text.encode("utf-8"))
        self._path = path
        self._set_dirty(False)
        self.project_path_changed.emit(str(path))
        self.status_message.emit(f"Saved {path}")

    def export_to_directory(self, directory: Path) -> int:
        files = export_project_files(self._project)
        for f in files:
            target = directory / f.relativePath
            target.parent.mkdir(parents=True, exist_ok=True)
            content = ("﻿" + f.content) if f.bom else f.content
            target.write_bytes(content.encode("utf-8"))
        self.status_message.emit(f"Exported {len(files)} files to {directory}")
        return len(files)

    # ----- change notification -----
    def notify_changed(self) -> None:
        """Public seam for UI editors that mutate ``project`` in place: re-emit
        the project/validation signals and mark the project dirty. Use this
        instead of the internal ``_emit_all`` so model internals stay private."""
        self._emit_all()

    # ----- emit helpers -----
    def _emit_all(self) -> None:
        self._set_dirty(True)
        self.project_changed.emit()
        self.validation_changed.emit(validate_project(self._project))
