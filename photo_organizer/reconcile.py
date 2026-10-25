"""Make the catalog match what's really in By Date and Unsorted.

Mom may move, rename, delete or copy files in Finder. We never move them
back; we update the catalog to follow her.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from . import dates, names
from .catalog import Catalog
from .fileops import sha256_file
from .layout import Drive
from .metadata import kind_for, read_meta

log = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"^(\d{4})$")
_DECADE_RE = re.compile(r"^(\d{3}0)s$")
_MONTH_RE = re.compile(r"^(\d{1,2})\s*-\s*([A-Za-z]+)$")


@dataclass
class ReconcileReport:
    moved: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    copies: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


def folder_date(lib_parts: list[str], now: datetime | None = None) -> dates.FuzzyDate | str | None:
    """What a file's place in My Photos says about its date.

    lib_parts: path relative to My Photos, including the filename.
    Returns a FuzzyDate, "unsorted", or None (location says nothing).
    """
    now = now or datetime.now()
    if not lib_parts:
        return None
    if lib_parts[0] == names.UNSORTED:
        return "unsorted"
    if lib_parts[0] != names.BY_DATE:
        return None
    found: dates.FuzzyDate | None = None
    for part in lib_parts[1:-1]:
        if (m := _YEAR_RE.match(part)) and dates.EARLIEST_FOLDER_YEAR <= int(m.group(1)) <= now.year:
            found = dates.FuzzyDate("year", int(m.group(1)))
        elif m := _DECADE_RE.match(part):
            found = dates.FuzzyDate("decade", int(m.group(1)))
        elif (m := _MONTH_RE.match(part)) and found and found.precision in ("year", "month"):
            month = int(m.group(1))
            if 1 <= month <= 12 and m.group(2).lower()[:3] == dates.MONTHS[month - 1].lower()[:3]:
                found = dates.FuzzyDate("month", found.year, month)
    return found


def walk_library_files(drive: Drive) -> dict[str, tuple[int, float]]:
    """rel_path -> (size, mtime) for real files in By Date and Unsorted."""
    out: dict[str, tuple[int, float]] = {}
    for top in (drive.by_date, drive.unsorted):
        if not os.path.isdir(top):
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                p = os.path.join(dirpath, fn)
                if os.path.islink(p):
                    continue
                if fn == names.HOW_TO_FIX_FILE and os.path.samefile(dirpath, drive.unsorted):
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out[drive.rel(p)] = (st.st_size, st.st_mtime)
    return out


def _lib_parts(drive: Drive, rel_path: str) -> list[str]:
    return drive.lib_rel(drive.abs(rel_path))


def date_update_for_location(row, drive: Drive, new_rel: str, now: datetime) -> dict:
    """Catalog fields to change because of where a file now sits. Her placement wins."""
    where = folder_date(_lib_parts(drive, new_rel), now)
    if where == "unsorted":
        old_where = folder_date(_lib_parts(drive, row["rel_path"]), now) if row["rel_path"] else None
        if row["taken_at"] is None and old_where == "unsorted":
            return {}
        return dict(taken_at=None, tz_offset=None, date_precision="unknown", date_source="manual")
    if isinstance(where, dates.FuzzyDate):
        current = dates.FuzzyDate.from_iso(row["taken_at"])
        if current and current.fits_folder(where):
            return {}
        return dict(taken_at=where.iso(), tz_offset=None, date_precision=where.precision,
                    date_source="manual", best_guess=None, guess_source=None)
    return {}


def reconcile(drive: Drive, cat: Catalog, now: datetime | None = None) -> ReconcileReport:
    now = now or datetime.now()
    report = ReconcileReport()
    disk = walk_library_files(drive)
    rows = cat.photos()
    ok_by_path = {r["rel_path"]: r for r in rows if r["status"] == "ok"}

    # Known files that changed on disk (edited in Preview, etc.): re-hash.
    for rel, row in ok_by_path.items():
        if rel in disk and (row["size"], row["mtime"]) != disk[rel]:
            size, mtime = disk[rel]
            try:
                sha = sha256_file(drive.abs(rel))
            except OSError:
                continue
            other = cat.photo_by_hash(sha)
            if other and other["id"] != row["id"]:
                log.info("%s now matches another catalog entry; leaving catalog as is", rel)
                cat.update_photo(row["id"], size=size, mtime=mtime)
            else:
                cat.update_photo(row["id"], sha256=sha, size=size, mtime=mtime)
                report.changed.append(rel)

    missing_ids = {r["id"] for r in rows if r["status"] == "missing"}
    missing_ids |= {r["id"] for rel, r in ok_by_path.items() if rel not in disk}

    unknown = sorted(p for p in disk if p not in ok_by_path)
    for rel in unknown:
        size, mtime = disk[rel]
        cached = cat.known_copy(rel)
        if cached and (cached["size"], cached["mtime"]) == (size, mtime):
            sha = cached["sha256"]
        else:
            try:
                sha = sha256_file(drive.abs(rel))
            except OSError as e:
                log.warning("Can't read %s: %s", rel, e)
                continue
        row = cat.photo_by_hash(sha)
        if row and row["id"] in missing_ids:
            # She moved or renamed it. Follow her.
            fields = date_update_for_location(row, drive, rel, now)
            cat.update_photo(row["id"], rel_path=rel, status="ok", size=size, mtime=mtime, **fields)
            cat.record_move(row["rel_path"], rel, "manual")
            cat.log_event("manual-move", f"{row['rel_path']} -> {rel}")
            missing_ids.discard(row["id"])
            report.moved.append(rel)
        elif row:
            # A copy she made. Leave it, don't catalog it twice.
            if not cached:
                cat.log_event("copy", f"{rel} is a copy of {row['rel_path']}")
                log.info("%s is a copy of %s; leaving it alone", rel, row["rel_path"])
            cat.remember_copy(rel, sha, size, mtime)
            report.copies.append(rel)
        else:
            # A new file she put straight into My Photos.
            abs_path = drive.abs(rel)
            meta = read_meta(abs_path)
            where = folder_date(_lib_parts(drive, rel), now)
            fd = where if isinstance(where, dates.FuzzyDate) else None
            date, source, tz = fd, ("manual" if fd else None), None
            # If the photo's own date agrees with the folder it's in, keep the
            # more precise one (e.g. a phone photo dropped into By Date/2019, or
            # a file whose catalog record was lost in a power cut mid-import).
            if fd and meta.candidates:
                c = meta.candidates[0]
                if (not dates.sanity_reject(c.date, now) and not dates.is_scanner(meta.make, meta.model, meta.software)
                        and c.date.fits_folder(fd)):
                    date, source, tz = c.date, c.source, c.tz_offset
            cat.add_photo(
                sha256=sha, rel_path=rel, original_name=os.path.basename(rel),
                original_inbox_path=None, kind=kind_for(rel),
                taken_at=date.iso() if date else None, date_precision=date.precision if date else "unknown",
                date_source=source, tz_offset=tz,
                gps_lat=meta.gps_lat, gps_lon=meta.gps_lon,
                camera_make=meta.make, camera_model=meta.model,
                size=size, mtime=mtime, status="ok",
            )
            cat.log_event("manual-add", rel)
            report.added.append(rel)

    for pid in missing_ids:
        row = cat.photo(pid)
        if row["status"] != "missing":
            cat.update_photo(pid, status="missing")
            cat.log_event("missing", row["rel_path"])
            report.missing.append(row["rel_path"])

    cat.forget_copies_not_in(disk)
    cat.commit()
    return report
