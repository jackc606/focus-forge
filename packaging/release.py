"""Build and publish a Focus Forge release (developer tool — not shipped).

Reads the version from core/version.py (single source of truth), syncs it into
installer.iss and pyproject.toml, builds the PyInstaller folder, compiles the
Inno Setup installer, writes SHA256SUMS.txt, and publishes everything as a
GitHub Release on the public releases repo (the app's auto-updater polls it).

Usage (from the project root):
    python packaging/release.py [--notes-file NOTES.md] [--dry-run]

Release notes come from --notes-file, or fall back to this version's entry in
core/changelog.py (title + bullet list). --dry-run does everything except the
final `gh release create`.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASES_REPO = "jackc606/focus-forge-releases"

ISCC_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
]


def step(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list, what: str) -> None:
    print(f"$ {subprocess.list2cmdline(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        fail(f"{what} failed (exit code {result.returncode}).")


def read_version() -> str:
    text = (ROOT / "core" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        fail("Couldn't find __version__ in core/version.py")
    return m.group(1)


def _sync_file(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, replacement, text, count=1)
    if count == 0:
        fail(f"Couldn't find the version line in {path.name}")
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"  {path.name}: {label} updated")
    else:
        print(f"  {path.name}: already in sync")


def sync_versions(version: str) -> None:
    step(f"Syncing version {version} into installer.iss + pyproject.toml")
    _sync_file(ROOT / "installer.iss",
               r'(#define MyAppVersion ")[^"]*(")',
               rf"\g<1>{version}\g<2>",
               "MyAppVersion")
    _sync_file(ROOT / "pyproject.toml",
               r'(?m)^(version\s*=\s*")[^"]*(")',
               rf"\g<1>{version}\g<2>",
               "version")


def resolve_notes(notes_file: str | None, version: str) -> Path:
    """The release-notes file: --notes-file, else generated from the matching
    core/changelog.py entry (which must exist for this version)."""
    if notes_file:
        p = Path(notes_file)
        if not p.is_file():
            fail(f"--notes-file not found: {p}")
        print(f"  using notes file: {p}")
        return p
    sys.path.insert(0, str(ROOT))
    from core.changelog import CHANGELOG  # noqa: PLC0415 (needs ROOT on path)
    entry = next((e for e in CHANGELOG if e.get("version") == version), None)
    if entry is None:
        fail(f"core/changelog.py has no entry for {version} — add one, or pass "
             f"--notes-file.")
    lines = []
    if entry.get("title"):
        lines += [f"## {entry['title']}", ""]
    lines += [f"- {c}" for c in entry.get("changes", [])]
    out = ROOT / "dist" / f"release-notes-{version}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  generated notes from core/changelog.py -> {out}")
    return out


def find_iscc() -> str:
    on_path = shutil.which("ISCC") or shutil.which("ISCC.exe")
    if on_path:
        return on_path
    for candidate in ISCC_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    fail("ISCC.exe (Inno Setup 6 compiler) not found — install Inno Setup 6 "
         "from https://jrsoftware.org/isinfo.php or add ISCC.exe to PATH.")
    raise AssertionError  # unreachable (fail exits)


def sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the installer and publish it as a GitHub Release.")
    parser.add_argument("--notes-file",
                        help="Markdown release notes; defaults to this "
                             "version's core/changelog.py entry.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Do everything except `gh release create`.")
    args = parser.parse_args()

    version = read_version()
    tag = f"v{version}"
    step(f"Releasing Focus Forge {tag}")

    sync_versions(version)

    step("Resolving release notes")
    notes = resolve_notes(args.notes_file, version)

    if not args.dry_run and shutil.which("gh") is None:
        fail("GitHub CLI (gh) not found on PATH — install it or use --dry-run.")

    step("Building with PyInstaller")
    run([sys.executable, "-m", "PyInstaller", "build.spec",
         "--clean", "--noconfirm"], "PyInstaller build")

    step("Compiling the installer with Inno Setup")
    run([find_iscc(), str(ROOT / "installer.iss")], "Inno Setup compile")

    setup = ROOT / "dist" / f"FocusForge-{version}-setup.exe"
    if not setup.is_file():
        fail(f"Expected installer not found: {setup}")

    step("Writing SHA256SUMS.txt")
    digest = sha256_of(setup)
    sums = ROOT / "dist" / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {setup.name}\n", encoding="utf-8")
    print(f"  {digest}  {setup.name}")

    gh_cmd = [
        "gh", "release", "create", tag,
        "--repo", RELEASES_REPO,
        "--title", f"Focus Forge {tag}",
        "--notes-file", str(notes),
        str(setup), str(sums),
    ]
    if args.dry_run:
        step("Dry run — skipping publish")
        print(f"  would run: {subprocess.list2cmdline(gh_cmd)}")
        return
    step(f"Publishing {tag} to {RELEASES_REPO}")
    run(gh_cmd, "gh release create")
    step(f"Done — {tag} is live on {RELEASES_REPO}")


if __name__ == "__main__":
    main()
