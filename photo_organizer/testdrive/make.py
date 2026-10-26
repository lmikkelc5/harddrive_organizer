"""`make`: build a fake drive with an inbox full of scenarios, plus expected.json."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timedelta

from .. import names
from .features import TEST_TIMEZONE
from .media import build_exif, heif_available, save_image, story_image, video_bytes
from .scenarios import COLORS, DEFAULT_MTIME, INBOX, Spec, all_scenarios, big_specs, expected_summary

MANIFEST = "expected.json"


class NotATestDrive(Exception):
    pass


def _looks_like_test_drive(folder: str) -> bool:
    return os.path.exists(os.path.join(folder, MANIFEST))


def prepare_folder(folder: str, reset: bool) -> None:
    if os.path.exists(folder) and os.listdir(folder):
        if not reset:
            raise NotATestDrive(f"{folder} isn't empty. Use --reset to rebuild a test drive.")
        if not _looks_like_test_drive(folder):
            # Never wipe a folder we didn't make (it could be a real drive).
            raise NotATestDrive(f"{folder} has no {MANIFEST}, so it isn't a test drive. Not deleting it.")
        shutil.rmtree(folder)
    os.makedirs(folder, exist_ok=True)


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _mtime(spec: Spec, now: datetime) -> float:
    if spec.mtime == "default":
        return DEFAULT_MTIME.timestamp()
    if spec.mtime == "future":
        return (now + timedelta(days=1)).timestamp()
    if spec.mtime == "yesterday":
        return (now - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
    return spec.mtime.timestamp()


def _unavailable(spec: Spec, heif_ok: bool) -> str | None:
    if spec.requires == "heif" and not heif_ok:
        return "pillow-heif can't load on this computer, so HEIC files can't be made"
    if spec.requires == "macos" and sys.platform != "darwin":
        return "only possible on macOS (Finder-style ':' in a folder name)"
    return None


def _write(spec: Spec, path: str, made: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if spec.kind == "image":
        exp = spec.expect
        where = f"{exp.get('dir', '?')}/{exp.get('name') or '(original name)'}"
        size = (320, 240) if spec.feature == "big" else (640, 480)
        img = story_image([spec.feature, spec.id, "Expected:", where.replace("My photos/", "")],
                          COLORS.get(spec.feature, (60, 60, 60)), size)
        save_image(path, img, build_exif(description=f"test-drive {spec.id}", **spec.exif))
    elif spec.kind == "video":
        data = video_bytes(unique=f"test-drive {spec.id}".encode(), **spec.video)
        with open(path, "wb") as f:
            f.write(data)
    elif spec.kind == "copy":
        shutil.copyfile(made[spec.copy_of], path)
    elif spec.kind in ("bytes", "junk"):
        with open(path, "wb") as f:
            f.write(spec.content if spec.content is not None else b"\x00\x05\x16\x07junk")
    else:
        raise ValueError(spec.kind)


def write_spec(folder: str, spec: Spec, made: dict[str, str], now: datetime) -> dict | None:
    """Write one scenario file into the inbox; return its manifest entry."""
    path = os.path.join(folder, INBOX, *spec.source.split("/"))
    _write(spec, path, made)
    t = _mtime(spec, now)
    os.utime(path, (t, t))
    made[spec.id] = path
    if spec.kind == "junk":
        return None
    return dict(id=spec.id, feature=spec.feature, phase=spec.phase,
                source=f"{INBOX}/{spec.source}", sha256=_sha(path), expect=spec.expect)


def make(folder: str, reset: bool = False, now: datetime | None = None, big: int = 0) -> dict:
    now = now or datetime.now()
    prepare_folder(folder, reset)
    os.makedirs(os.path.join(folder, names.APP_DATA), exist_ok=True)
    with open(os.path.join(folder, names.APP_DATA, names.DRIVE_MARKER), "w") as f:
        f.write(f"{uuid.UUID(int=0x7E57)}\ntest drive\n")
    os.makedirs(os.path.join(folder, names.LIBRARY), exist_ok=True)
    os.makedirs(os.path.join(folder, INBOX), exist_ok=True)

    specs, checks = all_scenarios(now)
    specs += big_specs(big)
    heif_ok = heif_available()
    made: dict[str, str] = {}
    files, skipped, generated = [], [], []
    for spec in specs:
        reason = _unavailable(spec, heif_ok)
        if reason:
            skipped.append(dict(id=spec.id, feature=spec.feature, reason=reason, phase="all"))
            continue
        entry = write_spec(folder, spec, made, now)
        generated.append(spec)
        if entry:
            files.append(entry)

    manifest = dict(
        version=1,
        made_at=now.isoformat(timespec="seconds"),
        big=big,
        timezone=TEST_TIMEZONE,
        run_command=f'python -m photo_organizer --drive "{folder}" --timezone {TEST_TIMEZONE}',
        summary={"first-run": expected_summary(generated)},
        files=files,
        checks=[c.__dict__ for c in checks],
        skipped=skipped,
    )
    with open(os.path.join(folder, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest
