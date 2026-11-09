"""One run of Organize photos, start to finish, wrapped so nothing ever crashes at Mom."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import __version__, names
from .catalog import Catalog, backup_catalog
from .fileops import DryRunOps, FileOps, symlinks_supported
from .importer import Importer, cleanup_inbox, scan_inbox
from .layout import Drive
from .reconcile import reconcile
from .system import AlreadyRunning, RunLock
from .views import adopt_view_changes, sync_views

log = logging.getLogger("photo_organizer")

BIG_BATCH = 50
KEEP_LOGS = 30


@dataclass
class RunSummary:
    sorted_photos: int = 0
    sorted_videos: int = 0
    unsorted: int = 0
    duplicates: int = 0
    not_photos: int = 0
    failed: int = 0
    still_copying: int = 0
    updated_labels: list[str] = field(default_factory=list)
    unreadable_date_folders: list[str] = field(default_factory=list)
    drive_percent_full: int | None = None
    views_enabled: bool = True
    nothing_to_do: bool = False


def _setup_logging(drive: Drive | None, verbose: bool, dry_run: bool) -> str | None:
    logger = logging.getLogger("photo_organizer")
    logger.setLevel(logging.DEBUG)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(console)
    if drive is None or dry_run:
        return None
    try:
        os.makedirs(drive.logs, exist_ok=True)
        path = os.path.join(drive.logs, f"run-{datetime.now():%Y%m%d-%H%M%S}.log")
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(fh)
        old = sorted(f for f in os.listdir(drive.logs) if f.startswith("run-"))
        for f in old[:-KEEP_LOGS]:
            os.remove(os.path.join(drive.logs, f))
        return path
    except OSError:
        return None


def write_error_report(drive: Drive | None, exc: BaseException) -> str:
    text = (
        f"{names.APP_NAME} {__version__} error report\n"
        f"time: {datetime.now().isoformat(timespec='seconds')}\n"
        f"python: {sys.version}\nplatform: {sys.platform}\n"
        f"drive: {drive.root if drive else 'not found'}\n\n"
        + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    )
    folders = [drive.logs] if drive else []
    folders.append(os.path.join(os.path.expanduser("~"), "Library", "Logs", names.APP_NAME)
                   if sys.platform == "darwin" else tempfile.gettempdir())
    for folder in folders:
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"error-{datetime.now():%Y%m%d-%H%M%S}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return path
        except OSError:
            continue
    return ""


def get_timezone(name: str | None):
    """A zoneinfo zone, or None for this computer's local zone."""
    if not name:
        return None
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)


def organize(drive: Drive, ui, dry_run: bool = False, now: datetime | None = None,
             tz=None) -> RunSummary:
    """Steps 3-9 of a run. The caller handles the lock and the final dialog."""
    now = now or datetime.now()
    ops: FileOps = DryRunOps(drive.root) if dry_run else FileOps(drive.root)
    summary = RunSummary()

    drive.ensure_layout(ops)
    if dry_run:
        cat = Catalog.in_memory_copy(drive.catalog)
    else:
        backup_catalog(drive.catalog, drive.backups)
        cat = Catalog(drive.catalog)
    try:
        cat.start_run(__version__)
        summary.views_enabled = symlinks_supported(drive.app_data) if not dry_run else True
        if not summary.views_enabled:
            log.warning("This drive can't hold symlinks (is it exFAT? It should be APFS). "
                        "Sorting by date only; By Trip / By event / Albums are skipped.")

        rec = reconcile(drive, cat, now)
        if rec.moved or rec.missing or rec.added or rec.copies:
            log.info("Reconcile: %d moved, %d missing, %d added by hand, %d copies",
                     len(rec.moved), len(rec.missing), len(rec.added), len(rec.copies))

        adopted = adopt_view_changes(drive, cat, ops) if summary.views_enabled else None

        files, summary.still_copying = scan_inbox(drive, now)
        if adopted:
            files += adopted.to_import
        if not files and summary.still_copying == 0:
            summary.nothing_to_do = True

        def progress(n: int) -> None:
            if n >= BIG_BATCH:
                ui.notify(names.msg_starting(n))

        result = Importer(drive, cat, ops, now, tz).run(files, progress)
        summary.sorted_photos, summary.sorted_videos = result.photos, result.videos
        summary.unsorted = result.unsorted
        summary.duplicates = result.duplicates
        summary.not_photos = result.not_photos
        summary.failed = result.failed
        summary.updated_labels = result.updated_labels
        summary.unreadable_date_folders = result.unreadable_date_folders
        if adopted:
            for label in adopted.labeled:
                if label not in summary.updated_labels:
                    summary.updated_labels.append(label)

        if summary.views_enabled:
            sync = sync_views(drive, cat, ops)
            log.info("Views: %d links created, %d removed", sync.created, sync.removed)

        cleanup_inbox(drive, ops)
        how_to = os.path.join(drive.unsorted, names.HOW_TO_FIX_FILE)
        if not ops.exists(how_to):
            ops.write_text(how_to, names.HOW_TO_FIX_TEXT)

        try:
            usage = shutil.disk_usage(drive.root)
            summary.drive_percent_full = round(usage.used * 100 / usage.total)
        except OSError:
            pass

        cat.finish_run(asdict(summary))
    finally:
        cat.close()

    if dry_run:
        print("\n".join(ops.actions) or "[dry-run] nothing would change")
    return summary


def message_for(summary: RunSummary) -> str:
    if summary.nothing_to_do:
        return names.MSG_NOTHING_TO_DO
    if summary.still_copying and not (summary.sorted_photos or summary.sorted_videos or summary.duplicates
                                      or summary.not_photos or summary.failed):
        return names.msg_still_copying_only(summary.still_copying)
    return names.msg_summary(summary)


def run(drive_root: str | None, ui, dry_run: bool = False, verbose: bool = False,
        finder=None, timezone: str | None = None) -> int:
    """The whole run. Returns an exit code; never raises."""
    drive: Drive | None = None
    try:
        if drive_root is None:
            from .system import find_drive
            drive_root = (finder or find_drive)()
        if drive_root is None or not os.path.isdir(drive_root):
            _setup_logging(None, verbose, dry_run)
            ui.error(names.MSG_NO_DRIVE)
            return 2
        drive = Drive(drive_root)
        log_path = _setup_logging(drive, verbose, dry_run)
        log.info("%s %s on %s (dry run: %s)", names.APP_NAME, __version__, drive.root, dry_run)
        if os.environ.get("ORGANIZE_PHOTOS_CODE"):
            log.info("Code: %s", os.environ["ORGANIZE_PHOTOS_CODE"])

        lock = RunLock(drive.lock)
        if not dry_run:
            try:
                lock.acquire()
            except AlreadyRunning:
                ui.info(names.MSG_ALREADY_RUNNING)
                return 3
        try:
            summary = organize(drive, ui, dry_run, tz=get_timezone(timezone))
        finally:
            lock.release()
        message = message_for(summary)
        log.info("Summary: %s", message)
        if log_path:
            log.info("Log: %s", log_path)
        ui.info(message)
        return 0 if not summary.failed else 1
    except Exception as exc:  # the one place everything is caught
        try:
            log.exception("Unexpected error")
            path = write_error_report(drive, exc)
            log.error("Error report written to %s", path)
        except Exception:
            pass
        try:
            ui.error(names.MSG_UNEXPECTED_ERROR)
        except Exception:
            pass
        return 1
