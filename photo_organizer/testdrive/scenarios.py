"""The test-drive scenarios, as data. Expected results follow CLAUDE.md:
By Date has year folders only; exact-time photos are renamed
YYYY-MM-DD_HH-MM-SS.ext; others get a date prefix ("2004 dl_1.jpg").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

LIB = "My Photos"
BY_DATE = f"{LIB}/By Date"
UNSORTED = f"{LIB}/Unsorted"
DUPLICATES = f"{LIB}/Duplicates (safe to delete)"
INBOX = "Put New Photos Here"

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
}


@dataclass
class Spec:
    id: str
    feature: str
    source: str                         # relative to Put New Photos Here/
    expect: dict
    kind: str = "image"                 # image | video | bytes | copy | junk
    exif: dict = field(default_factory=dict)
    video: dict = field(default_factory=dict)
    content: bytes | None = None
    copy_of: str | None = None
    mtime: object = "default"           # "default" | "future" | datetime
    requires: str | None = None         # "heif" | "macos"
    counts: str | None = None           # photo | video | duplicate | not_photo | still_copying
    unsorted: bool = False              # counts toward "didn't have a date"
    phase: str = "first-run"


@dataclass
class Check:
    """A check that isn't about one file."""
    id: str
    feature: str
    type: str                           # absent | inbox-only
    path: str | None = None
    files: list[str] | None = None
    phase: str = "first-run"


def _date_basic() -> list[Spec]:
    f = "date-basic"
    return [
        Spec("basic-exif", f, "IMG_0001.JPG", counts="photo",
             exif=dict(dto="2024:07:14 15:30:22", make="Apple", model="iPhone 13"),
             expect=dict(dir=f"{BY_DATE}/2024", name="2024-07-14_15-30-22.jpg",
                         date="2024-07-14T15:30:22", precision="exact")),
        Spec("basic-heic-gps", f, "IMG_0002.HEIC", counts="photo", requires="heif",
             exif=dict(dto="2025:03:08 09:05:00", make="Apple", model="iPhone 15", gps=(21.2769, -157.8268)),
             expect=dict(dir=f"{BY_DATE}/2025", name="2025-03-08_09-05-00.heic",
                         date="2025-03-08T09:05:00", precision="exact", gps=[21.2769, -157.8268])),
        *[
            Spec(f"basic-burst-{i}", f, f"IMG_000{n}.JPG", counts="photo",
                 exif=dict(dto="2024:07:14 16:00:00", make="Apple", model="iPhone 13"),
                 expect=dict(dir=f"{BY_DATE}/2024", name=name, date="2024-07-14T16:00:00", precision="exact"))
            for i, (n, name) in enumerate([(3, "2024-07-14_16-00-00.jpg"), (4, "2024-07-14_16-00-00_2.jpg"),
                                           (5, "2024-07-14_16-00-00_3.jpg")], start=1)
        ],
        Spec("basic-screenshot", f, "Screenshot 2025-03-02 at 9.14.07 AM.png", counts="photo",
             expect=dict(dir=f"{BY_DATE}/2025", name="2025-03-02_09-14-07.png",
                         date="2025-03-02T09:14:07", precision="exact")),
        Spec("basic-whatsapp", f, "WhatsApp Image 2023-11-05 at 18.22.10.jpeg", counts="photo",
             expect=dict(dir=f"{BY_DATE}/2023", name="2023-11-05_18-22-10.jpeg",
                         date="2023-11-05T18:22:10", precision="exact")),
        Spec("basic-new-year", f, "IMG_0006.JPG", counts="photo",
             exif=dict(dto="2020:01:01 00:00:30", make="Apple", model="iPhone 11"),
             expect=dict(dir=f"{BY_DATE}/2020", name="2020-01-01_00-00-30.jpg",
                         date="2020-01-01T00:00:30", precision="exact")),
        Spec("basic-video-utc", f, "VID_0001.MP4", kind="video", counts="video",
             video=dict(utc=datetime(2024, 7, 14, 22, 30, 22, tzinfo=timezone.utc), brand=b"isom"),
             expect=dict(dir=f"{BY_DATE}/2024", name="2024-07-14_15-30-22.mp4",
                         date="2024-07-14T15:30:22", precision="exact")),
    ]


def _edge() -> tuple[list[Spec], list[Check]]:
    f = "edge"
    specs = [
        Spec("edge-duplicate", f, "IMG_0001 copy.JPG", kind="copy", copy_of="basic-exif", counts="duplicate",
             expect=dict(dir=DUPLICATES, name="IMG_0001 copy.JPG")),
        Spec("edge-pdf", f, "recipe.pdf", kind="bytes", counts="not_photo",
             content=b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n",
             expect=dict(dir=f"{UNSORTED}/Not Photos", name="recipe.pdf")),
        Spec("edge-still-copying", f, "IMG_0099.JPG", counts="still_copying",
             # A modified time in the future stays inside the "still copying"
             # window no matter how long you wait before running the organizer.
             mtime="future", exif=dict(dto="2024:01:01 12:00:00", make="Apple", model="iPhone 13"),
             expect=dict(dir=INBOX, name="IMG_0099.JPG")),
        Spec("edge-junk-ds-store", f, "Junk Only/.DS_Store", kind="junk", expect={}),
        Spec("edge-junk-appledouble", f, "Junk Only/._IMG_0001.JPG", kind="junk", expect={}),
        Spec("edge-junk-nested", f, "Junk Only/Deeper/.DS_Store", kind="junk", expect={}),
    ]
    checks = [
        Check("edge-junk-folder-removed", f, "absent", path=f"{INBOX}/Junk Only"),
        Check("edge-inbox-left", f, "inbox-only", files=["IMG_0099.JPG"]),
    ]
    return specs, checks


def all_scenarios() -> tuple[list[Spec], list[Check]]:
    specs = _date_basic()
    edge_specs, edge_checks = _edge()
    return specs + edge_specs, edge_checks


def expected_summary(specs: list[Spec], phase: str = "first-run") -> dict:
    """The run summary counts the first run should report."""
    out = dict(sorted_photos=0, sorted_videos=0, unsorted=0, duplicates=0, not_photos=0, still_copying=0)
    key = dict(photo="sorted_photos", video="sorted_videos", duplicate="duplicates",
               not_photo="not_photos", still_copying="still_copying")
    for s in specs:
        if s.phase == phase and s.counts:
            out[key[s.counts]] += 1
            if s.unsorted:
                out["unsorted"] += 1
    return out
