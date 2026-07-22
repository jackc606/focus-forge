"""Build and publish a Focus Forge release (developer tool — not shipped).

Reads the version from core/version.py (single source of truth), syncs it into
installer.iss and pyproject.toml, builds the PyInstaller folder, compiles the
Inno Setup installer, writes SHA256SUMS.txt, and publishes everything as a
GitHub Release on the public releases repo (the app's auto-updater polls it).

Usage (from the project root):
    python packaging/release.py [--notes-file NOTES.md] [--dry-run] [--site]

Release notes come from --notes-file, or fall back to this version's entry in
core/changelog.py (title + bullet list). --dry-run does everything except the
final `gh release create` (and the site deploy). --site also refreshes
focusforgemod.com after publishing: site.ts version/download-link/size and a
generated changelog.ts entry, then npm build + wrangler deploy + git push —
one command, app release and website together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASES_REPO = "jackc606/focus-forge-releases"
DOWNLOAD_BASE = f"https://github.com/{RELEASES_REPO}/releases/latest/download"

# The marketing/docs site (SvelteKit + Cloudflare Pages). Deploys are direct
# CLI uploads — a git push alone does NOT update the live site.
SITE_ROOT = Path(os.environ.get("FOCUSFORGE_SITE_ROOT",
                                r"C:\Users\jackc\focusforgemod"))
CF_ACCOUNT_ID = "4dfc02a6e88a1a24733bd2cd056327e6"

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


def run(cmd: list, what: str, cwd: Path = ROOT, env: dict | None = None) -> None:
    print(f"$ {subprocess.list2cmdline(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=cwd, env=env)
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


def commit_version_sync(version: str) -> None:
    """Commit the installer.iss/pyproject.toml sync this script wrote — it was
    left uncommitted after every release and had to be mopped up by hand."""
    step("Committing version-sync files")
    r = subprocess.run(["git", "diff", "--quiet", "--",
                        "installer.iss", "pyproject.toml"], cwd=ROOT)
    if r.returncode == 0:
        print("  nothing to commit (already in sync)")
        return
    run(["git", "add", "installer.iss", "pyproject.toml"], "git add")
    run(["git", "commit", "-m",
         f"Sync installer.iss + pyproject.toml to {version} (release.py)"],
        "git commit")


# ----- website refresh (--site) ------------------------------------------------

def _site_ts_updated(text: str, version: str, installer_name: str,
                     size_mb: int) -> str:
    """site.ts with version / downloadUrl / installerName / installerSize
    pointed at this release. The download URL embeds the VERSIONED filename —
    forgetting this bump 404s the button as soon as 'latest' moves."""
    subs = [
        (r"(version: ')[^']*(')", rf"\g<1>{version}\g<2>"),
        (r"(downloadUrl:\s*')[^']*(')",
         rf"\g<1>{DOWNLOAD_BASE}/{installer_name}\g<2>"),
        (r"(installerName: ')[^']*(')", rf"\g<1>{installer_name}\g<2>"),
        (r"(installerSize: ')[^']*(')", rf"\g<1>~{size_mb} MB\g<2>"),
    ]
    for pattern, repl in subs:
        text, n = re.subn(pattern, repl, text, count=1)
        if n == 0:
            fail(f"site.ts: pattern not found: {pattern}")
    return text


def _format_site_entry(entry: dict) -> str:
    """One changelog.ts Release block from a core/changelog.py entry. Notes go
    through json.dumps — valid TS string literals, safely escaped."""
    lines = ["  {",
             f"    version: '{entry['version']}',",
             f"    date: '{entry['date']}',",
             "    stage: 'pre-alpha',",
             "    current: true,",
             "    notes: ["]
    lines += [f"      {json.dumps(note)}," for note in entry.get("changes", [])]
    lines += ["    ]", "  },"]
    return "\n".join(lines)


def _changelog_ts_updated(text: str, entry: dict) -> str:
    """changelog.ts with this release prepended and the previous entry's
    ``current`` flag moved. Idempotent: an existing entry is left alone."""
    if f"version: '{entry['version']}'" in text:
        print(f"  changelog.ts already has {entry['version']} — leaving it")
        return text
    anchor = "export const releases: Release[] = [\n"
    if anchor not in text:
        fail("changelog.ts: releases array anchor not found")
    text = text.replace("\n    current: true,", "", 1)
    return text.replace(anchor, anchor + _format_site_entry(entry) + "\n", 1)


def deploy_site(version: str, setup: Path, entry: dict, dry_run: bool) -> None:
    step("Refreshing focusforgemod.com")
    if not SITE_ROOT.is_dir():
        fail(f"site repo not found: {SITE_ROOT} (set FOCUSFORGE_SITE_ROOT)")
    site_ts = SITE_ROOT / "src" / "lib" / "site.ts"
    changelog_ts = SITE_ROOT / "src" / "lib" / "data" / "changelog.ts"
    size_mb = round(setup.stat().st_size / (1024 * 1024))
    new_site = _site_ts_updated(site_ts.read_text(encoding="utf-8"),
                                version, setup.name, size_mb)
    new_changelog = _changelog_ts_updated(
        changelog_ts.read_text(encoding="utf-8"), entry)
    if dry_run:
        print("  dry run — would update site.ts + changelog.ts, npm build, "
              "wrangler deploy, git push")
        return
    site_ts.write_text(new_site, encoding="utf-8")
    changelog_ts.write_text(new_changelog, encoding="utf-8")
    print(f"  site.ts -> {version} ({setup.name}, ~{size_mb} MB); "
          f"changelog.ts entry added")

    npm = shutil.which("npm")
    npx = shutil.which("npx")
    if not npm or not npx:
        fail("npm/npx not found on PATH — needed for --site.")
    run([npm, "run", "build"], "site build", cwd=SITE_ROOT)
    env = dict(os.environ, CLOUDFLARE_ACCOUNT_ID=CF_ACCOUNT_ID)
    run([npx, "wrangler", "pages", "deploy", ".svelte-kit/cloudflare",
         "--project-name=focusforgemod", "--branch=main"],
        "wrangler deploy", cwd=SITE_ROOT, env=env)
    run(["git", "add", "-A"], "site git add", cwd=SITE_ROOT)
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=SITE_ROOT)
    if r.returncode != 0:
        run(["git", "commit", "-m", f"Site refresh for v{version} (release.py)"],
            "site git commit", cwd=SITE_ROOT)
        run(["git", "push", "origin", "main"], "site git push", cwd=SITE_ROOT)
    print("  site refreshed, deployed, and pushed")


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
                        help="Do everything except `gh release create` (and "
                             "the site deploy).")
    parser.add_argument("--site", action="store_true",
                        help="Also refresh focusforgemod.com after publishing: "
                             "site.ts + changelog.ts, npm build, wrangler "
                             "deploy, git push.")
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
    sys.path.insert(0, str(ROOT))
    from core.changelog import CHANGELOG  # noqa: PLC0415 (needs ROOT on path)
    entry = next((e for e in CHANGELOG if e.get("version") == version), None)

    if args.dry_run:
        step("Dry run — skipping publish")
        print(f"  would run: {subprocess.list2cmdline(gh_cmd)}")
        if args.site and entry:
            deploy_site(version, setup, entry, dry_run=True)
        return
    step(f"Publishing {tag} to {RELEASES_REPO}")
    run(gh_cmd, "gh release create")
    commit_version_sync(version)
    if args.site:
        if entry is None:
            fail(f"--site needs a core/changelog.py entry for {version}.")
        deploy_site(version, setup, entry, dry_run=False)
    step(f"Done — {tag} is live on {RELEASES_REPO}"
         + (" and focusforgemod.com" if args.site else ""))


if __name__ == "__main__":
    main()
