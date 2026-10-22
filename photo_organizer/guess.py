"""Best guesses for undated photos, so Unsorted can be fixed a whole folder at a time.

A guess only picks the "Probably YYYY" folder inside Unsorted. It never
files anything into By Date.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .dates import EARLIEST_DIGITAL_YEAR

# A modified time must be at least this old to count as a hint.
MTIME_MIN_AGE = timedelta(days=30)
# Folders whose files all share a modified time within this many seconds were bulk-copied.
MTIME_SAME_WINDOW = 2.0

_SEQ_RE = re.compile(r"^(.*?)(\d+)$")


@dataclass
class GuessEntry:
    key: object            # caller's handle for the result
    folder: str            # inbox-relative source folder
    stem: str              # filename without extension
    model: str | None
    year: int | None       # trusted year if dated, else None
    mtime: float


def _seq(stem: str) -> tuple[str, int] | None:
    m = _SEQ_RE.match(stem)
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def compute_guesses(entries: list[GuessEntry], now: datetime) -> dict[object, tuple[str, str]]:
    """Return {key: (year, guess_source)} for undated entries that have a reasonable hint."""
    by_folder: dict[str, list[GuessEntry]] = defaultdict(list)
    for e in entries:
        by_folder[e.folder].append(e)

    guesses: dict[object, tuple[str, str]] = {}
    for folder_entries in by_folder.values():
        dated = [e for e in folder_entries if e.year is not None]
        undated = [e for e in folder_entries if e.year is None]
        if not undated:
            continue

        # Majority year of dated photos in this folder.
        majority: int | None = None
        if len(dated) >= 2:
            year, count = Counter(e.year for e in dated).most_common(1)[0]
            if count * 2 > len(dated):
                majority = year

        # Bulk copy check: every file has the same modified time.
        mtimes = [e.mtime for e in folder_entries]
        bulk_copied = len(mtimes) > 1 and max(mtimes) - min(mtimes) <= MTIME_SAME_WINDOW

        for e in undated:
            if (y := _neighbor_year(e, dated)) is not None:
                guesses[e.key] = (str(y), "neighbors")
            elif majority is not None:
                guesses[e.key] = (str(majority), "folder-majority")
            elif not bulk_copied:
                mt = datetime.fromtimestamp(e.mtime)
                if mt < now - MTIME_MIN_AGE and EARLIEST_DIGITAL_YEAR <= mt.year <= now.year:
                    guesses[e.key] = (str(mt.year), "file-modified-time")
    return guesses


def _neighbor_year(e: GuessEntry, dated: list[GuessEntry]) -> int | None:
    """Undated DSC_0412 between dated DSC_0411 and DSC_0415 from the same camera."""
    me = _seq(e.stem)
    if not me:
        return None
    below = above = None
    for d in dated:
        if d.model != e.model:
            continue
        s = _seq(d.stem)
        if not s or s[0] != me[0]:
            continue
        if s[1] < me[1] and (below is None or s[1] > below[0]):
            below = (s[1], d.year)
        elif s[1] > me[1] and (above is None or s[1] < above[0]):
            above = (s[1], d.year)
    if below and above and below[1] == above[1]:
        return below[1]
    return None
