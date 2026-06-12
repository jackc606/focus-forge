"""Single-source-of-truth project state, exposed to the UI via signals."""
from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from core.exporters import export_project_files
from core.file_io import atomic_write_bytes
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

_UNDO_LIMIT = 50          # snapshots kept; a full project dict is cheap (KBs)
_UNDO_COALESCE_S = 0.8    # mutations closer together than this = one gesture


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
        self._focus_index: dict = {f.id: f for f in self._project.focuses}
        # Snapshot-based undo: _current_state mirrors the project as a plain
        # dict; every change pushes the PREVIOUS state (per gesture — rapid
        # keystroke bursts coalesce into one step).
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._current_state: dict = project_to_dict(self._project)
        self._state_stale = False      # _current_state lags the project mid-burst
        self._undo_skip = False        # suppress capture during undo/redo/load
        self._last_mutation = 0.0
        self._undo_coalesce_s = _UNDO_COALESCE_S
        # Mid-burst mutations skip the O(project) serialization; this timer
        # materializes the post-burst state once the burst goes quiet, so a
        # node drag costs nothing per grid cell.
        self._materialize_timer = QTimer(self)
        self._materialize_timer.setSingleShot(True)
        self._materialize_timer.setInterval(int(_UNDO_COALESCE_S * 1000))
        self._materialize_timer.timeout.connect(self._materialize_state_now)
        # Validation walks the whole project — debounce it so a burst of
        # keystrokes in the inspector costs one pass, not one per character.
        self._validation_timer = QTimer(self)
        self._validation_timer.setSingleShot(True)
        self._validation_timer.setInterval(250)
        self._validation_timer.timeout.connect(self._emit_validation)

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
        # O(1) via the id index (rebuilt on every change notification); the
        # linear fallback covers lookups made mid-mutation, before re-index.
        f = self._focus_index.get(focus_id)
        if f is not None and f.id == focus_id:
            return f
        for f in self._project.focuses:
            if f.id == focus_id:
                return f
        return None

    def issues(self) -> list:
        return validate_project(self._project, icon_exists=self._icon_exists(),
                                known_decision_categories=self._known_decision_categories())

    @staticmethod
    def _icon_exists():
        """Icon resolver for validation — returns None (no checker) until the
        sprite index is ready, so validation never blocks on an index build."""
        from .icon_provider import provider
        p = provider()
        return p.sprite_exists if p.is_indexed() else None

    @staticmethod
    def _known_decision_categories():
        """Set of existing game/MD category ids if already indexed, else None
        (validation then skips the unknown-category warning)."""
        from .tech_provider import tech_provider
        cats = tech_provider().md_decision_categories_cached()
        return set(cats) if cats else None

    # ----- undo / redo -----
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._materialize_state_now()
        self._redo_stack.append(self._current_state)
        self._restore_state(self._undo_stack.pop())
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._materialize_state_now()
        self._undo_stack.append(self._current_state)
        self._restore_state(self._redo_stack.pop())
        return True

    def _materialize_state_now(self) -> None:
        if self._state_stale:
            self._current_state = project_to_dict(self._project)
            self._state_stale = False

    def _force_undo_boundary(self) -> None:
        """Structural operations (add/delete/paste/rename, dialog saves) always
        start their own undo step, even inside the time-coalescing window."""
        self._last_mutation = 0.0

    def _restore_state(self, state: dict) -> None:
        self._project = project_from_dict(state)
        self._current_state = state
        self._state_stale = False
        # Fix the selection before any signal fires — listeners read selected_id
        # during project_changed.
        ids = {f.id for f in self._project.focuses}
        if self._selected_id and self._selected_id not in ids:
            self._selected_id = self._project.focuses[0].id if self._project.focuses else ""
        self._undo_skip = True
        try:
            self._emit_all()
        finally:
            self._undo_skip = False
        # The restored project is a NEW object graph — re-announce the selection
        # so the inspector and editors rebuild from it instead of keeping stale
        # references into the discarded one.
        self.selection_changed.emit(self._selected_id)
        self._last_mutation = 0.0  # the next edit starts a fresh gesture

    # ----- mutation -----
    def replace_project(self, project: FocusForgeProject, path: Optional[Path] = None) -> None:
        self._project = project
        self._path = path
        self._selected_id = project.focuses[0].id if project.focuses else ""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._current_state = project_to_dict(project)
        self._undo_skip = True
        try:
            self._emit_all()
        finally:
            self._undo_skip = False
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
        self._force_undo_boundary()
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
        self._force_undo_boundary()
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

    # ----- focus-reference upkeep (availability + bypass rules) -----
    @staticmethod
    def _focus_ref_params(item) -> list:
        """Param keys of an availability item that hold a focus id."""
        from core.availability_presets import get_availability_preset
        preset = get_availability_preset(getattr(item, "kind", ""))
        if not preset:
            return []
        return [p.key for p in preset.params if p.type == "focus"]

    @staticmethod
    def _focus_rules(focus) -> list:
        return [r for r in (focus.available, getattr(focus, "bypass", None)) if r]

    def _strip_focus_refs(self, focus, ids: set) -> None:
        for rule in self._focus_rules(focus):
            if rule.completedFocuses:
                rule.completedFocuses = [c for c in rule.completedFocuses if c not in ids]
            for item in (rule.items or []):
                for key in self._focus_ref_params(item):
                    if (item.params or {}).get(key) in ids:
                        item.params[key] = ""

    def _rewrite_focus_refs(self, focus, mapping: dict) -> None:
        for rule in self._focus_rules(focus):
            if rule.completedFocuses:
                rule.completedFocuses = [mapping.get(c, c) for c in rule.completedFocuses]
            for item in (rule.items or []):
                for key in self._focus_ref_params(item):
                    val = (item.params or {}).get(key)
                    if val in mapping:
                        item.params[key] = mapping[val]

    def delete_focuses(self, focus_ids) -> None:
        """Delete one or more focuses in a single update, stripping every
        reference (prerequisites / mutually exclusive / availability + bypass
        completed-focus checks and condition items)."""
        present = {f.id for f in self._project.focuses}
        ids = {fid for fid in focus_ids if fid in present}
        if not ids:
            return
        self._force_undo_boundary()
        self._project.focuses = [f for f in self._project.focuses if f.id not in ids]
        # Strip references
        for f in self._project.focuses:
            f.prerequisites = [p for p in f.prerequisites if p not in ids]
            f.mutuallyExclusive = [m for m in f.mutuallyExclusive if m not in ids]
            self._strip_focus_refs(f, ids)
        if self._selected_id in ids:
            self._selected_id = self._project.focuses[0].id if self._project.focuses else ""
            self.selection_changed.emit(self._selected_id)
        self._emit_all()

    # ----- copy / paste / duplicate -----
    def copy_payload(self, focus_ids) -> dict:
        """Clipboard payload (plain JSON-able dict) for the given focuses."""
        from core.serialization import focus_to_dict
        focuses = [self.find_focus(fid) for fid in focus_ids]
        return {"focusforge": 1,
                "focuses": [focus_to_dict(f) for f in focuses if f is not None]}

    def paste_focuses(self, payload, at=None) -> list:
        """Insert copied focuses with fresh unique ids. Links BETWEEN pasted
        focuses are remapped to the new ids; links to other focuses are kept
        when the target exists in this project and dropped otherwise.

        ``at`` is an optional ``(grid_x, grid_y)`` target: the copied group is
        translated so its TOP-LEFT focus lands there (preserving the relative
        layout) — i.e. paste-at-cursor. Without it, the group lands one cell
        down-right of the originals. Returns the new ids (first → selection)."""
        from core.serialization import focus_from_dict
        raw = payload.get("focuses") if isinstance(payload, dict) else None
        if not raw:
            return []
        copies = [focus_from_dict(d) for d in raw]
        old_ids = {f.id for f in copies}
        self._force_undo_boundary()
        if at is not None:
            min_x = min(int(f.position.x) for f in copies)
            min_y = min(int(f.position.y) for f in copies)
            dx, dy = int(at[0]) - min_x, int(at[1]) - min_y
        else:
            dx, dy = 1, 1  # nudge down-right so the copy doesn't sit on the original
        id_map: dict = {}
        for f in copies:
            new_id = self._unique_id(f.id or "pasted_focus")
            id_map[f.id] = new_id
            f.id = new_id
            f.position = FocusPosition(x=int(f.position.x) + dx, y=int(f.position.y) + dy)
            self._project.focuses.append(f)
        present = {f.id for f in self._project.focuses}
        for f in copies:
            f.prerequisites = [id_map.get(p, p) for p in f.prerequisites
                               if p in old_ids or p in present]
            f.mutuallyExclusive = [id_map.get(m, m) for m in f.mutuallyExclusive
                                   if m in old_ids or m in present]
            # Mutex is symmetric in the model — give kept external targets the
            # back-reference so validation doesn't flag a one-sided link.
            for m in f.mutuallyExclusive:
                if m not in id_map.values():
                    other = self.find_focus(m)
                    if other is not None and f.id not in other.mutuallyExclusive:
                        other.mutuallyExclusive = list(other.mutuallyExclusive) + [f.id]
            # Remap focus references inside availability AND bypass rules —
            # both the legacy completedFocuses list and condition-item params.
            self._rewrite_focus_refs(f, id_map)
        self._selected_id = copies[0].id
        self.selection_changed.emit(self._selected_id)
        self._emit_all()
        return [f.id for f in copies]

    def duplicate_focuses(self, focus_ids) -> list:
        return self.paste_focuses(self.copy_payload(focus_ids))

    def rename_focus(self, old_id: str, new_id: str) -> str:
        """Rename a focus (de-duping the new id) and rewrite every reference —
        prerequisites, mutual exclusions, and availability completed-focus checks.
        Returns the final id. Shared by the inspector and the AI bridge."""
        focus = self.find_focus(old_id)
        new_id = (new_id or "").strip()
        if not focus or not new_id or new_id == old_id:
            return old_id
        self._force_undo_boundary()
        new_id = self._unique_id(new_id)
        focus.id = new_id
        mapping = {old_id: new_id}
        for other in self._project.focuses:
            other.prerequisites = [new_id if p == old_id else p for p in other.prerequisites]
            other.mutuallyExclusive = [new_id if m == old_id else m for m in other.mutuallyExclusive]
            self._rewrite_focus_refs(other, mapping)
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
        self._force_undo_boundary()
        """Append a new idea (de-duping its id) and return the final id."""
        idea.id = self._unique_idea_id(idea.id)
        self._project.ideas.append(idea)
        self._project.exportSettings.includeIdeas = True
        self._emit_all()
        return idea.id

    def update_idea(self, old_id: str, new_idea) -> str:
        self._force_undo_boundary()
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
        self._force_undo_boundary()
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
        self._force_undo_boundary()
        """Append a new event (de-duping its id) and return the final id."""
        event.id = self._unique_event_id(event.id)
        self._project.events.append(event)
        self._project.exportSettings.includeEvents = True
        self._emit_all()
        return event.id

    def update_event(self, old_id: str, new_event) -> str:
        self._force_undo_boundary()
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
        self._force_undo_boundary()
        before = len(self._project.events)
        self._project.events = [e for e in self._project.events if e.id != event_id]
        if len(self._project.events) == before:
            return
        self._emit_all()

    def event_reference_count(self, event_id: str) -> int:
        """How many focus reward references point at this event (delete warnings)."""
        return sum(1 for val in self._iter_event_refs() if val == event_id)

    def event_reference_counts(self) -> dict:
        """{event_id: reference count} over all focus rewards in ONE pass — use
        this when labelling every event (per-event counting is O(events×focuses))."""
        counts: dict = {}
        for val in self._iter_event_refs():
            if val:
                counts[val] = counts.get(val, 0) + 1
        return counts

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

    # ----- decisions -----
    def _unique_decision_id(self, base: str, ignore: str = "") -> str:
        existing = {x.id for x in self._project.decisions if x.id != ignore}
        if base and base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def add_decision(self, decision) -> str:
        self._force_undo_boundary()
        decision.id = self._unique_decision_id(decision.id)
        self._project.decisions.append(decision)
        self._project.exportSettings.includeDecisions = True
        self._emit_all()
        return decision.id

    def update_decision(self, old_id: str, new_decision) -> str:
        self._force_undo_boundary()
        idx = next((i for i, x in enumerate(self._project.decisions) if x.id == old_id), -1)
        if idx < 0:
            return self.add_decision(new_decision)
        if new_decision.id != old_id:
            new_decision.id = self._unique_decision_id(new_decision.id, ignore=old_id)
        self._project.decisions[idx] = new_decision
        self._project.exportSettings.includeDecisions = True
        self._emit_all()
        return new_decision.id

    def delete_decision(self, decision_id: str) -> None:
        self._force_undo_boundary()
        before = len(self._project.decisions)
        self._project.decisions = [x for x in self._project.decisions if x.id != decision_id]
        if len(self._project.decisions) != before:
            self._emit_all()

    def _unique_decision_category_id(self, base: str, ignore: str = "") -> str:
        existing = {c.id for c in self._project.decisionCategories if c.id != ignore}
        if base and base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def add_decision_category(self, category) -> str:
        self._force_undo_boundary()
        category.id = self._unique_decision_category_id(category.id)
        self._project.decisionCategories.append(category)
        self._project.exportSettings.includeDecisions = True
        self._emit_all()
        return category.id

    def update_decision_category(self, old_id: str, new_category) -> str:
        self._force_undo_boundary()
        idx = next((i for i, c in enumerate(self._project.decisionCategories)
                    if c.id == old_id), -1)
        if idx < 0:
            return self.add_decision_category(new_category)
        if new_category.id != old_id:
            new_category.id = self._unique_decision_category_id(new_category.id, ignore=old_id)
            for d in self._project.decisions:   # keep decisions pointing at it
                if d.category == old_id:
                    d.category = new_category.id
        self._project.decisionCategories[idx] = new_category
        self._emit_all()
        return new_category.id

    def delete_decision_category(self, category_id: str) -> None:
        self._force_undo_boundary()
        before = len(self._project.decisionCategories)
        self._project.decisionCategories = [c for c in self._project.decisionCategories
                                            if c.id != category_id]
        if len(self._project.decisionCategories) != before:
            self._emit_all()

    def decision_category_reference_count(self, category_id: str) -> int:
        return sum(1 for d in self._project.decisions if d.category == category_id)

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
        try:
            text = path.read_text(encoding="utf-8-sig")
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"{path.name} isn't a readable Focus Forge project — the file is "
                f"corrupt or not UTF-8 JSON ({exc}). If you have a backup or a "
                f"version in source control, restore that copy.") from exc
        self.replace_project(project_from_dict(data), path=path)
        self.status_message.emit(f"Opened {path}")

    def save_to_file(self, path: Path) -> None:
        text = json.dumps(project_to_dict(self._project), indent=2, ensure_ascii=False)
        # Atomic write: a crash or full disk mid-save must never truncate the
        # user's only copy of the project.
        atomic_write_bytes(path, text.encode("utf-8"))
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
            atomic_write_bytes(target, content.encode("utf-8"))
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
        self._focus_index = {f.id: f for f in self._project.focuses}
        if not self._undo_skip:
            self._capture_undo_state()
        self._set_dirty(True)
        self.project_changed.emit()
        if QCoreApplication.instance() is not None:
            self._validation_timer.start()
        else:  # headless (tests): no event loop to fire the timer
            self._emit_validation()

    def _capture_undo_state(self) -> None:
        now = time.monotonic()
        if now - self._last_mutation <= self._undo_coalesce_s:
            # Mid-burst (typing, dragging): the pre-burst snapshot already sits
            # on the stack; skip the O(project) serialization entirely and let
            # the idle timer materialize the post-burst state.
            self._redo_stack.clear()
            self._state_stale = True
            self._last_mutation = now
            if QCoreApplication.instance() is not None:
                self._materialize_timer.start()
            else:
                self._materialize_state_now()
            return
        # Gesture boundary: settle any stale burst first, then push the state
        # BEFORE this change as the undoable step.
        self._materialize_state_now()
        new_state = project_to_dict(self._project)
        if new_state == self._current_state:
            return  # no-op change — don't burn an undo step
        self._undo_stack.append(self._current_state)
        if len(self._undo_stack) > _UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._current_state = new_state
        self._last_mutation = now

    def _emit_validation(self) -> None:
        self.validation_changed.emit(
            validate_project(self._project, icon_exists=self._icon_exists(),
                             known_decision_categories=self._known_decision_categories()))
