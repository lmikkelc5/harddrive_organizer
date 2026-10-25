"""Every name and message Mom can see, in one place.

Change wording here and nowhere else.
"""

from __future__ import annotations

APP_NAME = "Organize Photos"

# --- Folders on the drive -------------------------------------------------
INBOX = "Put New Photos Here"
LIBRARY = "My Photos"
BY_DATE = "By Date"
UNSORTED = "Unsorted"
DUPLICATES = "Duplicates (safe to delete)"
ALBUMS = "Albums"
DATE_UNKNOWN = "Date Unknown"
NOT_PHOTOS = "Not Photos"
HOW_TO_FIX_FILE = "How to fix these.txt"

# Hidden app data (Mom never opens this).
APP_DATA = ".photo-organizer"
DRIVE_MARKER = "drive-marker"
CATALOG = "catalog.db"
CATALOG_BACKUPS = "catalog-backups"
SIDECARS = "sidecars"
LOGS = "logs"
LOCK = "lock"
LABEL_ID_FILE = ".label-id"

# Group word used for plain folders (no dash) that become albums.
ALBUM_GROUP = "Album"
# Reserved group word that sets a date instead of making a view.
DATE_GROUP = "Date"


def probably(year: str) -> str:
    """Unsorted subfolder for a best guess, e.g. 'Probably 2008'."""
    return f"Probably {year}"


def group_folder(group: str) -> str:
    """Top-level view folder for a group word: 'Trip' -> 'By Trip'."""
    if group == ALBUM_GROUP:
        return ALBUMS
    return f"By {group}"


HOW_TO_FIX_TEXT = (
    'Folders under "Probably 2008" (and so on) are our best guess. If one looks '
    "right, drag it into that year in By Date.\n\n"
    "Know roughly when the others were taken? Drag them into the right year "
    "folder in By Date.\n\n"
    "Organize Photos will remember.\n"
)

# --- Dialog messages ------------------------------------------------------
MSG_NOTHING_TO_DO = (
    'There\'s nothing to sort yet. Drag photos into the "Put New Photos Here" '
    "folder on your photo drive, then open Organize Photos again."
)
MSG_NO_DRIVE = "I can't find your photo drive. Plug it in, wait a few seconds, and try again."
MSG_ALREADY_RUNNING = "Organize Photos is already working. Give it a minute."
MSG_UNEXPECTED_ERROR = (
    "Something went wrong, but none of your photos were lost. Anything that "
    'wasn\'t sorted is still in "Put New Photos Here." Please let Mikkel know.'
)


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def items_word(photos: int, videos: int) -> str:
    """'photos', 'videos', or 'photos and videos' for the summary."""
    if photos and videos:
        return "photos and videos"
    if videos:
        return "videos" if videos != 1 else "video"
    return "photo" if photos == 1 else "photos"


def msg_starting(n: int) -> str:
    return f"Sorting {n} photos — this may take a few minutes."


def msg_still_copying_only(n: int) -> str:
    return (
        f"{_count(n, 'file')} {'is' if n == 1 else 'are'} still being copied into "
        '"Put New Photos Here." Wait a minute, then open Organize Photos again.'
    )


def msg_summary(s) -> str:
    """Build the end-of-run message from a RunSummary."""
    parts: list[str] = []
    sorted_n = s.sorted_photos + s.sorted_videos
    if sorted_n:
        word = items_word(s.sorted_photos, s.sorted_videos)
        parts.append(f"All done! {sorted_n} {word} sorted into My Photos.")
    else:
        parts.append("All done!")
    if s.updated_labels:
        parts.append("Updated: " + ", ".join(s.updated_labels) + ".")
    if s.unsorted:
        verb = "didn't have a date, so it's" if s.unsorted == 1 else "didn't have a date, so they're"
        parts.append(f"{_count(s.unsorted, 'photo')} {verb} in My Photos ▸ Unsorted.")
    for folder in s.unreadable_date_folders:
        parts.append(
            f'I couldn\'t read the date in "{folder}", so those photos are in Unsorted.'
        )
    if s.duplicates:
        parts.append(
            f"{_count(s.duplicates, 'photo')} {'was' if s.duplicates == 1 else 'were'} "
            "already in My Photos, so the extra "
            f"{'copy is' if s.duplicates == 1 else 'copies are'} in "
            "Duplicates (safe to delete)."
        )
    if s.not_photos:
        parts.append(
            f"{_count(s.not_photos, 'file')} {'wasn' if s.not_photos == 1 else 'weren'}'t "
            "a photo or video, so "
            f"{"it's" if s.not_photos == 1 else "they're"} in My Photos ▸ Unsorted ▸ Not Photos."
        )
    if s.still_copying:
        parts.append(
            f"{_count(s.still_copying, 'file')} {'was' if s.still_copying == 1 else 'were'} "
            "still being copied, so I left "
            f"{'it' if s.still_copying == 1 else 'them'} for next time."
        )
    if s.failed:
        parts.append(
            f"{_count(s.failed, 'file')} couldn't be sorted and "
            f"{'is' if s.failed == 1 else 'are'} still in \"Put New Photos Here.\" "
            "Please let Mikkel know."
        )
    if s.drive_percent_full is not None and s.drive_percent_full > 90:
        parts.append(
            f"Heads-up: your photo drive is almost full ({s.drive_percent_full}%). "
            "Please let Mikkel know."
        )
    return " ".join(parts)
