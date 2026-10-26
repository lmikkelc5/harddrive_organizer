"""The test-drive scenarios, as data. Expected results follow CLAUDE.md:
By date has year folders only; exact-time photos are renamed
YYYY-MM-DD_HH-MM-SS.ext; others get a date prefix ("2004 dl_1.jpg").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LIB = "My photos"
BY_DATE = f"{LIB}/By date"
UNSORTED = f"{LIB}/Unsorted"
DATE_UNKNOWN = f"{UNSORTED}/Date unknown"
DUPLICATES = f"{LIB}/Duplicates (safe to delete)"
SIDECARS = ".photo-organizer/sidecars"
INBOX = "Put new photos here"

# Every file gets this modified time unless a scenario says otherwise. It's
# old (so files aren't "still copying") and identical, so it never produces
# a modified-time guess on its own.
DEFAULT_MTIME = datetime(2026, 1, 15, 12, 0, 0)

COLORS = {
    "date-basic": (40, 90, 160),
    "iphone": (120, 60, 140),
    "sanity": (160, 50, 50),
    "guesses": (170, 120, 30),
    "folder-hints": (40, 130, 90),
    "labels": (20, 120, 140),
    "date-folders": (100, 100, 40),
    "edge": (90, 90, 90),
    "manual-edits": (150, 70, 100),
    "big": (60, 110, 60),
}


@dataclass
class Spec:
    id: str
    feature: str
    source: str                         # relative to Put new photos here/
    expect: dict
    kind: str = "image"                 # image | video | bytes | copy | junk
    exif: dict = field(default_factory=dict)
    video: dict = field(default_factory=dict)
    content: bytes | None = None
    copy_of: str | None = None
    mtime: object = "default"           # "default" | "future" | "yesterday" | datetime
    requires: str | None = None         # "heif" | "macos"
    counts: str | None = "photo"        # photo | video | duplicate | not_photo | still_copying | None
    unsorted: bool = False              # counts toward "didn't have a date"
    phase: str = "first-run"


@dataclass
class Check:
    """A check that isn't about one file.

    absent / present: a path must (not) exist. needs_links: only meaningful
    where symlinks work. inbox-only: the inbox holds exactly these files.
    label-count: exactly `count` labels match group + label (case-insensitively).
    links-healthy: every link under My photos points at a real file.
    copy: a copy Mom made is left alone and cataloged once (sha, path).
    """
    id: str
    feature: str
    type: str
    path: str | None = None
    files: list[str] | None = None
    group: str | None = None
    label: str | None = None
    count: int | None = None
    sha256: str | None = None
    needs_links: bool = False
    phase: str = "first-run"


# ---------------------------------------------------------------------------
# Small helpers so the tables below read like TEST_DRIVE.md
# ---------------------------------------------------------------------------

def exif_at(ts: str, **more) -> dict:
    """'2024-07-14 15:30:22' -> EXIF DateTimeOriginal fields."""
    return dict(dto=ts.replace("-", ":", 2), **more)


def exact(ts: str, ext: str = ".jpg", suffix: str = "", **more) -> dict:
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    return dict(dir=f"{BY_DATE}/{dt.year}", name=dt.strftime("%Y-%m-%d_%H-%M-%S") + suffix + ext,
                date=dt.isoformat(), precision="exact", **more)


def fuzzy(prefix: str, original: str, precision: str, **more) -> dict:
    """Dated by a DATE folder or folder name: date prefix + original name."""
    folder = prefix if precision == "decade" else prefix[:4]
    return dict(dir=f"{BY_DATE}/{folder}", name=f"{prefix} {original}", date=prefix,
                precision=precision, **more)


def unsorted(sub: str, name: str, **more) -> dict:
    return dict(dir=f"{UNSORTED}/{sub}", name=name, precision="unknown", **more)


def event(name: str) -> dict:
    return dict(labels=[f"Event: {name}"], links=[f"{LIB}/By event/{name}"])



# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------

def _date_basic() -> list[Spec]:
    f = "date-basic"
    apple = dict(make="Apple", model="iPhone 13")
    return [
        Spec("basic-exif", f, "IMG_0001.JPG", exif=exif_at("2024-07-14 15:30:22", **apple),
             expect=exact("2024-07-14 15:30:22", source="exif-original")),
        Spec("basic-heic-gps", f, "IMG_0002.HEIC", requires="heif",
             exif=exif_at("2025-03-08 09:05:00", make="Apple", model="iPhone 15", gps=(21.2769, -157.8268)),
             expect=exact("2025-03-08 09:05:00", ".heic", gps=[21.2769, -157.8268])),
        *[
            Spec(f"basic-burst-{i}", f, f"IMG_000{n}.JPG", exif=exif_at("2024-07-14 16:00:00", **apple),
                 expect=exact("2024-07-14 16:00:00", suffix=suffix))
            for i, (n, suffix) in enumerate([(3, ""), (4, "_2"), (5, "_3")], start=1)
        ],
        Spec("basic-screenshot", f, "Screenshot 2025-03-02 at 9.14.07 AM.png",
             expect=exact("2025-03-02 09:14:07", ".png", source="filename")),
        Spec("basic-whatsapp", f, "WhatsApp Image 2023-11-05 at 18.22.10.jpeg",
             expect=exact("2023-11-05 18:22:10", ".jpeg", source="filename")),
        Spec("basic-new-year", f, "IMG_0006.JPG", exif=exif_at("2020-01-01 00:00:30", make="Apple", model="iPhone 11"),
             expect=exact("2020-01-01 00:00:30")),
        Spec("basic-video-utc", f, "VID_0001.MP4", kind="video", counts="video",
             video=dict(utc=datetime(2024, 7, 14, 22, 30, 22, tzinfo=timezone.utc), brand=b"isom"),
             expect=exact("2024-07-14 15:30:22", ".mp4")),
    ]


def _iphone() -> list[Spec]:
    f = "iphone"
    ts = "2024-12-25 08:00:00"
    apple = dict(make="Apple", model="iPhone 15")
    return [
        Spec("iphone-live-photo", f, "IMG_1234.HEIC", requires="heif", exif=exif_at(ts, **apple),
             expect=exact(ts, ".heic", pair_with="iphone-live-video")),
        Spec("iphone-live-video", f, "IMG_1234.MOV", kind="video", counts=None, requires="heif",
             video=dict(apple_date="2024-12-25T08:00:00-0800", model="iPhone 15"),
             expect=exact(ts, ".mov", pair_with="iphone-live-photo")),
        Spec("iphone-edited", f, "IMG_E1234.HEIC", requires="heif", exif=exif_at(ts, **apple),
             expect=exact(ts, ".heic", suffix="_edited", edited_of="iphone-live-photo")),
        Spec("iphone-aae", f, "IMG_1234.AAE", kind="bytes", counts=None, requires="heif",
             content=b'<?xml version="1.0"?><plist version="1.0"><dict><key>adjustmentFormatVersion</key>'
                     b"<integer>1</integer></dict></plist>\n",
             expect=dict(dir=SIDECARS, name="IMG_1234.AAE", sidecar_of="iphone-live-photo")),
    ]


def _sanity(now: datetime) -> list[Spec]:
    f = "sanity"
    future = (now + timedelta(days=730)).replace(hour=12, minute=0, second=0, microsecond=0)
    specs = [
        Spec("sanity-scanner", f, "scan_001.jpg", unsorted=True,
             exif=exif_at("2021-05-01 10:00:00", make="EPSON", model="Perfection V600"),
             expect=unsorted("Date unknown", "scan_001.jpg", reject_reason="scanner")),
        *[
            Spec(f"sanity-reset-{i}", f, f"DSC0000{i}.JPG", unsorted=True,
                 exif=exif_at(f"2000-01-01 00:00:{sec}", make="SONY", model="DSC-W55"),
                 expect=unsorted("Date unknown", f"DSC0000{i}.JPG", reject_reason="camera-reset"))
            for i, sec in [(1, "05"), (2, "12"), (3, "40")]
        ],
        Spec("sanity-future", f, "IMG_0007.JPG", unsorted=True,
             exif=exif_at(future.strftime("%Y-%m-%d %H:%M:%S")),
             expect=unsorted("Date unknown", "IMG_0007.JPG", reject_reason="future")),
        Spec("sanity-no-clues", f, "photo.jpg", unsorted=True,
             expect=unsorted("Date unknown", "photo.jpg")),
    ]
    return specs


def _guesses(now: datetime) -> list[Spec]:
    f = "guesses"
    nikon = dict(make="NIKON CORPORATION", model="NIKON D90")
    yesterday = (now - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    specs = [
        Spec("guess-camping-410", f, "Camping/DSC_0410.JPG", exif=exif_at("2011-08-20 10:00:00", **nikon),
             expect=exact("2011-08-20 10:00:00", labels=[])),
        Spec("guess-camping-413", f, "Camping/DSC_0413.JPG", exif=exif_at("2011-08-20 10:20:00", **nikon),
             expect=exact("2011-08-20 10:20:00", labels=[])),
    ]
    for n in (411, 412):
        specs.append(Spec(f"guess-camping-{n}", f, f"Camping/DSC_0{n}.JPG", unsorted=True, exif=dict(nikon),
                          expect=unsorted("Probably 2011/Camping", f"DSC_0{n}.JPG", best_guess="2011",
                                          labels=[])))
    for i in range(1, 5):
        specs.append(Spec(f"guess-beach-{i}", f, f"Beach/beach_{i}.jpg", exif=exif_at(f"2015-06-0{i} 14:00:00"),
                          expect=exact(f"2015-06-0{i} 14:00:00", labels=[])))
    for x in "ab":
        specs.append(Spec(f"guess-beach-{x}", f, f"Beach/beach_{x}.jpg", unsorted=True,
                          expect=unsorted("Probably 2015/Beach", f"beach_{x}.jpg", best_guess="2015",
                                          labels=[])))
    for i, d in enumerate([datetime(2008, 3, 4, 12), datetime(2008, 7, 19, 12), datetime(2008, 11, 2, 12)], start=1):
        specs.append(Spec(f"guess-oldpics-{i}", f, f"Old Pics/old_{i}.jpg", unsorted=True, mtime=d,
                          expect=unsorted("Probably 2008/Old Pics", f"old_{i}.jpg", best_guess="2008",
                                          labels=[])))
    for i in range(1, 4):
        specs.append(Spec(f"guess-copied-{i}", f, f"Copied/c_{i}.jpg", unsorted=True, mtime=yesterday,
                          expect=unsorted("Date unknown/Copied", f"c_{i}.jpg", labels=[])))
    return specs


def _folder_hints() -> tuple[list[Spec], list[Check]]:
    f = "folder-hints"
    specs = [
        *[
            Spec(f"hint-laptop-{i}", f, f"Old Laptop/2004/Disneyland/dl_{i}.jpg",
                 expect=fuzzy("2004", f"dl_{i}.jpg", "year", source="folder-name", labels=[]))
            for i in (1, 2)
        ],
        Spec("hint-laptop-exif", f, "Old Laptop/2004/Disneyland/dl_3.jpg", exif=exif_at("2004-05-02 14:00:00"),
             expect=exact("2004-05-02 14:00:00", labels=[])),
        *[
            Spec(f"hint-xmas-{i}", f, f"Christmas 2009/xmas_{i}.jpg",
                 expect=fuzzy("2009", f"xmas_{i}.jpg", "year", source="folder-name", labels=[]))
            for i in (1, 2)
        ],
        Spec("hint-xmas-conflict", f, "Christmas 2009/xmas_3.jpg", exif=exif_at("2005-12-24 18:00:00"),
             expect=exact("2005-12-24 18:00:00", conflict=True, labels=[])),
    ]
    checks = [
        # Plain folders never make views: there is no Albums folder at all.
        Check("hint-no-albums", f, "absent", path=f"{LIB}/Albums"),
    ]
    return specs, checks


def _labels() -> tuple[list[Spec], list[Check]]:
    f = "labels"
    specs = [
        *[
            Spec(f"label-hawaii-{i}", f, f"EVENT - Hawaii 2026/IMG_200{i}.JPG",
                 exif=exif_at(f"2026-07-1{i - 1} 11:00:00"),
                 expect=exact(f"2026-07-1{i - 1} 11:00:00", **event("Hawaii 2026")))
            for i in (1, 2, 3)
        ],
        Spec("label-hawaii-nodate", f, "EVENT - Hawaii 2026/hawaii_nodate.jpg",
             expect=fuzzy("2026", "hawaii_nodate.jpg", "year", source="folder-name", **event("Hawaii 2026"))),
        *[
            Spec(f"label-christmas-{i}", f, f"EVENT - Christmas 2025/IMG_300{i}.JPG",
                 exif=exif_at(f"2025-12-25 09:{(i - 1) * 30:02d}:00"),
                 expect=exact(f"2025-12-25 09:{(i - 1) * 30:02d}:00", **event("Christmas 2025")))
            for i in (1, 2)
        ],
        *[
            Spec(f"label-yellowstone-{i}", f, f"EVENT - Yellowstone 2019/Day 1/IMG_400{i}.JPG",
                 exif=exif_at(f"2019-06-1{i - 1} 08:00:00"),
                 expect=exact(f"2019-06-1{i - 1} 08:00:00", **event("Yellowstone 2019")))
            for i in (1, 2)
        ],
        *[
            Spec(f"label-recipes-{i}", f, f"Grandma's Recipes/r_{i}.jpg", exif=exif_at(f"2022-10-0{i} 17:00:00"),
                 expect=exact(f"2022-10-0{i} 17:00:00", labels=[]))
            for i in (1, 2)
        ],
        # She types EVENT, but another word (here "Trip", no spaces) still becomes an event.
        Spec("label-zion-other-word", f, "Trip-Zion 2021/z_1.jpg", exif=exif_at("2021-05-15 13:00:00"),
             expect=exact("2021-05-15 13:00:00", **event("Zion 2021"))),
        Spec("label-graduation-endash", f, "Event – Graduation 2018/g_1.jpg", exif=exif_at("2018-05-20 15:00:00"),
             expect=exact("2018-05-20 15:00:00", **event("Graduation 2018"))),
    ]
    checks = [
        Check("label-no-day-1", f, "absent", path=f"{LIB}/By event/Day 1"),
        Check("label-no-by-trip", f, "absent", path=f"{LIB}/By trip"),
        Check("label-event-hawaii", f, "present", path=f"{LIB}/By event/Hawaii 2026", needs_links=True),
        Check("label-other-word-is-event", f, "present", path=f"{LIB}/By event/Zion 2021", needs_links=True),
        Check("label-event-folder", f, "present", path=f"{LIB}/By event/Graduation 2018", needs_links=True),
    ]
    return specs, checks


def _date_folders() -> tuple[list[Spec], list[Check]]:
    f = "date-folders"
    epson = dict(make="EPSON", model="FastFoto FF-680W")
    specs = [
        *[
            Spec(f"datef-scan-{n}", f, f"DATE - June 2009/scan_{n}.jpg", exif=exif_at("2021-02-0%d 10:00:00" % (n - 100), **epson),
                 expect=fuzzy("2009-06", f"scan_{n}.jpg", "month", source="date-folder"))
            for n in (101, 102)
        ],
        Spec("datef-camera-overridden", f, "DATE - June 2009/cam_101.jpg",
             exif=exif_at("2012-03-03 10:00:00", make="Canon", model="Canon PowerShot A520"),
             expect=fuzzy("2009-06", "cam_101.jpg", "month", source="date-folder",
                          raw_meta_date="2012-03-03T10:00:00")),
        *[
            Spec(f"datef-decade-{i}", f, f"DATE - 1990s/p_{i}.jpg",
                 expect=fuzzy("1990s", f"p_{i}.jpg", "decade", source="date-folder"))
            for i in (1, 2)
        ],
        Spec("datef-day", f, "DATE - July 4 2009/j_1.jpg",
             expect=fuzzy("2009-07-04", "j_1.jpg", "day", source="date-folder")),
        Spec("datef-colon-mac", f, "DATE - 7:4:2009/k_1.jpg", requires="macos",
             expect=fuzzy("2009-07-04", "k_1.jpg", "day", source="date-folder")),
        *[
            Spec(f"datef-in-event-{i}", f, f"EVENT - Hawaii 2009/DATE - June 2009/h_{i}.jpg",
                 exif=exif_at(f"2013-08-0{i} 10:00:00", make="Canon", model="Canon PowerShot A520"),
                 expect=fuzzy("2009-06", f"h_{i}.jpg", "month", source="date-folder", **event("Hawaii 2009")))
            for i in (1, 2)
        ],
        Spec("datef-unreadable", f, "DATE - a long time ago/lt_1.jpg", unsorted=True,
             expect=unsorted("Date unknown/DATE - a long time ago", "lt_1.jpg", labels=[])),
    ]
    checks = [
        Check("datef-no-date-view", f, "absent", path=f"{BY_DATE}/a long time ago"),
        Check("datef-no-date-view-2", f, "absent", path=f"{LIB}/By date/June 2009"),
    ]
    return specs, checks


def _edge() -> tuple[list[Spec], list[Check]]:
    f = "edge"
    specs = [
        Spec("edge-duplicate", f, "IMG_0001 copy.JPG", kind="copy", copy_of="basic-exif", counts="duplicate",
             expect=dict(dir=DUPLICATES, name="IMG_0001 copy.JPG")),
        Spec("edge-pdf", f, "recipe.pdf", kind="bytes", counts="not_photo",
             content=b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n",
             expect=dict(dir=f"{UNSORTED}/Not photos", name="recipe.pdf")),
        Spec("edge-still-copying", f, "IMG_0099.JPG", counts="still_copying",
             # A modified time in the future stays inside the "still copying"
             # window no matter how long you wait before running the organizer.
             mtime="future", exif=exif_at("2024-01-01 12:00:00", make="Apple", model="iPhone 13"),
             expect=dict(dir=INBOX, name="IMG_0099.JPG")),
        Spec("edge-junk-ds-store", f, "Junk Only/.DS_Store", kind="junk", counts=None, expect={}),
        Spec("edge-junk-appledouble", f, "Junk Only/._IMG_0001.JPG", kind="junk", counts=None, expect={}),
        Spec("edge-junk-nested", f, "Junk Only/Deeper/.DS_Store", kind="junk", counts=None, expect={}),
        Spec("edge-junk-in-photo-folder", f, "Camping/.DS_Store", kind="junk", counts=None, expect={}),
    ]
    checks = [
        Check("edge-junk-folder-removed", f, "absent", path=f"{INBOX}/Junk Only"),
        Check("edge-photo-folder-removed", f, "absent", path=f"{INBOX}/Camping"),
        Check("edge-inbox-left", f, "inbox-only", files=["IMG_0099.JPG"]),
        Check("edge-links-healthy", f, "links-healthy"),
    ]
    return specs, checks


def all_scenarios(now: datetime | None = None) -> tuple[list[Spec], list[Check]]:
    now = now or datetime.now()
    specs: list[Spec] = []
    checks: list[Check] = []
    specs += _date_basic() + _iphone() + _sanity(now) + _guesses(now)
    for part in (_folder_hints(), _labels(), _date_folders(), _edge()):
        specs += part[0]
        checks += part[1]
    return specs, checks


# ---------------------------------------------------------------------------
# --big: lots of plain phone photos for timing a first big import
# ---------------------------------------------------------------------------

def big_specs(n: int) -> list[Spec]:
    """n phone photos with EXIF dates spread evenly over 2015-2025.

    Every timestamp ends in :47 seconds, which no other scenario uses, so
    the expected names never collide with them.
    """
    start = datetime(2015, 1, 1, 8, 0, 47)
    span_minutes = int((datetime(2025, 12, 31, 20, 0) - start).total_seconds() // 60)
    step = max(1, span_minutes // max(n, 1))
    out = []
    for i in range(n):
        ts = (start + timedelta(minutes=i * step)).strftime("%Y-%m-%d %H:%M:%S")
        out.append(Spec(f"big-{i + 1:05d}", "big", f"BIG_{i + 1:05d}.JPG",
                        exif=exif_at(ts, make="Apple", model="iPhone 12"), expect=exact(ts)))
    return out


def expected_summary(specs: list[Spec], phase: str = "first-run") -> dict:
    """The run summary counts a run should report."""
    out = dict(sorted_photos=0, sorted_videos=0, unsorted=0, duplicates=0, not_photos=0, still_copying=0)
    key = dict(photo="sorted_photos", video="sorted_videos", duplicate="duplicates",
               not_photo="not_photos", still_copying="still_copying")
    unreadable = set()
    for s in specs:
        if s.phase == phase and s.counts:
            out[key[s.counts]] += 1
            if s.unsorted:
                out["unsorted"] += 1
        for part in s.source.split("/")[:-1]:
            if part == "DATE - a long time ago":
                unreadable.add(part)
    out["unreadable_date_folders"] = sorted(unreadable)
    return out
