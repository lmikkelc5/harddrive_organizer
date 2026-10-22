"""Import: inbox files -> dated, deduplicated, moved, and recorded in the catalog."""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from . import dates, guess, names
from .catalog import Catalog
from .fileops import FileOps, free_name, sha256_file
from .labels import FolderContext, Label, folder_context
from .layout import Drive
from .metadata import DateCandidate, Meta, kind_for, read_meta

log = logging.getLogger(__name__)

# Files modified more recently than this may still be copying.
SETTLE_SECONDS = 15
LIVE_PHOTO_IMAGE_EXTS = {".heic", ".heif", ".jpg", ".jpeg"}
LIVE_PHOTO_VIDEO_EXTS = {".mov"}
_EDIT_RE = re.compile(r"^([A-Za-z]+)_E(\d+)$")
_AAE_ORIG_RE = re.compile(r"^([A-Za-z]+)_O(\d+)$")


def is_junk(name: str) -> bool:
    return name == ".DS_Store" or name.startswith("._")


def is_hidden(name: str) -> bool:
    return name.startswith(".")


@dataclass(eq=False)
class SourceFile:
    abs_path: str
    rel_dirs: list[str]          # inbox-relative folders, outermost first
    ctx: FolderContext
    origin: str                  # path shown in the catalog as original_inbox_path
    name: str = ""
    stem: str = ""
    ext: str = ""
    kind: str = ""
    size: int = 0
    mtime: float = 0.0
    sha: str | None = None
    meta: Meta = field(default_factory=Meta)

    def __post_init__(self) -> None:
        self.name = os.path.basename(self.abs_path)
        self.stem, ext = os.path.splitext(self.name)
        self.ext = ext.lower()
        self.kind = kind_for(self.name)
        st = os.stat(self.abs_path)
        self.size, self.mtime = st.st_size, st.st_mtime

    @property
    def folder_key(self) -> str:
        return "/".join(self.rel_dirs)


@dataclass(eq=False)
class Item:
    """One thing Mom thinks of as 'a photo': the photo, its Live Photo video, edits, sidecars."""

    primary: SourceFile
    live_video: SourceFile | None = None
    edits: list["Item"] = field(default_factory=list)
    sidecars: list[SourceFile] = field(default_factory=list)
    decision: "DateDecision | None" = None


@dataclass
class DateDecision:
    date: dates.FuzzyDate | None
    source: str | None = None
    tz: str | None = None
    raw_meta_date: str | None = None
    reject_reason: str | None = None
    conflict: str | None = None
    bad_date_folder: str | None = None
    best_guess: str | None = None
    guess_source: str | None = None


@dataclass
class ImportResult:
    photos: int = 0
    videos: int = 0
    unsorted: int = 0
    duplicates: int = 0
    not_photos: int = 0
    failed: int = 0
    still_copying: int = 0
    updated_labels: list[str] = field(default_factory=list)
    unreadable_date_folders: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_inbox(drive: Drive, now: datetime) -> tuple[list[SourceFile], int]:
    """Return (ready files, number of files still being copied)."""
    files: list[SourceFile] = []
    recent = 0
    cutoff = now.timestamp() - SETTLE_SECONDS
    if not os.path.isdir(drive.inbox):
        return files, 0
    ctx_cache: dict[tuple[str, ...], FolderContext] = {}
    for dirpath, dirnames, filenames in os.walk(drive.inbox):
        dirnames[:] = sorted(d for d in dirnames if not is_hidden(d)
                             and not os.path.islink(os.path.join(dirpath, d)))
        rel = os.path.relpath(dirpath, drive.inbox)
        rel_dirs = [] if rel == "." else rel.replace(os.sep, "/").split("/")
        key = tuple(rel_dirs)
        if key not in ctx_cache:
            ctx_cache[key] = folder_context(rel_dirs, now)
        for fn in sorted(filenames):
            if is_hidden(fn) or is_junk(fn):
                continue
            path = os.path.join(dirpath, fn)
            if os.path.islink(path):
                log.info("Skipping symlink in inbox: %s", path)
                continue
            try:
                if os.stat(path).st_mtime > cutoff:
                    recent += 1
                    continue
                origin = "/".join([names.INBOX, *rel_dirs, fn])
                files.append(SourceFile(path, rel_dirs, ctx_cache[key], origin))
            except OSError as e:
                log.warning("Can't read %s: %s", path, e)
    return files, recent


def group_items(files: list[SourceFile]) -> tuple[list[Item], list[SourceFile], list[SourceFile]]:
    """Group into (media items, loose sidecars, non-photo files)."""
    by_folder: dict[str, list[SourceFile]] = defaultdict(list)
    for f in files:
        by_folder[f.folder_key].append(f)

    items: list[Item] = []
    loose_sidecars: list[SourceFile] = []
    others: list[SourceFile] = []
    for folder_files in by_folder.values():
        images = {f.stem.lower(): f for f in folder_files if f.kind == "photo"}
        videos = {f.stem.lower(): f for f in folder_files if f.kind == "video"}
        used: set[int] = set()

        def make_item(img: SourceFile) -> Item:
            item = Item(img)
            used.add(id(img))
            vid = videos.get(img.stem.lower())
            if vid and img.ext in LIVE_PHOTO_IMAGE_EXTS and vid.ext in LIVE_PHOTO_VIDEO_EXTS:
                item.live_video = vid
                used.add(id(vid))
            return item

        by_stem: dict[str, Item] = {}
        edit_images = []
        for stem, img in sorted(images.items()):
            m = _EDIT_RE.match(img.stem)
            if m and f"{m.group(1)}_{m.group(2)}".lower() in images:
                edit_images.append((f"{m.group(1)}_{m.group(2)}".lower(), img))
                continue
            by_stem[stem] = make_item(img)
        for orig_stem, img in edit_images:
            by_stem[orig_stem].edits.append(make_item(img))

        for f in folder_files:
            if f.kind == "video" and id(f) not in used:
                items.append(Item(f))
                used.add(id(f))
        items.extend(by_stem.values())

        for f in folder_files:
            if f.kind == "sidecar":
                stem = f.stem
                if m := _AAE_ORIG_RE.match(stem):
                    stem = f"{m.group(1)}_{m.group(2)}"
                owner = by_stem.get(stem.lower())
                if owner:
                    owner.sidecars.append(f)
                else:
                    loose_sidecars.append(f)
            elif f.kind == "other":
                others.append(f)
    # Originals before files named like copies, so "IMG_1 copy.JPG" is the one called a duplicate.
    items.sort(key=lambda it: (looks_like_copy(it.primary.stem), it.primary.abs_path))
    others.sort(key=lambda f: (looks_like_copy(f.stem), f.abs_path))
    return items, loose_sidecars, others


_COPY_RE = re.compile(r"(\s+copy(\s+\d+)?|\s*\(\d+\)|-\d)$", re.IGNORECASE)


def looks_like_copy(stem: str) -> bool:
    """'IMG_1 copy', 'IMG_1 copy 2', 'IMG_1 (1)', 'IMG_1-1'."""
    return bool(_COPY_RE.search(stem))


# ---------------------------------------------------------------------------
# Dating
# ---------------------------------------------------------------------------

def suspicious_resets(items: list[Item]) -> set[tuple[str | None, int]]:
    """(camera model, year) pairs with several Jan-1-first-hour timestamps in this batch."""
    counts: dict[tuple[str | None, int], int] = defaultdict(int)
    for it in items:
        for c in it.primary.meta.candidates[:1]:
            if dates.is_reset_candidate(c.date):
                counts[(it.primary.meta.model, c.date.year)] += 1
    return {k for k, n in counts.items() if n >= dates.RESET_REPEAT_THRESHOLD}


def decide_date(f: SourceFile, now: datetime, suspicious: set) -> DateDecision:
    meta = f.meta
    candidates: list[DateCandidate] = list(meta.candidates)
    if fn_date := dates.date_from_filename(f.name):
        candidates.append(DateCandidate(fn_date, "filename"))
    scanner = dates.is_scanner(meta.make, meta.model, meta.software)

    trusted: DateCandidate | None = None
    rejected: tuple[DateCandidate, str] | None = None
    for c in candidates:
        reason = "scanner" if scanner else dates.sanity_reject(c.date, now)
        if not reason and dates.is_reset_candidate(c.date) and (meta.model, c.date.year) in suspicious:
            reason = "camera-reset"
        if reason:
            rejected = rejected or (c, reason)
            continue
        trusted = c
        break

    raw = rejected[0].date.iso() if rejected else None
    reason = rejected[1] if rejected else None
    ctx = f.ctx

    if ctx.date:  # Mom's DATE folder beats everything
        d = DateDecision(ctx.date, "date-folder", raw_meta_date=(trusted.date.iso() if trusted else raw),
                         reject_reason=None if trusted else reason)
        if trusted and dates.year_gap(trusted.date, ctx.date) > 1:
            d.conflict = f"DATE folder {ctx.date.iso()} vs {trusted.source} {trusted.date.iso()}"
            log.info("DATE folder overrides metadata for %s: %s", f.origin, d.conflict)
        return d
    if ctx.bad_date_folder:
        return DateDecision(None, raw_meta_date=raw, reject_reason=reason, bad_date_folder=ctx.bad_date_folder)
    if trusted:
        d = DateDecision(trusted.date, trusted.source, trusted.tz_offset, raw_meta_date=raw, reject_reason=reason)
        if ctx.hint and dates.year_gap(trusted.date, ctx.hint) > 1:
            d.conflict = f"folder name {ctx.hint.iso()} vs {trusted.source} {trusted.date.iso()}"
        return d
    if ctx.hint:
        return DateDecision(ctx.hint, "folder-name", raw_meta_date=raw, reject_reason=reason)
    return DateDecision(None, raw_meta_date=raw, reject_reason=reason)


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------

class Importer:
    def __init__(self, drive: Drive, cat: Catalog, ops: FileOps, now: datetime | None = None,
                 tz=None) -> None:
        self.drive = drive
        self.cat = cat
        self.ops = ops
        self.now = now or datetime.now()
        self.tz = tz
        self.result = ImportResult()
        self._batch_hashes: set[str] = set()
        self._labels_touched: dict[int, str] = {}

    # ---- public ----
    def run(self, files: list[SourceFile], progress=None) -> ImportResult:
        items, loose_sidecars, others = group_items(files)
        media = [f for it in items for f in self._all_files(it)]
        if progress:
            progress(len(items))

        for f in media:
            try:
                f.sha = sha256_file(f.abs_path)
            except OSError as e:
                log.warning("Can't read %s: %s", f.abs_path, e)
            f.meta = read_meta(f.abs_path, self.tz)

        suspicious = suspicious_resets(items)
        for it in items:
            self._decide(it, suspicious)
        self._guess(items)

        for it in items:
            self._import_item(it)
        for f in loose_sidecars:
            self._import_sidecar(f, None)
        for f in others:
            self._import_other(f)

        for folder in sorted({it.decision.bad_date_folder for it in items if it.decision.bad_date_folder}):
            self.result.unreadable_date_folders.append(folder)
        self.result.updated_labels = sorted(set(self._labels_touched.values()), key=str.casefold)
        return self.result

    # ---- helpers ----
    @staticmethod
    def _all_files(it: Item) -> list[SourceFile]:
        out = [it.primary] + ([it.live_video] if it.live_video else [])
        for e in it.edits:
            out += Importer._all_files(e)
        return out

    def _decide(self, it: Item, suspicious: set) -> None:
        it.decision = decide_date(it.primary, self.now, suspicious)
        for e in it.edits:
            e.decision = it.decision  # edits sit next to their original

    def _guess(self, items: list[Item]) -> None:
        entries = []
        for it in items:
            d = it.decision
            year = d.date.year if d.date and d.date.precision != "decade" else None
            if d.bad_date_folder:
                continue  # don't guess when Mom gave a date we couldn't read
            entries.append(guess.GuessEntry(it, it.primary.folder_key, it.primary.stem,
                                            it.primary.meta.model, year, it.primary.mtime))
        for it, (year, source) in guess.compute_guesses(entries, self.now).items():
            if it.decision.date is None:
                it.decision.best_guess, it.decision.guess_source = year, source
                for e in it.edits:
                    e.decision = it.decision

    def _destination_folder(self, it: Item) -> str:
        d = it.decision
        if d.date:
            return os.path.join(self.drive.by_date, d.date.year_folder())
        group = names.probably(d.best_guess) if d.best_guess else names.DATE_UNKNOWN
        return os.path.join(self.drive.unsorted, group, *it.primary.rel_dirs)

    def _stem_for(self, it: Item, base: str | None) -> str:
        d = it.decision
        if base is not None:  # an edit of `base`
            return f"{base}_edited" if d.date else it.primary.stem
        if not d.date:
            return it.primary.stem
        if d.date.precision == "exact":
            return d.date.name_prefix()
        return f"{d.date.name_prefix()} {it.primary.stem}"

    def _ext(self, f: SourceFile, it: Item) -> str:
        return f.ext if it.decision.date else os.path.splitext(f.name)[1]

    def _is_duplicate(self, f: SourceFile) -> bool:
        if f.sha is None:
            return False
        if f.sha in self._batch_hashes:
            return True
        row = self.cat.photo_by_hash(f.sha)
        return bool(row and row["status"] == "ok")

    def _move_to_duplicates(self, f: SourceFile) -> None:
        folder = os.path.join(self.drive.duplicates, *f.rel_dirs)
        stem = free_name(self.ops, folder, f.stem, [os.path.splitext(f.name)[1]])
        dst = os.path.join(folder, stem + os.path.splitext(f.name)[1])
        self._move(f, dst, "duplicate")
        self.cat.log_event("duplicate", f"{f.origin} -> {self.drive.rel(dst)}")
        self.cat.commit()

    def _move(self, f: SourceFile, dst: str, reason: str) -> None:
        self.ops.move(f.abs_path, dst)
        self.cat.record_move(self.drive.rel(f.abs_path), self.drive.rel(dst), reason)

    def _import_item(self, it: Item, base: str | None = None, original_id: int | None = None) -> None:
        files = [it.primary] + ([it.live_video] if it.live_video else [])
        try:
            fresh = []
            for f in files:
                if f.sha is None:
                    self.result.failed += 1
                elif self._is_duplicate(f):
                    self._move_to_duplicates(f)
                    if f is it.primary:
                        self.result.duplicates += 1
                else:
                    fresh.append(f)
                if f.sha:
                    self._batch_hashes.add(f.sha)

            folder = self._destination_folder(it)
            stem = free_name(self.ops, folder, self._stem_for(it, base), [self._ext(f, it) for f in files])
            ids: dict[int, int] = {}
            for f in fresh:
                dst = os.path.join(folder, stem + self._ext(f, it))
                self._move(f, dst, "import")
                ids[id(f)] = self._record(f, it, dst, original_id if f is it.primary else None)
                self.cat.commit()
                if f is it.primary or not it.live_video:
                    self._count(f, it)
            if it.live_video and len(ids) == 2:
                pid, vid = ids[id(it.primary)], ids[id(it.live_video)]
                self.cat.update_photo(pid, pair_id=vid)
                self.cat.update_photo(vid, pair_id=pid)
            primary_id = ids.get(id(it.primary))
            if primary_id is None and it.primary.sha:
                row = self.cat.photo_by_hash(it.primary.sha)
                primary_id = row["id"] if row else None
            for sc in it.sidecars:
                self._import_sidecar(sc, primary_id)
            self.cat.commit()
        except Exception:
            log.exception("Couldn't import %s", it.primary.abs_path)
            self.result.failed += sum(1 for f in files if os.path.exists(f.abs_path))
            self.cat.commit()
            return
        for e in it.edits:
            self._import_item(e, base=stem, original_id=primary_id)

    def _count(self, f: SourceFile, it: Item) -> None:
        if f.kind == "video":
            self.result.videos += 1
        else:
            self.result.photos += 1
        if not it.decision.date:
            self.result.unsorted += 1

    def _record(self, f: SourceFile, it: Item, dst: str, edited_of: int | None) -> int:
        d = it.decision
        st = os.stat(dst) if not self.ops.dry_run else None
        fields = dict(
            rel_path=self.drive.rel(dst),
            original_name=f.name,
            original_inbox_path=f.origin,
            kind=f.kind,
            taken_at=d.date.iso() if d.date else None,
            tz_offset=d.tz,
            date_source=d.source,
            date_precision=d.date.precision if d.date else "unknown",
            raw_meta_date=d.raw_meta_date,
            reject_reason=d.reject_reason,
            date_conflict=d.conflict,
            best_guess=d.best_guess,
            guess_source=d.guess_source,
            gps_lat=f.meta.gps_lat,
            gps_lon=f.meta.gps_lon,
            camera_make=f.meta.make,
            camera_model=f.meta.model,
            size=st.st_size if st else f.size,
            mtime=st.st_mtime if st else f.mtime,
            status="ok",
            edited_of_id=edited_of,
        )
        existing = self.cat.photo_by_hash(f.sha)
        if existing:  # re-import of a photo that had gone missing: revive it
            fields.pop("original_name"), fields.pop("original_inbox_path")
            self.cat.update_photo(existing["id"], **fields)
            photo_id = existing["id"]
        else:
            photo_id = self.cat.add_photo(sha256=f.sha, **fields)
        for label in f.ctx.labels:
            self._apply_label(photo_id, label)
        return photo_id

    def _apply_label(self, photo_id: int, label: Label) -> None:
        lid = self.cat.get_or_create_label(label.group, label.name)
        if self.cat.add_label(photo_id, lid):
            self._labels_touched[lid] = self.cat.label(lid)["label"]

    def _import_sidecar(self, f: SourceFile, photo_id: int | None) -> None:
        try:
            ext = os.path.splitext(f.name)[1]
            stem = free_name(self.ops, self.drive.sidecars, f.stem, [ext])
            dst = os.path.join(self.drive.sidecars, stem + ext)
            self._move(f, dst, "sidecar")
            self.cat.add_sidecar(photo_id=photo_id, rel_path=self.drive.rel(dst),
                                 original_name=f.name, original_inbox_path=f.origin)
            self.cat.commit()
        except Exception:
            log.exception("Couldn't move sidecar %s", f.abs_path)
            self.result.failed += 1

    def _import_other(self, f: SourceFile) -> None:
        try:
            f.sha = sha256_file(f.abs_path)
            if self._is_duplicate(f):
                self._move_to_duplicates(f)
                self.result.duplicates += 1
                return
            self._batch_hashes.add(f.sha)
            folder = os.path.join(self.drive.unsorted, names.NOT_PHOTOS, *f.rel_dirs)
            ext = os.path.splitext(f.name)[1]
            stem = free_name(self.ops, folder, f.stem, [ext])
            dst = os.path.join(folder, stem + ext)
            self._move(f, dst, "not-photo")
            st = os.stat(dst) if not self.ops.dry_run else None
            fields = dict(rel_path=self.drive.rel(dst), original_name=f.name, original_inbox_path=f.origin,
                          kind="other", size=st.st_size if st else f.size,
                          mtime=st.st_mtime if st else f.mtime, status="ok")
            existing = self.cat.photo_by_hash(f.sha)
            if existing:
                self.cat.update_photo(existing["id"], **fields)
            else:
                self.cat.add_photo(sha256=f.sha, **fields)
            self.cat.commit()
            self.result.not_photos += 1
        except Exception:
            log.exception("Couldn't move %s", f.abs_path)
            self.result.failed += 1


def cleanup_inbox(drive: Drive, ops: FileOps) -> None:
    """Remove inbox subfolders that are now empty (ignoring Finder junk files)."""
    if not os.path.isdir(drive.inbox):
        return
    for dirpath, dirnames, filenames in os.walk(drive.inbox, topdown=False):
        if os.path.samefile(dirpath, drive.inbox):
            continue
        try:
            entries = os.listdir(dirpath)
        except OSError:
            continue
        if all(is_junk(e) and os.path.isfile(os.path.join(dirpath, e)) for e in entries):
            for e in entries:
                ops.remove_junk(os.path.join(dirpath, e))
            ops.rmdir_if_empty(dirpath)
