"""Auto-updater logic: version parsing, release parsing, download verification.

Pure core.update_check — no Qt and no network (urlopen is monkeypatched)."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from core import update_check
from core.update_check import (
    UpdateError,
    UpdateInfo,
    download_asset,
    is_newer,
    parse_release,
    parse_version,
)


# ----- parse_version -----
@pytest.mark.parametrize("text,expected", [
    ("0.3.0", (0, 3, 0)),
    ("v0.3.0", (0, 3, 0)),
    ("V1.2.3", (1, 2, 3)),
    ("v0.3.0-pre", (0, 3, 0)),          # trailing junk tolerated
    ("0.3.0.7", (0, 3, 0)),             # extra parts ignored
    ("1.2", (1, 2, 0)),                 # 2-part version
    ("v2", (2, 0, 0)),                  # 1-part version
    ("  v10.20.30  ", (10, 20, 30)),
    ("garbage", (0, 0, 0)),
    ("", (0, 0, 0)),
    (None, (0, 0, 0)),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


# ----- is_newer -----
@pytest.mark.parametrize("latest,current,expected", [
    ("0.3.1", "0.3.0", True),      # newer patch
    ("0.4.0", "0.3.9", True),      # newer minor
    ("1.0.0", "0.9.9", True),      # newer major
    ("v0.3.1", "0.3.0", True),     # v-prefix on latest
    ("0.3.0", "0.3.0", False),     # equal
    ("0.3.0", "v0.3.0", False),    # equal with prefix
    ("0.2.9", "0.3.0", False),     # older
    ("garbage", "0.1.0", False),   # unparseable latest never wins
    ("0.0.1", "garbage", True),    # unparseable current loses
])
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


# ----- parse_release -----
def _release(tag="v0.4.0", assets=None, body="Fixes and features.",
             html_url="https://github.com/jackc606/focus-forge-releases/releases/tag/v0.4.0"):
    if assets is None:
        assets = [{
            "name": "FocusForge-0.4.0-setup.exe",
            "browser_download_url": "https://example.invalid/FocusForge-0.4.0-setup.exe",
            "size": 12345,
        }]
    return {"tag_name": tag, "body": body, "html_url": html_url, "assets": assets}


def test_parse_release_newer_with_asset():
    info = parse_release(_release(), "0.3.0")
    assert info is not None
    assert info.version == "0.4.0"
    assert info.tag == "v0.4.0"
    assert info.notes == "Fixes and features."
    assert info.asset_name == "FocusForge-0.4.0-setup.exe"
    assert info.asset_url.endswith("FocusForge-0.4.0-setup.exe")
    assert info.asset_size == 12345
    assert info.sha256 is None            # filled in later by fetch_latest
    assert "releases/tag/v0.4.0" in info.html_url


def test_parse_release_equal_version_is_none():
    assert parse_release(_release(tag="v0.4.0"), "0.4.0") is None


def test_parse_release_older_version_is_none():
    assert parse_release(_release(tag="v0.2.0"), "0.3.0") is None


def test_parse_release_no_matching_asset_is_none():
    assets = [
        {"name": "SHA256SUMS.txt", "browser_download_url": "u", "size": 1},
        {"name": "SomethingElse-0.4.0-setup.exe", "browser_download_url": "u", "size": 1},
        {"name": "FocusForge-0.4.0.zip", "browser_download_url": "u", "size": 1},
    ]
    assert parse_release(_release(assets=assets), "0.3.0") is None


def test_parse_release_asset_match_is_case_insensitive():
    assets = [{"name": "FOCUSFORGE-0.4.0-SETUP.EXE",
               "browser_download_url": "u", "size": 7}]
    info = parse_release(_release(assets=assets), "0.3.0")
    assert info is not None
    assert info.asset_name == "FOCUSFORGE-0.4.0-SETUP.EXE"


def test_parse_release_garbage_payload_is_none():
    assert parse_release({}, "0.3.0") is None
    assert parse_release(None, "0.3.0") is None


# ----- download_asset -----
class _FakeResponse:
    """Just enough of an http.client.HTTPResponse for download_asset."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve_bytes(monkeypatch, data: bytes):
    monkeypatch.setattr(update_check, "urlopen",
                        lambda request, timeout=None: _FakeResponse(data))


def _info(data: bytes, sha256=None):
    return UpdateInfo(
        version="0.4.0", tag="v0.4.0", notes="",
        asset_url="https://example.invalid/FocusForge-0.4.0-setup.exe",
        asset_name="FocusForge-0.4.0-setup.exe",
        asset_size=len(data), sha256=sha256)


def test_download_asset_good_hash_passes(tmp_path, monkeypatch):
    data = b"installer-bytes" * 10_000  # > one 64 KiB chunk
    _serve_bytes(monkeypatch, data)
    info = _info(data, sha256=hashlib.sha256(data).hexdigest())

    progress = []
    dest = download_asset(info, str(tmp_path),
                          progress_cb=lambda got, total: progress.append((got, total)))

    assert Path(dest) == tmp_path / info.asset_name
    assert Path(dest).read_bytes() == data
    assert progress                        # callback fired per chunk
    assert progress[-1] == (len(data), len(data))
    assert [got for got, _ in progress] == sorted(got for got, _ in progress)


def test_download_asset_bad_hash_raises_and_removes_file(tmp_path, monkeypatch):
    data = b"tampered-installer-bytes"
    _serve_bytes(monkeypatch, data)
    info = _info(data, sha256="0" * 64)

    with pytest.raises(UpdateError):
        download_asset(info, str(tmp_path))
    # No partial/bad file is left behind looking usable.
    assert not (tmp_path / info.asset_name).exists()


def test_download_asset_without_checksum_skips_verification(tmp_path, monkeypatch):
    data = b"unverified but delivered"
    _serve_bytes(monkeypatch, data)
    dest = download_asset(_info(data, sha256=None), str(tmp_path))
    assert Path(dest).read_bytes() == data


def test_download_asset_network_error_raises_updateerror(tmp_path, monkeypatch):
    def boom(request, timeout=None):
        raise OSError("connection reset")
    monkeypatch.setattr(update_check, "urlopen", boom)
    with pytest.raises(UpdateError):
        download_asset(_info(b"x"), str(tmp_path))
