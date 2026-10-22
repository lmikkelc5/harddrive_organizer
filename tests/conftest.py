"""Test helpers: fake drives, generated photos with known EXIF, tiny videos."""

from __future__ import annotations

import itertools
import os
import sqlite3
import time
from datetime import datetime

import pytest
from PIL import Image

from photo_organizer import names
from photo_organizer.fileops import symlinks_supported
from photo_organizer.layout import Drive
from photo_organizer.run import message_for, organize
from photo_organizer.testdrive.media import build_exif, heif_available, save_image, video_bytes

_counter = itertools.count(1)

OLD = 3600  # seconds; files older than the 15 s "still copying" window


HEIF_OK = heif_available()
needs_heif = pytest.mark.skipif(not HEIF_OK, reason="pillow-heif can't load here")

_probe = os.path.join(os.path.dirname(__file__), "..", ".pytest-symlink-probe")
SYMLINKS_OK = symlinks_supported(os.path.abspath(_probe))
try:
    os.rmdir(os.path.abspath(_probe))
except OSError:
    pass
needs_symlinks = pytest.mark.skipif(not SYMLINKS_OK, reason="symlinks not supported here (Windows without Developer Mode)")


def set_age(path: str, seconds: float = OLD) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


def make_image(path: str, dto: str | None = None, *, age: float = OLD, **exif_fields) -> str:
    """Write a small unique image with the given EXIF (see testdrive.media.build_exif)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = next(_counter)
    img = Image.new("RGB", (16, 16), (n % 256, (n // 256) % 256, 77))
    # A unique description keeps bytes unique even when pixels compress the same.
    save_image(path, img, build_exif(dto, description=f"test image {n}", **exif_fields))
    set_age(path, age)
    return path


def make_video(path: str, apple_date: str | None = None, utc: datetime | None = None,
               model: str | None = None, age: float = OLD) -> str:
    """A minimal QuickTime file with mvhd creation time and/or Apple creationdate metadata."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(video_bytes(apple_date, utc, model, unique=next(_counter).to_bytes(8, "big")))
    set_age(path, age)
    return path


def make_file(path: str, content: bytes | None = None, age: float = OLD) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content if content is not None else f"file {next(_counter)}".encode())
    set_age(path, age)
    return path


class FakeUI:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.notes: list[str] = []

    def info(self, m): self.infos.append(m)
    def error(self, m): self.errors.append(m)
    def notify(self, m): self.notes.append(m)


class DriveHelper(Drive):
    def inbox_path(self, *parts: str) -> str:
        return os.path.join(self.inbox, *parts)

    def lib(self, *parts: str) -> str:
        return os.path.join(self.library, *parts)

    def organize(self, dry_run: bool = False, now: datetime | None = None, tz=None):
        self.ui = FakeUI()
        summary = organize(self, self.ui, dry_run=dry_run, now=now, tz=tz)
        self.ui.info(message_for(summary))
        return summary

    def db(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.catalog)
        con.row_factory = sqlite3.Row
        return con

    def row(self, **where):
        clause = " AND ".join(f"{k} = ?" for k in where)
        with self.db() as con:
            return con.execute(f"SELECT * FROM photos WHERE {clause}", tuple(where.values())).fetchone()

    def files(self, under: str | None = None) -> list[str]:
        """Real files (not symlinks, not hidden) under My Photos, relative, sorted."""
        top = under or self.library
        out = []
        for dp, dn, fn in os.walk(top):
            dn[:] = [d for d in dn if not d.startswith(".")]
            for f in fn:
                p = os.path.join(dp, f)
                if not f.startswith(".") and not os.path.islink(p):
                    out.append(os.path.relpath(p, top).replace(os.sep, "/"))
        return sorted(out)


@pytest.fixture
def drive(tmp_path) -> DriveHelper:
    d = DriveHelper(str(tmp_path / "Family Photos"))
    os.makedirs(d.inbox)
    return d


__all__ = ["make_image", "make_video", "make_file", "FakeUI", "needs_symlinks", "needs_heif", "names", "set_age"]
