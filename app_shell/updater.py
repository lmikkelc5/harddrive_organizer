"""Fetch and install newer sorting code from GitHub Releases.

Rules (see README "Updates"):
- Only published releases count (GitHub's "latest release"; drafts and
  pre-releases are ignored), never ordinary pushes.
- A release carries photo_organizer-code.zip + photo_organizer-code.zip.sha256.
- Anything unexpected (offline, slow, bad checksum, odd zip, code that needs
  a newer shell) means: keep using what we already have. Never raise.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field

from . import SHELL_API

log = logging.getLogger("app_shell")

REPO = "lmikkelc5/harddrive_organizer"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CODE_ASSET = "photo_organizer-code.zip"
SHA_ASSET = CODE_ASSET + ".sha256"
PACKAGE = "photo_organizer"
KEEP_VERSIONS = 3

# Overrides for tests and CI (a local "release" served from files).
ENV_HOME = "ORGANIZE_PHOTOS_HOME"
ENV_SOURCE = "ORGANIZE_PHOTOS_UPDATE_SOURCE"
ENV_DISABLE = "ORGANIZE_PHOTOS_NO_UPDATE"


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def home_dir() -> str:
    if os.environ.get(ENV_HOME):
        return os.environ[ENV_HOME]
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Organize photos")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Organize photos")
    return os.path.expanduser("~/.local/share/organize-photos")


# ---------------------------------------------------------------------------
# Network: the system curl (uses the Mac's own certificate store, so HTTPS
# works inside a frozen app without bundling certificates).
# ---------------------------------------------------------------------------

def curl_fetch(url: str, timeout: float) -> bytes:
    cmd = ["curl", "-fsSL", "--max-time", str(int(timeout)), "-H", "User-Agent: organize-photos-updater", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError(f"couldn't run curl: {e}") from e
    if proc.returncode != 0:
        raise UpdateError(f"curl failed ({proc.returncode}) for {url}: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class State:
    bad: list[str] = field(default_factory=list)   # versions that failed to start

    @classmethod
    def load(cls, home: str) -> "State":
        try:
            with open(os.path.join(home, "state.json"), encoding="utf-8") as f:
                data = json.load(f)
            return cls(bad=[str(v) for v in data.get("bad", [])])
        except (OSError, ValueError):
            return cls()

    def save(self, home: str) -> None:
        os.makedirs(home, exist_ok=True)
        tmp = os.path.join(home, "state.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"bad": self.bad}, f)
        os.replace(tmp, os.path.join(home, "state.json"))


def code_dir(home: str) -> str:
    return os.path.join(home, "code")


def installed_versions(home: str) -> dict[tuple[int, ...], str]:
    """version tuple -> folder holding photo_organizer/ for that version."""
    out = {}
    root = code_dir(home)
    if os.path.isdir(root):
        for name in os.listdir(root):
            v = parse_version(name)
            if v and os.path.isfile(os.path.join(root, name, PACKAGE, "__init__.py")):
                out[v] = os.path.join(root, name)
    return out


# ---------------------------------------------------------------------------
# Check + install
# ---------------------------------------------------------------------------

def latest_release(fetch, source: str) -> tuple[str, str, str]:
    """(tag, code zip url, sha256 url) of the latest published release."""
    data = json.loads(fetch(source, 8).decode("utf-8"))
    tag = data.get("tag_name", "")
    urls = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    if CODE_ASSET not in urls or SHA_ASSET not in urls:
        raise UpdateError(f"release {tag} has no {CODE_ASSET}")
    return tag, urls[CODE_ASSET], urls[SHA_ASSET]


def _safe_members(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for info in z.infolist():
        name = info.filename
        if name.startswith("/") or ".." in name.split("/") or "\\" in name or ":" in name:
            raise UpdateError(f"unsafe path in zip: {name}")
        if not (name == "update.json" or name.startswith(PACKAGE + "/")):
            raise UpdateError(f"unexpected file in zip: {name}")
        members.append(info)
    return members


def install(home: str, tag: str, data: bytes, expected_sha: str) -> str:
    """Verify and unpack a code zip into code/<version>/. Returns that folder."""
    version = parse_version(tag)
    if not version:
        raise UpdateError(f"bad tag {tag!r}")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        raise UpdateError(f"checksum mismatch for {tag}")
    staging = os.path.join(code_dir(home), f".{tag}.partial")
    final = os.path.join(code_dir(home), ".".join(map(str, version)))
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    try:
        zpath = os.path.join(staging, "code.zip")
        with open(zpath, "wb") as f:
            f.write(data)
        with zipfile.ZipFile(zpath) as z:
            members = _safe_members(z)
            meta = json.loads(z.read("update.json").decode("utf-8"))
            if parse_version(str(meta.get("version"))) != version:
                raise UpdateError(f"zip says version {meta.get('version')}, tag says {tag}")
            if int(meta.get("requires_shell", 1)) > SHELL_API:
                raise UpdateError(f"{tag} needs a newer app (shell {meta.get('requires_shell')} > {SHELL_API})")
            z.extractall(staging, members)
        os.remove(zpath)
        if not os.path.isfile(os.path.join(staging, PACKAGE, "__init__.py")):
            raise UpdateError("zip has no photo_organizer/__init__.py")
        shutil.rmtree(final, ignore_errors=True)
        os.rename(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def _cleanup(home: str, keep: tuple[int, ...] | None) -> None:
    versions = sorted(installed_versions(home))
    old = [v for v in versions[:-KEEP_VERSIONS] if v != keep]
    for v in old:
        shutil.rmtree(installed_versions(home)[v], ignore_errors=True)


def check_for_update(bundled: tuple[int, ...], home: str | None = None, fetch=curl_fetch,
                     source: str | None = None) -> None:
    """Download + install a newer release if there is one. Never raises."""
    home = home or home_dir()
    source = source or os.environ.get(ENV_SOURCE) or LATEST_URL
    try:
        state = State.load(home)
        tag, code_url, sha_url = latest_release(fetch, source)
        version = parse_version(tag)
        if not version:
            raise UpdateError(f"release tag {tag!r} isn't a version")
        vtext = ".".join(map(str, version))
        if version <= bundled or vtext in state.bad or version in installed_versions(home):
            log.info("No update needed (latest release %s, bundled %s)", tag, ".".join(map(str, bundled)))
            return
        sha = fetch(sha_url, 15).decode("utf-8").split()[0].strip().lower()
        folder = install(home, tag, fetch(code_url, 60), sha)
        log.info("Installed update %s into %s", tag, folder)
        _cleanup(home, version)
    except Exception as e:  # offline, GitHub down, bad release: keep what we have
        log.warning("Update check skipped: %s", e)


def candidates(bundled: tuple[int, ...], home: str | None = None) -> list[tuple[tuple[int, ...], str]]:
    """Installed versions newer than the bundled code and not marked bad, newest first."""
    home = home or home_dir()
    bad = set(State.load(home).bad)
    good = [(v, p) for v, p in installed_versions(home).items()
            if v > bundled and ".".join(map(str, v)) not in bad]
    return sorted(good, reverse=True)


def mark_bad(version: tuple[int, ...], home: str | None = None) -> None:
    home = home or home_dir()
    try:
        state = State.load(home)
        text = ".".join(map(str, version))
        if text not in state.bad:
            state.bad.append(text)
        state.save(home)
    except OSError as e:
        log.warning("Couldn't record bad version: %s", e)
