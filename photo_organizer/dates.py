"""Dates: parsing, sanity checks, and the folder/file naming they drive.

Pure Python, no I/O. A wrong date is worse than no date, so every parser
here returns None when it isn't sure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

PRECISIONS = ("exact", "day", "month", "year", "decade")

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_LOOKUP: dict[str, int] = {}
for _i, _m in enumerate(MONTHS, start=1):
    _MONTH_LOOKUP[_m.lower()] = _i
    _MONTH_LOOKUP[_m[:3].lower()] = _i
_MONTH_LOOKUP["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTH_LOOKUP, key=len, reverse=True))

# Earliest plausible date for a *digital* file's own metadata or filename.
EARLIEST_DIGITAL_YEAR = 1990
# Earliest year we accept from a folder name or a DATE folder.
EARLIEST_FOLDER_YEAR = 1900

# Days cameras fall back to after a clock reset. Any time on these days is rejected.
RESET_DEFAULT_DAYS = {(1970, 1, 1), (1980, 1, 1), (2000, 1, 1)}
# Jan 1, first hour, repeated across this many photos from one camera in a batch.
RESET_REPEAT_THRESHOLD = 3

# Scanners and scanning apps (matched case-insensitively against EXIF
# Make, Model and Software). Keep this small and edit freely.
SCANNER_WORDS = [
    "epson", "fastfoto", "vuescan", "photoscan", "scansnap", "canoscan",
    "lide", "scanjet", "plustek", "silverfast", "doxie", "scanner",
]


@dataclass(frozen=True)
class FuzzyDate:
    """A date known to some precision. For 'decade', year is the decade start."""

    precision: str
    year: int
    month: int = 1
    day: int = 1
    hour: int = 0
    minute: int = 0
    second: int = 0

    # ---- conversions ----
    def iso(self) -> str:
        p = self.precision
        if p == "exact":
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}T{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
        if p == "day":
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if p == "month":
            return f"{self.year:04d}-{self.month:02d}"
        if p == "year":
            return f"{self.year:04d}"
        return f"{self.year:04d}s"

    @classmethod
    def from_iso(cls, s: str | None, precision: str | None = None) -> "FuzzyDate | None":
        if not s:
            return None
        if s.endswith("s"):
            return cls("decade", int(s[:4]))
        if "T" in s:
            dt = datetime.fromisoformat(s[:19])
            return cls("exact", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
        bits = [int(b) for b in s.split("-")]
        if len(bits) == 3:
            return cls("day", *bits)
        if len(bits) == 2:
            return cls("month", *bits)
        return cls("year", bits[0])

    @classmethod
    def from_datetime(cls, dt: datetime) -> "FuzzyDate":
        return cls("exact", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

    def as_datetime(self) -> datetime:
        return datetime(self.year, self.month, self.day, self.hour, self.minute, self.second)

    # ---- naming ----
    def year_folder(self) -> str:
        """By date subfolder: '2009', or '1990s' for a decade."""
        return f"{self.year}s" if self.precision == "decade" else str(self.year)

    def name_prefix(self) -> str:
        if self.precision == "exact":
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}_{self.hour:02d}-{self.minute:02d}-{self.second:02d}"
        return self.iso()

    # ---- comparisons ----
    def fits_folder(self, folder: "FuzzyDate") -> bool:
        """True if this date agrees with a (less precise) folder date."""
        if folder.precision == "decade":
            return folder.year <= self.year < folder.year + 10
        if self.precision == "decade":
            return False
        if self.year != folder.year:
            return False
        if folder.precision == "month":
            return self.precision not in ("year",) and self.month == folder.month
        return True


# ---------------------------------------------------------------------------
# DATE - folders (Mom's own statement of the date)
# ---------------------------------------------------------------------------

def _valid(year: int, month: int = 1, day: int = 1) -> bool:
    try:
        datetime(year, month, day)
    except ValueError:
        return False
    return True


def _not_future(d: FuzzyDate, now: datetime) -> bool:
    if d.precision == "decade":
        return d.year <= now.year
    if d.year > now.year:
        return False
    if d.year == now.year and d.precision in ("month", "day", "exact") and d.month > now.month:
        return False
    if (d.year, d.month) == (now.year, now.month) and d.precision in ("day", "exact") and d.day > now.day:
        return False
    return True


def parse_date_text(text: str, now: datetime | None = None) -> FuzzyDate | None:
    """Parse the date part of a 'DATE - ...' folder. None if unsure."""
    now = now or datetime.now()
    # Finder stores a "/" typed in a name as ":" on disk, so treat them alike.
    t = text.strip().lower().replace(",", " ").replace(":", "/")
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    result: FuzzyDate | None = None

    if m := re.fullmatch(r"'?(\d{2})s", t):  # 90s, '90s
        yy = int(m.group(1))
        if yy % 10 == 0:
            century = now.year // 100 * 100
            year = century + yy
            if year > now.year:
                year -= 100
            result = FuzzyDate("decade", year)
    elif m := re.fullmatch(r"(\d{4})'?s", t):  # 1990s
        if int(m.group(1)) % 10 == 0:
            result = FuzzyDate("decade", int(m.group(1)))
    elif m := re.fullmatch(r"(\d{4})", t):
        result = FuzzyDate("year", int(m.group(1)))
    elif m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})", t):  # 2009-06
        result = FuzzyDate("month", int(m.group(1)), int(m.group(2)))
    elif m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", t):  # 6/2009
        result = FuzzyDate("month", int(m.group(2)), int(m.group(1)))
    elif m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t):  # 2009-07-04
        result = FuzzyDate("day", int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t):  # 7/4/2009 (US)
        result = FuzzyDate("day", int(m.group(3)), int(m.group(1)), int(m.group(2)))
    elif m := re.fullmatch(rf"({_MONTH_RE})\.? (\d{{4}})", t):  # June 2009
        result = FuzzyDate("month", int(m.group(2)), _MONTH_LOOKUP[m.group(1)])
    elif m := re.fullmatch(rf"({_MONTH_RE})\.? (\d{{1,2}}) (\d{{4}})", t):  # July 4 2009
        result = FuzzyDate("day", int(m.group(3)), _MONTH_LOOKUP[m.group(1)], int(m.group(2)))
    elif m := re.fullmatch(rf"(\d{{1,2}}) ({_MONTH_RE})\.? (\d{{4}})", t):  # 4 July 2009
        result = FuzzyDate("day", int(m.group(3)), _MONTH_LOOKUP[m.group(2)], int(m.group(1)))

    if result is None:
        return None
    if result.year < EARLIEST_FOLDER_YEAR or not _valid(result.year, result.month, result.day):
        return None
    if not _not_future(result, now):
        return None
    return result


# ---------------------------------------------------------------------------
# Folder-name hints ("Christmas 2009", "Old Laptop/2004/Disneyland")
# ---------------------------------------------------------------------------

def folder_name_hint(name: str, now: datetime | None = None) -> FuzzyDate | None:
    """Year (and month if present) from one folder name. Standalone 4-digit years only."""
    now = now or datetime.now()
    n = name.lower()
    candidates = [
        (r"(?<!\d)(\d{4})[-_.](\d{1,2})(?!\d)", lambda m: (int(m[1]), int(m[2]))),
        (r"(?<![\d.\-/])(\d{1,2})[-_./](\d{4})(?!\d)", lambda m: (int(m[2]), int(m[1]))),
        (rf"\b({_MONTH_RE})\.?[ _-]+(\d{{4}})(?!\d)", lambda m: (int(m[2]), _MONTH_LOOKUP[m[1]])),
        (rf"(?<!\d)(\d{{4}})[ _-]+({_MONTH_RE})\b", lambda m: (int(m[1]), _MONTH_LOOKUP[m[2]])),
    ]
    for pattern, pick in candidates:
        if m := re.search(pattern, n):
            year, month = pick(m)
            if EARLIEST_FOLDER_YEAR <= year <= now.year and 1 <= month <= 12:
                d = FuzzyDate("month", year, month)
                if _not_future(d, now):
                    return d
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", n):
        year = int(m.group(1))
        if EARLIEST_FOLDER_YEAR <= year <= now.year:
            return FuzzyDate("year", year)
    return None


def path_hint(folder_names: list[str], now: datetime | None = None) -> FuzzyDate | None:
    """Deepest folder in the path that has a year wins."""
    for name in reversed(folder_names):
        if d := folder_name_hint(name, now):
            return d
    return None


def is_bare_date_name(name: str, now: datetime | None = None) -> bool:
    """True for folder names that are just a date ('2004', 'June 2009', '2009-06')."""
    return parse_date_text(name, now) is not None


# ---------------------------------------------------------------------------
# Metadata and filename dates
# ---------------------------------------------------------------------------

def parse_exif_datetime(value: str | None) -> FuzzyDate | None:
    """'2009:06:14 10:22:05' -> exact date. Offsets are kept separately."""
    if not value:
        return None
    v = str(value).strip().replace("\x00", "")
    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", v)
    if not m:
        return None
    parts = [int(x) for x in m.groups()]
    try:
        dt = datetime(*parts)
    except ValueError:
        return None
    return FuzzyDate.from_datetime(dt)


def parse_iso_with_offset(value: str) -> tuple[FuzzyDate, str | None] | None:
    """Apple's '2026-07-14T15:30:22-0700' -> (local exact date, '-07:00')."""
    m = re.match(
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?",
        value.strip(),
    )
    if not m:
        return None
    try:
        dt = datetime(*[int(x) for x in m.groups()[:6]])
    except ValueError:
        return None
    tz = m.group(7)
    if tz and tz != "Z" and ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    if tz == "Z":
        tz = "+00:00"
    return FuzzyDate.from_datetime(dt), tz


def _dt(*parts) -> datetime | None:
    try:
        return datetime(*[int(p) for p in parts])
    except ValueError:
        return None


def date_from_filename(filename: str) -> FuzzyDate | None:
    """Dates in common camera, phone and app filenames."""
    stem = filename.rsplit(".", 1)[0]
    # Screenshot 2026-07-14 at 3.30.22 PM / WhatsApp Image 2026-07-14 at 15.30.22
    if m := re.search(
        r"(\d{4})-(\d{2})-(\d{2}) at (\d{1,2})\.(\d{2})\.(\d{2})(?:\s*([AaPp])\.?[Mm])?", stem
    ):
        y, mo, d, h, mi, s, ampm = m.groups()
        h = int(h)
        if ampm:
            if h > 12:
                return None
            h = h % 12 + (12 if ampm.lower() == "p" else 0)
        if dt := _dt(y, mo, d, h, mi, s):
            return FuzzyDate.from_datetime(dt)
        return None
    # 2026-07-14 15.30.22 / 2026-07-14_15-30-22
    if m := re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[ _T](\d{2})[.\-:](\d{2})[.\-:](\d{2})(?!\d)", stem):
        if dt := _dt(*m.groups()):
            return FuzzyDate.from_datetime(dt)
        return None
    # IMG_20260714_153022, PXL_20260714_153022123, 20260714_153022, Screenshot_20260714-153022
    if m := re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})", stem):
        if dt := _dt(*m.groups()):
            return FuzzyDate.from_datetime(dt)
        return None
    # IMG-20260714-WA0001 (WhatsApp on Android): day only
    if m := re.search(r"(?:IMG|VID|AUD)-(\d{4})(\d{2})(\d{2})-WA\d+", stem, re.IGNORECASE):
        if _dt(*m.groups()):
            y, mo, d = (int(x) for x in m.groups())
            return FuzzyDate("day", y, mo, d)
    return None


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def is_scanner(*fields: str | None) -> bool:
    text = " ".join(f for f in fields if f).lower()
    return any(word in text for word in SCANNER_WORDS)


def is_reset_candidate(d: FuzzyDate) -> bool:
    """Jan 1 in the first hour: suspicious only if it repeats (see batch check)."""
    return d.precision == "exact" and d.month == 1 and d.day == 1 and d.hour == 0


def sanity_reject(d: FuzzyDate, now: datetime) -> str | None:
    """Reason to reject a metadata/filename date on its own, or None if it looks fine."""
    if d.as_datetime() > now + timedelta(days=1):
        return "future"
    if d.year < EARLIEST_DIGITAL_YEAR:
        return "too-early"
    if (d.year, d.month, d.day) in RESET_DEFAULT_DAYS:
        return "camera-reset"
    return None


def year_gap(a: FuzzyDate, b: FuzzyDate) -> float:
    """Rough distance in years between two dates, using the middle of fuzzy ranges."""
    def mid(d: FuzzyDate) -> float:
        if d.precision == "decade":
            return d.year + 5
        if d.precision == "year":
            return d.year + 0.5
        return d.year + (d.month - 0.5) / 12
    return abs(mid(a) - mid(b))


def with_precision(d: FuzzyDate, precision: str) -> FuzzyDate:
    return replace(d, precision=precision)
