"""Discovery file ownership — clear_bridge_info must not wipe another instance's file."""
from __future__ import annotations

import json
import os

from core import bridge_discovery as bd


def test_clear_bridge_info_is_pid_aware(tmp_path, monkeypatch) -> None:
    f = tmp_path / "bridge.json"
    monkeypatch.setattr(bd, "bridge_info_path", lambda: f)

    # File owned by a DIFFERENT (live) instance — must be left alone.
    f.write_text(json.dumps({"port": 5, "pid": os.getpid() + 999999, "protocol": 1}))
    bd.clear_bridge_info()
    assert f.exists(), "must not delete a file owned by another process"

    # File owned by THIS process — cleared.
    bd.write_bridge_info(5)
    assert f.exists()
    bd.clear_bridge_info()
    assert not f.exists()

    # No pid recorded (legacy file) — cleared.
    f.write_text(json.dumps({"port": 5, "protocol": 1}))
    bd.clear_bridge_info()
    assert not f.exists()


def test_write_read_round_trip(tmp_path, monkeypatch) -> None:
    f = tmp_path / "bridge.json"
    monkeypatch.setattr(bd, "bridge_info_path", lambda: f)
    bd.write_bridge_info(54321, version="9.9.9")
    info = bd.read_bridge_info()
    assert info["port"] == 54321 and info["pid"] == os.getpid() and info["version"] == "9.9.9"
