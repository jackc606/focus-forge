"""Dialog to scaffold a brand-new HOI4 / Millennium Dawn submod from the app."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.mod_scaffold import (
    DEFAULT_SUPPORTED_VERSION,
    DEFAULT_TAGS,
    MD_DEPENDENCY,
    default_mod_root,
    sanitize_folder,
)

from . import theme as T
from .country_tag_picker import CountryTagPicker
from .widgets import hint, panel_header, section_header

_ALL_TAGS = ["Gameplay", "National Focuses", "Events", "Alternative History",
             "Ideologies", "Map", "Balance"]


class NewSubmodDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Submod")
        self.resize(560, 0)
        self._settings = QSettings("FocusForge", "FocusForge")
        self._folder_edited = False

        v = QVBoxLayout(self)
        v.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        v.setSpacing(T.SPACE_MD)
        v.addWidget(panel_header("New Submod"))
        v.addWidget(hint("Creates a project in your Focus Forge workspace. "
                         "\"Export to Mod\" then builds it into the HOI4 mods "
                         "folder below (and into the launcher)."))

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        v.addLayout(form)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Millennium Dawn: Chile Expanded")
        self._name.textChanged.connect(self._on_name)
        form.addRow("Mod name", self._name)

        self._folder = QLineEdit()
        self._folder.setPlaceholderText("md_chile_expanded")
        self._folder.textEdited.connect(lambda *_: setattr(self, "_folder_edited", True))
        form.addRow("Folder name", self._folder)

        # Location (mods folder)
        loc_row = QWidget()
        lr = QHBoxLayout(loc_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.setSpacing(T.SPACE_SM)
        self._location = QLineEdit(self._settings.value("mod_root", "") or default_mod_root())
        lr.addWidget(self._location, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_location)
        lr.addWidget(browse)
        form.addRow("HOI4 mods folder", loc_row)

        self._country = CountryTagPicker()
        form.addRow("Country tag", self._country)

        self._supported = QLineEdit(DEFAULT_SUPPORTED_VERSION)
        form.addRow("Supported version", self._supported)

        # Tags
        v.addWidget(section_header("Tags"))
        tags_row = QWidget()
        tr = QHBoxLayout(tags_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(T.SPACE_MD)
        self._tag_boxes = {}
        for t in _ALL_TAGS:
            cb = QCheckBox(t)
            cb.setChecked(t in DEFAULT_TAGS)
            self._tag_boxes[t] = cb
            tr.addWidget(cb)
        tr.addStretch(1)
        v.addWidget(tags_row)

        # Options
        v.addWidget(section_header("Options"))
        self._dep_md = QCheckBox(f'Depends on "{MD_DEPENDENCY}"')
        self._dep_md.setChecked(True)
        v.addWidget(self._dep_md)
        self._make_project = QCheckBox("Create a focus-tree project and open it")
        self._make_project.setChecked(True)
        v.addWidget(self._make_project)
        self._start_blank = QCheckBox(
            "Start blank (don't import this country's Millennium Dawn focus tree)")
        self._start_blank.setToolTip(
            "By default a new submod imports the chosen country's existing MD focus "
            "tree so you can build on what's already there. Tick this to start from an "
            "empty placeholder tree instead.")
        v.addWidget(self._start_blank)
        self._add_icons = QCheckBox("Add this mod folder as an icon source")
        self._add_icons.setChecked(True)
        v.addWidget(self._add_icons)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Create Submod")
        self._buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        v.addWidget(self._buttons)

    # ----- helpers -----
    def _on_name(self, text: str) -> None:
        if not self._folder_edited:
            self._folder.setText(sanitize_folder(text))

    def _browse_location(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose mods folder", self._location.text())
        if path:
            self._location.setText(path)

    def values(self) -> dict:
        self._settings.setValue("mod_root", self._location.text())
        tags = [t for t, cb in self._tag_boxes.items() if cb.isChecked()]
        deps = [MD_DEPENDENCY] if self._dep_md.isChecked() else []
        return {
            "name": self._name.text().strip() or self._folder.text().strip(),
            "folder": sanitize_folder(self._folder.text()),
            "mod_root": self._location.text().strip(),
            "country_tag": self._country.current_tag(),
            "supported_version": self._supported.text().strip() or DEFAULT_SUPPORTED_VERSION,
            "tags": tags or list(DEFAULT_TAGS),
            "dependencies": deps,
            "make_project": self._make_project.isChecked(),
            "start_blank": self._start_blank.isChecked(),
            "add_icons": self._add_icons.isChecked(),
        }
