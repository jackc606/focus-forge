"""Tests for the submod scaffolder."""
from __future__ import annotations

import os

import pytest

from core.mod_scaffold import (
    MD_DEPENDENCY,
    find_mod_root,
    sanitize_folder,
    scaffold_submod,
)


def test_sanitize_folder():
    assert sanitize_folder("Millennium Dawn: Chile Rework") == "millennium_dawn_chile_rework"
    assert sanitize_folder("  ALPHA--beta  ") == "alpha_beta"
    assert sanitize_folder("") == "new_submod"


def test_scaffold_creates_skeleton_and_descriptors(tmp_path):
    res = scaffold_submod(str(tmp_path), "md_chile", "Millennium Dawn: Chile")
    mod_dir = tmp_path / "md_chile"
    assert (mod_dir / "descriptor.mod").is_file()
    assert (tmp_path / "md_chile.mod").is_file()
    # skeleton present
    assert (mod_dir / "common" / "national_focus").is_dir()
    assert (mod_dir / "localisation" / "english").is_dir()
    assert (mod_dir / "gfx" / "interface" / "goals").is_dir()
    assert res["mod_dir"] == str(mod_dir)


def test_descriptors_content(tmp_path):
    scaffold_submod(str(tmp_path), "md_chile", "Millennium Dawn: Chile")
    inner = (tmp_path / "md_chile" / "descriptor.mod").read_text(encoding="utf-8")
    outer = (tmp_path / "md_chile.mod").read_text(encoding="utf-8")
    assert 'name="Millennium Dawn: Chile"' in inner
    assert MD_DEPENDENCY in inner
    assert 'supported_version="1.17.*"' in inner
    assert "path=" not in inner                      # inner has NO path
    assert 'path="' in outer                          # outer DOES
    assert outer.count("\\") == 0                     # path uses forward slashes
    assert "md_chile" in outer


def test_scaffold_refuses_to_clobber(tmp_path):
    scaffold_submod(str(tmp_path), "md_chile", "Chile")
    with pytest.raises(FileExistsError):
        scaffold_submod(str(tmp_path), "md_chile", "Chile")


def test_find_mod_root_from_project_path(tmp_path):
    scaffold_submod(str(tmp_path), "md_chile", "Chile")
    mod_dir = tmp_path / "md_chile"
    # A project file saved anywhere inside the mod resolves to the mod root.
    proj = mod_dir / "md_chile.focusforge.json"
    proj.write_text("{}", encoding="utf-8")
    assert find_mod_root(str(proj)) == str(mod_dir)
    assert find_mod_root(str(mod_dir / "common" / "national_focus")) == str(mod_dir)
    # Outside any mod → None.
    assert find_mod_root(str(tmp_path)) is None
