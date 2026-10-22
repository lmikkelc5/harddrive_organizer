from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from conftest import make_file, make_image, make_video
from photo_organizer.dates import FuzzyDate
from photo_organizer.metadata import kind_for, read_image_meta, read_video_meta


def test_kind_for():
    assert kind_for("a.HEIC") == "photo"
    assert kind_for("a.dng") == "photo"
    assert kind_for("a.MOV") == "video"
    assert kind_for("a.m4v") == "video"
    assert kind_for("a.AAE") == "sidecar"
    assert kind_for("a.pdf") == "other"
    assert kind_for("a.nef") == "other"  # RAW is out of scope for v1


def test_image_meta(tmp_path):
    p = make_image(str(tmp_path / "a.jpg"), "2024:07:14 15:30:22", offset="+02:00", make="Apple",
                   model="iPhone 15", software="17.1", gps=(-33.86, 151.21))
    m = read_image_meta(p)
    assert m.candidates[0].date == FuzzyDate("exact", 2024, 7, 14, 15, 30, 22)
    assert m.candidates[0].tz_offset == "+02:00"
    assert (m.make, m.model, m.software) == ("Apple", "iPhone 15", "17.1")
    assert round(m.gps_lat, 3) == -33.86 and round(m.gps_lon, 3) == 151.21


def test_unreadable_image_gives_empty_meta(tmp_path):
    p = make_file(str(tmp_path / "broken.jpg"), b"not really a jpeg")
    assert read_image_meta(p).candidates == []


def test_video_meta(tmp_path):
    p = make_video(str(tmp_path / "v.mov"), apple_date="2024-07-14T15:30:22-0700",
                   utc=datetime(2024, 7, 14, 22, 30, 22, tzinfo=timezone.utc), model="iPhone 15")
    m = read_video_meta(p, ZoneInfo("America/Los_Angeles"))
    assert [c.source for c in m.candidates] == ["quicktime-creationdate", "video-creation-time"]
    assert all(c.date == FuzzyDate("exact", 2024, 7, 14, 15, 30, 22) for c in m.candidates)
    assert m.model == "iPhone 15"


def test_video_zero_time_is_ignored(tmp_path):
    p = make_video(str(tmp_path / "v.mp4"))
    assert read_video_meta(p).candidates == []


def test_garbage_video(tmp_path):
    p = make_file(str(tmp_path / "v.mp4"), b"\x00\x00\x00\x01junk")
    assert read_video_meta(p).candidates == []
