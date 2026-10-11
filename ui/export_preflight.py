"""Export pre-flight: stop a tree from being exported NEXT TO the base-mod
tree it was copied from.

HOI4 loads every ``common/national_focus/*.txt`` it can see, so an edited
copy of Millennium Dawn's Nigeria tree exported as ``nga_focus.txt`` defines
every focus twice and breaks in-game (no prerequisite lines, nothing
startable). ``run_export_preflight`` computes the collision report
(core.tree_index) and, only when there IS a problem, offers the two real
fixes in plain language — export under the base file's name so the mod
REPLACES it, or prefix every focus id so the copy can coexist — plus
"export anyway" and cancel. No problem → no dialog.

The model-changing parts (``apply_replace`` / ``apply_prefix``) are plain
functions so they are undoable through the model and testable offscreen.
"""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.focus_import import ID_PREFIX_PATTERN
from core.multi_tree import all_focuses, is_multi, tree_count
from core.tree_index import BASE_MOD_NAME, collision_issues, current_index, find_collisions

from . import theme as T
from .widgets import divider, hint, panel_header

CHOICE_REPLACE = "replace"
CHOICE_PREFIX = "prefix"
CHOICE_ANYWAY = "anyway"
CHOICE_CANCEL = "cancel"

PREFLIGHT_TITLE = "Your export would break the tree in-game"


def compute_report(model, roots):
    """The project's CollisionReport against ``roots``, or None when there
    are no roots to check against. Builds the shared index on this thread if
    needed — the user just clicked Export, a one-off wait is fine."""
    roots = list(roots or ())
    if not roots:
        return None
    index = current_index(lambda: roots)
    if index is None:
        return None
    return find_collisions(model.project, index)


def default_prefix(model) -> str:
    tag = (model.project.countryTag or "TAG").strip().upper() or "TAG"
    return f"{tag}_NEW"


def prefix_problem(prefix: str) -> str:
    """'' when ``prefix`` is a legal focus-id prefix, else a plain-language
    reason (shared by the import dialog and the pre-flight prompt)."""
    prefix = (prefix or "").strip()
    if not prefix:
        return "Type a prefix first — for example NGA_NEW."
    if not ID_PREFIX_PATTERN.match(prefix):
        return ("A prefix can only use letters, digits and underscores, and must "
                "start with a letter — for example NGA_NEW.")
    return ""


# ---------------------------------------------------------------------------
# Model changes (undoable; each is one undo step)
# ---------------------------------------------------------------------------
def apply_replace(model, report) -> str:
    """Point the export at the base file's name so the mod REPLACES it.
    Returns the new focusFileName."""
    stem = report.suggested_stem
    model.update_export_settings(focusFileName=stem)
    src = dict(model.project.source or {})
    src["mode"] = "replace"
    src.setdefault("file", report.suggested_basename)
    model.update_project_meta(source=src)
    return stem


def prefix_unavailable_reason(project) -> str:
    """'' when the "give my focuses a prefix" fix can be applied to
    ``project``, else why not, in plain language.

    A prefixed copy only works when the copy is self-contained. A multi-tree
    project is not: its trees are tied together by their tree ids
    (``load_focus_tree`` / ``has_focus_tree`` in rewards and offsets) and by
    their verbatim ``country = { }`` blocks, none of which a focus-id rename
    reaches — prefixing just the tree on screen would leave every other tree
    still colliding, and prefixing all of them would leave copies that
    still switch to (and compete with) the originals. So the fix is offered
    for single-tree projects only; a multi-tree file is exported as a
    replacement, or one tree is re-imported as a separate copy."""
    if not is_multi(project):
        return ""
    n = tree_count(project)
    what = f"all {n} trees" if n > 1 else "a tree and its shared focuses"
    return (f"This project holds {what} of one focus file, and they refer to each "
            f"other by tree id, so prefixing focus ids can't turn it into a working "
            f"separate copy. Export it as a replacement instead — or, for a separate "
            f"copy of one tree, use Import Tree… → \"Start a separate copy\".")


def apply_prefix(model, prefix: str) -> dict:
    """Rename EVERY focus to ``<prefix>_<id>`` (prerequisites, mutual
    exclusions, availability checks and shortcut targets follow — all inside
    ``rename_focus``), and point the tree id + export file at
    ``<prefix>_focus`` — all as ONE undo step. Returns the old→new id mapping.

    Single-tree projects only (``prefix_unavailable_reason``); raises
    ValueError otherwise, before anything changes."""
    prefix = (prefix or "").strip()
    problem = prefix_problem(prefix) or prefix_unavailable_reason(model.project)
    if problem:
        raise ValueError(problem)
    stem = f"{prefix.lower()}_focus"
    old_tree_id = (model.project.treeId or "").strip()
    mapping: dict = {}
    with model.batch():
        # Not multi-tree, so project.focuses IS every focus of the file
        # (including any shared focuses a copy-mode import brought along).
        for old in [f.id for f in model.project.focuses]:
            if not old:
                continue
            mapping[old] = model.rename_focus(old, f"{prefix}_{old}")
        # Shared focuses position themselves per tree with
        # `offset = { … trigger = { has_focus_tree = <tree id> } }`; those must
        # follow the tree's new id or the copy loses that layout on export.
        if old_tree_id and old_tree_id != stem:
            ref = re.compile(r"(\bhas_focus_tree\s*=\s*)" + re.escape(old_tree_id)
                             + r"(?![A-Za-z0-9_.\-])")
            for f in all_focuses(model.project):
                if getattr(f, "offsets", None):
                    f.offsets = [[ref.sub(lambda m: m.group(1) + stem, ln) for ln in block]
                                 for block in f.offsets]
        src = dict(model.project.source or {})
        src["mode"] = "copy"
        model.update_project_meta(treeId=stem, source=src)
        model.update_export_settings(focusFileName=stem)
    return mapping


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
class ExportPreflightDialog(QDialog):
    """Plain-language explanation of the collision plus the fixes. Reads
    ``.choice`` after exec(): one of the CHOICE_* constants."""

    def __init__(self, report, parent=None, prefix_blocked: str = "") -> None:
        """``prefix_blocked``: why the prefix fix can't be used for this
        project ('' = it can) — the button is then disabled and says why."""
        super().__init__(parent)
        self.setWindowTitle(PREFLIGHT_TITLE)
        self.setMinimumWidth(T.DIALOG_MD[0])
        self.choice = CHOICE_CANCEL
        self._report = report

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header(PREFLIGHT_TITLE))
        for issue in collision_issues(report):
            lbl = QLabel(issue.message)
            lbl.setWordWrap(True)
            lbl.setObjectName("issueTextError")
            v.addWidget(lbl)
        v.addWidget(divider())
        v.addWidget(hint("Pick what you meant to do:"))

        stem = report.suggested_stem
        self.replace_btn = QPushButton(f"Export as '{stem}' (replace {BASE_MOD_NAME}'s tree)")
        self.replace_btn.setObjectName("primary")
        self.replace_btn.setToolTip(
            f"Your mod's file gets the same name as {BASE_MOD_NAME}'s, so the game loads "
            f"yours INSTEAD of theirs. This is the normal way to edit an existing tree.")
        self.replace_btn.clicked.connect(lambda: self._pick(CHOICE_REPLACE))
        self.replace_btn.setVisible(bool(stem))
        v.addWidget(self.replace_btn)

        self.prefix_btn = QPushButton("Give my focuses a prefix…")
        self.prefix_btn.setToolTip(
            f"Keep {BASE_MOD_NAME}'s tree and add yours as a separate copy: every focus "
            f"id gets a prefix so the two can't clash. One undo step.")
        self.prefix_btn.clicked.connect(lambda: self._pick(CHOICE_PREFIX))
        v.addWidget(self.prefix_btn)
        if prefix_blocked:
            self.prefix_btn.setEnabled(False)
            self.prefix_btn.setToolTip(prefix_blocked)
            v.addWidget(hint(prefix_blocked))

        row = QHBoxLayout()
        row.setSpacing(T.SPACE_SM)
        row.addStretch(1)
        self.anyway_btn = QPushButton("Export anyway")
        self.anyway_btn.setToolTip("Write the files as they are. The tree WILL be broken in-game "
                                   "until one of the fixes above is applied.")
        self.anyway_btn.clicked.connect(lambda: self._pick(CHOICE_ANYWAY))
        row.addWidget(self.anyway_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(lambda: self._pick(CHOICE_CANCEL))
        row.addWidget(self.cancel_btn)
        v.addLayout(row)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        if choice == CHOICE_CANCEL:
            self.reject()
        else:
            self.accept()


def ask_prefix(parent, default: str):
    """Prompt for a focus-id prefix until it is legal or the user cancels.
    Returns the prefix, or None."""
    text = default
    while True:
        text, ok = QInputDialog.getText(
            parent, "Prefix for your focuses",
            "Every focus id will start with this prefix (for example NGA_NEW_).\n"
            "Letters, digits and underscores only, starting with a letter:",
            QLineEdit.Normal, text)
        if not ok:
            return None
        text = (text or "").strip()
        problem = prefix_problem(text)
        if not problem:
            return text
        QMessageBox.warning(parent, "Prefix for your focuses", problem)


def apply_choice(parent, model, report, choice: str, prefix=None) -> bool:
    """Carry out a dialog choice. True = go ahead with the export."""
    if choice == CHOICE_REPLACE and report.suggested_basename:
        stem = apply_replace(model, report)
        model.status_message.emit(
            f"Export file set to '{stem}' — your tree now replaces {BASE_MOD_NAME}'s.")
        return True
    if choice == CHOICE_PREFIX:
        blocked = prefix_unavailable_reason(model.project)
        if blocked:     # the dialog disables the button; guard other callers
            QMessageBox.information(parent, "Prefix for your focuses", blocked)
            return False
        if prefix is None:
            prefix = ask_prefix(parent, default_prefix(model))
        if not prefix:
            return False
        mapping = apply_prefix(model, prefix)
        model.status_message.emit(
            f"{len(mapping)} focus ids prefixed with '{prefix}_' — your tree is now a separate "
            f"copy (Undo reverses all of it).")
        return True
    return choice == CHOICE_ANYWAY


def run_export_preflight(parent, model, roots) -> bool:
    """Gate an export on the existing-tree collision check. True = proceed
    (nothing to fix, a fix was applied, or the user chose to export anyway);
    False = the user cancelled."""
    report = compute_report(model, roots)
    if report is None or not report.is_problem:
        return True
    dlg = ExportPreflightDialog(report, parent,
                                prefix_blocked=prefix_unavailable_reason(model.project))
    dlg.exec()
    return apply_choice(parent, model, report, dlg.choice)
