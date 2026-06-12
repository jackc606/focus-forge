"""Create the on-disk skeleton for a new HOI4 / Millennium Dawn submod.

Writes the two descriptor files HOI4 expects — an inner ``descriptor.mod`` and an
outer ``<folder>.mod`` (with an absolute ``path=``) in the mods folder — plus the
standard content directory tree. Pure filesystem logic, no Qt, so it's testable.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .file_io import atomic_write_text

MD_DEPENDENCY = "Millennium Dawn: A Modern Day Mod"
DEFAULT_TAGS = ["Gameplay", "National Focuses"]
DEFAULT_SUPPORTED_VERSION = "1.17.*"

# Directories a focus-oriented submod typically needs.
SKELETON_DIRS = [
    "common/national_focus",
    "common/ideas",
    "common/decisions",
    "common/on_actions",
    "common/country_leader",
    "common/characters",
    "common/scripted_effects",
    "events",
    "localisation/english",
    "interface",
    "gfx/interface/goals",
    "gfx/flags",
    "gfx/flags/medium",
    "gfx/flags/small",
    "gfx/leaders",
    "history/countries",
]


def default_mod_root() -> str:
    """The standard HOI4 mods folder under the user's Documents, if it exists."""
    candidates = [
        Path.home() / "Documents" / "Paradox Interactive" / "Hearts of Iron IV" / "mod",
        Path.home() / "OneDrive" / "Documents" / "Paradox Interactive" / "Hearts of Iron IV" / "mod",
    ]
    for c in candidates:
        if c.is_dir():
            return str(c)
    return str(candidates[0])


def find_mod_root(start) -> str:
    """Nearest ancestor of ``start`` (a file or dir) that contains a
    ``descriptor.mod`` — i.e. the mod folder a project lives in. None if none."""
    if not start:
        return None
    p = Path(start)
    if p.is_file() or p.suffix:
        p = p.parent
    for d in [p, *p.parents]:
        if (d / "descriptor.mod").is_file():
            return str(d)
    return None


def sanitize_folder(name: str) -> str:
    """Turn a display name into a safe folder/file slug (lowercase, underscores)."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "new_submod"


def build_descriptor(name: str, version: str, tags, dependencies,
                     supported_version: str, path: str = None) -> str:
    lines = [f'version="{version}"', "tags={"]
    for t in tags:
        lines.append(f'\t"{t}"')
    lines.append("}")
    lines.append(f'name="{name}"')
    if dependencies:
        lines.append("dependencies={")
        for d in dependencies:
            lines.append(f'\t"{d}"')
        lines.append("}")
    lines.append(f'supported_version="{supported_version}"')
    if path:
        lines.append(f'path="{path}"')
    return "\n".join(lines) + "\n"


def scaffold_submod(mod_root, folder: str, name: str, *,
                    version: str = "0.1.0", tags=None, dependencies=None,
                    supported_version: str = DEFAULT_SUPPORTED_VERSION) -> dict:
    """Create the submod folder tree + descriptor files. Returns key paths.

    Raises ``FileExistsError`` if the target already looks like a mod (has a
    ``descriptor.mod``), so we never clobber existing work.
    """
    tags = list(tags) if tags else list(DEFAULT_TAGS)
    dependencies = list(dependencies) if dependencies is not None else [MD_DEPENDENCY]
    folder = (folder or "").strip()
    if not folder:
        raise ValueError("folder name is required")
    name = (name or folder).strip()

    mod_root = Path(mod_root)
    mod_dir = mod_root / folder
    descriptor_path = mod_dir / "descriptor.mod"
    if descriptor_path.exists():
        raise FileExistsError(f"A mod already exists at {mod_dir}")

    for d in SKELETON_DIRS:
        (mod_dir / d).mkdir(parents=True, exist_ok=True)

    atomic_write_text(
        descriptor_path,
        build_descriptor(name, version, tags, dependencies, supported_version))

    abs_path = os.path.abspath(str(mod_dir)).replace("\\", "/")
    outer_path = mod_root / f"{folder}.mod"
    atomic_write_text(
        outer_path,
        build_descriptor(name, version, tags, dependencies, supported_version, path=abs_path))

    return {
        "mod_dir": str(mod_dir),
        "descriptor": str(descriptor_path),
        "outer": str(outer_path),
        "created_dirs": [str(mod_dir / d) for d in SKELETON_DIRS],
    }
