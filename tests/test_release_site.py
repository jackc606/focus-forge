"""Tests for release.py's website-refresh text transforms (--site)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "release", Path(__file__).resolve().parents[1] / "packaging" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

_SITE_TS = """export const site = {
  version: '0.3.3',
  stage: 'pre-alpha',
  downloadUrl: 'https://github.com/jackc606/focus-forge-releases/releases/latest/download/FocusForge-0.3.3-setup.exe',
  installerName: 'FocusForge-0.3.3-setup.exe',
  installerSize: '~61 MB',
};
"""

_CHANGELOG_TS = """export const releases: Release[] = [
  {
    version: '0.3.3',
    date: '2026-07-21',
    stage: 'pre-alpha',
    current: true,
    notes: [
      'Old note.'
    ]
  },
];
"""


def test_site_ts_updated_rewrites_all_fields():
    out = release._site_ts_updated(_SITE_TS, "0.3.4",
                                   "FocusForge-0.3.4-setup.exe", 62)
    assert "version: '0.3.4'" in out
    assert "download/FocusForge-0.3.4-setup.exe'" in out
    assert "installerName: 'FocusForge-0.3.4-setup.exe'" in out
    assert "installerSize: '~62 MB'" in out
    assert "0.3.3" not in out


def test_changelog_ts_gets_new_current_entry():
    entry = {"version": "0.3.4", "date": "2026-07-22",
             "changes": ["First note.", 'Note with "quotes" and \'apostrophes\'.']}
    out = release._changelog_ts_updated(_CHANGELOG_TS, entry)
    # New entry first, marked current; old current flag removed.
    assert out.index("version: '0.3.4'") < out.index("version: '0.3.3'")
    assert out.count("current: true,") == 1
    assert '"First note.",' in out
    assert '\\"quotes\\"' in out            # json-escaped, valid TS
    # Idempotent: running again changes nothing.
    assert release._changelog_ts_updated(out, entry) == out
