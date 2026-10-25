import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from conftest import make_file, make_image, make_video, needs_heif, set_age
from photo_organizer import fileops, names

LA = ZoneInfo("America/Los_Angeles")


def test_exif_date_sorts_into_year_folder(drive):
    make_image(drive.inbox_path("IMG_0001.JPG"), "2024:07:14 15:30:22", make="Apple", model="iPhone 15",
               gps=(37.33, -122.01))
    s = drive.organize()
    assert drive.files(drive.by_date) == ["2024/2024-07-14_15-30-22.jpg"]
    row = drive.row(original_name="IMG_0001.JPG")
    assert row["taken_at"] == "2024-07-14T15:30:22"
    assert row["date_source"] == "exif-original"
    assert row["date_precision"] == "exact"
    assert row["camera_model"] == "iPhone 15"
    assert row["gps_lat"] == pytest.approx(37.33, abs=1e-4)
    assert row["gps_lon"] == pytest.approx(-122.01, abs=1e-4)
    assert row["rel_path"] == "My Photos/By Date/2024/2024-07-14_15-30-22.jpg"
    assert row["original_inbox_path"] == "Put New Photos Here/IMG_0001.JPG"
    assert s.sorted_photos == 1
    assert "All done! 1 photo sorted into My Photos." in drive.ui.infos[0]
    assert os.listdir(drive.inbox) == []


def test_offset_is_stored(drive):
    make_image(drive.inbox_path("a.jpg"), "2024:07:14 15:30:22", offset="-07:00")
    drive.organize()
    assert drive.row(original_name="a.jpg")["tz_offset"] == "-07:00"


def test_digitized_then_ifd0_fallbacks(drive):
    make_image(drive.inbox_path("a.jpg"), dtd="2019:05:05 10:00:00")
    make_image(drive.inbox_path("b.jpg"), dt="2018:04:04 09:00:00")
    drive.organize()
    assert drive.row(original_name="a.jpg")["date_source"] == "exif-digitized"
    assert drive.row(original_name="b.jpg")["date_source"] == "exif-datetime"


def test_burst_collisions_get_suffixes(drive):
    for i in (3, 4, 5):
        make_image(drive.inbox_path(f"IMG_000{i}.JPG"), "2024:07:14 16:00:00")
    drive.organize()
    assert drive.files(drive.by_date) == [
        "2024/2024-07-14_16-00-00.jpg", "2024/2024-07-14_16-00-00_2.jpg", "2024/2024-07-14_16-00-00_3.jpg"]


def test_filename_dates(drive):
    make_image(drive.inbox_path("Screenshot 2025-03-02 at 9.14.07 AM.png"))
    make_image(drive.inbox_path("WhatsApp Image 2023-11-05 at 18.22.10.jpeg"))
    drive.organize()
    assert drive.files(drive.by_date) == ["2023/2023-11-05_18-22-10.jpeg", "2025/2025-03-02_09-14-07.png"]
    assert drive.row(original_name="Screenshot 2025-03-02 at 9.14.07 AM.png")["date_source"] == "filename"


def test_single_new_years_photo_is_kept(drive):
    make_image(drive.inbox_path("IMG_0006.JPG"), "2020:01:01 00:00:30", make="Apple", model="iPhone 11")
    drive.organize()
    assert drive.files(drive.by_date) == ["2020/2020-01-01_00-00-30.jpg"]


def test_repeated_jan_first_from_one_camera_is_rejected(drive):
    for i, t in enumerate(["00:00:05", "00:00:12", "00:00:40"], start=1):
        make_image(drive.inbox_path(f"DSC0000{i}.JPG"), f"2005:01:01 {t}", model="DSC-W55")
    drive.organize()
    assert drive.files(drive.by_date) == []
    assert sorted(drive.files(drive.unsorted)) == [
        "Date Unknown/DSC00001.JPG", "Date Unknown/DSC00002.JPG", "Date Unknown/DSC00003.JPG",
        names.HOW_TO_FIX_FILE]
    assert drive.row(original_name="DSC00001.JPG")["reject_reason"] == "camera-reset"
    assert drive.row(original_name="DSC00001.JPG")["raw_meta_date"] == "2005-01-01T00:00:05"


def test_reset_default_date_rejected(drive):
    make_image(drive.inbox_path("x.jpg"), "2000:01:01 00:00:05", model="DSC-W55")
    drive.organize()
    row = drive.row(original_name="x.jpg")
    assert row["reject_reason"] == "camera-reset"
    assert row["rel_path"] == "My Photos/Unsorted/Date Unknown/x.jpg"


def test_future_date_rejected(drive):
    future = datetime.now().replace(year=datetime.now().year + 2)
    make_image(drive.inbox_path("IMG_0007.JPG"), future.strftime("%Y:%m:%d %H:%M:%S"))
    drive.organize()
    assert drive.row(original_name="IMG_0007.JPG")["reject_reason"] == "future"


def test_scanner_date_rejected(drive):
    make_image(drive.inbox_path("scan_001.jpg"), "2021:05:01 10:00:00", make="EPSON", model="Perfection V600")
    s = drive.organize()
    row = drive.row(original_name="scan_001.jpg")
    assert row["rel_path"] == "My Photos/Unsorted/Date Unknown/scan_001.jpg"
    assert row["reject_reason"] == "scanner"
    assert s.unsorted == 1
    assert "1 photo didn't have a date, so it's in My Photos ▸ Unsorted." in drive.ui.infos[0]


def test_scanner_filename_date_also_rejected(drive):
    make_image(drive.inbox_path("IMG_20210501_100000.jpg"), software="VueScan 9")
    drive.organize()
    assert drive.row(original_name="IMG_20210501_100000.jpg")["date_precision"] == "unknown"


# ---- DATE folders ----

def test_date_folder_overrides_metadata(drive):
    make_image(drive.inbox_path("DATE - June 2009", "cam_101.jpg"), "2012:03:03 10:00:00")
    make_image(drive.inbox_path("DATE - June 2009", "scan_101.jpg"), "2021:01:01 10:00:00", make="EPSON")
    drive.organize()
    assert drive.files(drive.by_date) == ["2009/2009-06 cam_101.jpg", "2009/2009-06 scan_101.jpg"]
    row = drive.row(original_name="cam_101.jpg")
    assert row["taken_at"] == "2009-06" and row["date_precision"] == "month"
    assert row["date_source"] == "date-folder"
    assert row["raw_meta_date"] == "2012-03-03T10:00:00"
    assert "DATE folder" in row["date_conflict"]
    assert drive.row(original_name="scan_101.jpg")["reject_reason"] == "scanner"


def test_date_folder_precisions(drive):
    make_image(drive.inbox_path("DATE - 1990s", "p_1.jpg"))
    make_image(drive.inbox_path("DATE - July 4 2009", "j_1.jpg"))
    make_image(drive.inbox_path("DATE - 2001", "y_1.jpg"))
    drive.organize()
    assert drive.files(drive.by_date) == ["1990s/1990s p_1.jpg", "2001/2001 y_1.jpg", "2009/2009-07-04 j_1.jpg"]
    assert drive.row(original_name="p_1.jpg")["date_precision"] == "decade"
    assert drive.row(original_name="j_1.jpg")["date_precision"] == "day"


def test_date_folder_inside_trip(drive):
    make_image(drive.inbox_path("TRIP - Hawaii 2009", "DATE - June 2009", "h_1.jpg"), "2013:01:01 10:00:00")
    drive.organize()
    assert drive.files(drive.by_date) == ["2009/2009-06 h_1.jpg"]
    with drive.db() as con:
        labels = con.execute("SELECT group_name, label FROM labels").fetchall()
    assert [tuple(l) for l in labels] == [("Trip", "Hawaii 2009")]


def test_unreadable_date_folder_goes_to_unsorted(drive):
    make_image(drive.inbox_path("DATE - a long time ago", "lt_1.jpg"), "2015:01:05 10:00:00")
    s = drive.organize()
    assert drive.row(original_name="lt_1.jpg")["rel_path"] == \
        "My Photos/Unsorted/Date Unknown/DATE - a long time ago/lt_1.jpg"
    assert s.unreadable_date_folders == ["DATE - a long time ago"]
    assert 'I couldn\'t read the date in "DATE - a long time ago", so those photos are in Unsorted.' \
        in drive.ui.infos[0]
    with drive.db() as con:
        assert con.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0


# ---- folder-name hints ----

def test_folder_hints(drive):
    make_image(drive.inbox_path("Old Laptop", "2004", "Disneyland", "dl_1.jpg"))
    make_image(drive.inbox_path("Old Laptop", "2004", "Disneyland", "dl_3.jpg"), "2004:05:02 10:00:00")
    make_image(drive.inbox_path("Summer 2009-06", "s.jpg"))
    drive.organize()
    assert drive.files(drive.by_date) == [
        "2004/2004 dl_1.jpg", "2004/2004-05-02_10-00-00.jpg", "2009/2009-06 s.jpg"]
    assert drive.row(original_name="dl_1.jpg")["date_source"] == "folder-name"


def test_metadata_beats_folder_year_and_logs_conflict(drive):
    make_image(drive.inbox_path("Christmas 2009", "xmas_3.jpg"), "2005:12:24 18:00:00")
    drive.organize()
    row = drive.row(original_name="xmas_3.jpg")
    assert row["taken_at"] == "2005-12-24T18:00:00"
    assert "folder name 2009" in row["date_conflict"]


# ---- duplicates, junk, not photos, still copying ----

def test_duplicates_in_batch_and_catalog(drive):
    src = make_image(drive.inbox_path("IMG_0001.JPG"), "2024:07:14 15:30:22")
    with open(src, "rb") as f:
        data = f.read()
    make_file(drive.inbox_path("IMG_0001 copy.JPG"), data)
    s = drive.organize()
    assert s.duplicates == 1
    assert drive.files(drive.duplicates) == ["IMG_0001 copy.JPG"]
    # Same photo dropped again later.
    make_file(drive.inbox_path("again", "IMG_0001.JPG"), data)
    s = drive.organize()
    assert s.duplicates == 1
    assert drive.files(drive.duplicates) == ["IMG_0001 copy.JPG", "again/IMG_0001.JPG"]
    assert "already in My Photos" in drive.ui.infos[0]


def test_junk_ignored_and_empty_folders_removed(drive):
    make_image(drive.inbox_path("Trip stuff", "a.jpg"), "2024:07:14 15:30:22")
    make_file(drive.inbox_path("Trip stuff", ".DS_Store"))
    make_file(drive.inbox_path("Trip stuff", "._a.jpg"))
    make_file(drive.inbox_path(".DS_Store"))
    drive.organize()
    assert os.listdir(drive.inbox) == [".DS_Store"]  # the inbox itself stays
    assert drive.files(drive.by_date) == ["2024/2024-07-14_15-30-22.jpg"]


def test_folder_with_failures_is_not_removed(drive, monkeypatch):
    make_image(drive.inbox_path("F", "a.jpg"), "2024:07:14 15:30:22")
    make_image(drive.inbox_path("F", "b.jpg"), "2024:07:15 15:30:22")
    real_move = fileops.FileOps.move

    def flaky(self, src, dst):
        if src.endswith("b.jpg"):
            raise OSError("disk hiccup")
        return real_move(self, src, dst)

    monkeypatch.setattr(fileops.FileOps, "move", flaky)
    s = drive.organize()
    assert s.failed == 1 and s.sorted_photos == 1
    assert os.listdir(drive.inbox_path("F")) == ["b.jpg"]
    assert "still in \"Put New Photos Here.\"" in drive.ui.infos[0]


def test_not_photos(drive):
    make_file(drive.inbox_path("recipe.pdf"), b"%PDF-1.4\n%%EOF\n")
    s = drive.organize()
    assert drive.files(drive.unsorted) == [names.HOW_TO_FIX_FILE, "Not Photos/recipe.pdf"]
    assert s.not_photos == 1
    assert "wasn't a photo or video" in drive.ui.infos[0]


def test_still_copying_is_left_for_next_time(drive):
    p = make_image(drive.inbox_path("IMG_0099.JPG"), "2024:01:01 12:00:00", age=0)
    s = drive.organize()
    assert s.still_copying == 1
    assert os.path.exists(p)
    assert "still being copied" in drive.ui.infos[0]
    set_age(p)
    drive.organize()
    assert drive.files(drive.by_date) == ["2024/2024-01-01_12-00-00.jpg"]


def test_nothing_to_do(drive):
    s = drive.organize()
    assert s.nothing_to_do
    from photo_organizer.run import message_for
    assert message_for(s) == names.MSG_NOTHING_TO_DO


def test_hidden_files_are_skipped(drive):
    make_image(drive.inbox_path(".hidden.jpg"), "2024:07:14 15:30:22")
    s = drive.organize()
    assert s.nothing_to_do
    assert os.path.exists(drive.inbox_path(".hidden.jpg"))


# ---- iPhone specials ----

def test_live_photo_pair_and_edit_and_sidecar(drive):
    make_image(drive.inbox_path("IMG_1234.JPG"), "2024:12:25 08:00:00")
    make_video(drive.inbox_path("IMG_1234.MOV"))
    make_image(drive.inbox_path("IMG_E1234.JPG"), "2024:12:25 08:00:00")
    make_file(drive.inbox_path("IMG_1234.AAE"), b"<plist/>")
    s = drive.organize()
    assert drive.files(drive.by_date) == [
        "2024/2024-12-25_08-00-00.jpg", "2024/2024-12-25_08-00-00.mov", "2024/2024-12-25_08-00-00_edited.jpg"]
    photo = drive.row(original_name="IMG_1234.JPG")
    video = drive.row(original_name="IMG_1234.MOV")
    edit = drive.row(original_name="IMG_E1234.JPG")
    assert photo["pair_id"] == video["id"] and video["pair_id"] == photo["id"]
    assert video["taken_at"] == photo["taken_at"]
    assert edit["edited_of_id"] == photo["id"]
    assert os.listdir(drive.sidecars) == ["IMG_1234.AAE"]
    with drive.db() as con:
        sc = con.execute("SELECT * FROM sidecars").fetchone()
    assert sc["photo_id"] == photo["id"]
    assert s.sorted_photos == 2 and s.sorted_videos == 0


@needs_heif
def test_heic_with_exif(drive):
    make_image(drive.inbox_path("IMG_0002.HEIC"), "2025:03:08 09:05:00", gps=(19.6, -155.5))
    drive.organize()
    assert drive.files(drive.by_date) == ["2025/2025-03-08_09-05-00.heic"]
    assert drive.row(original_name="IMG_0002.HEIC")["gps_lat"] == pytest.approx(19.6, abs=1e-4)


# ---- videos ----

def test_video_prefers_apple_local_date(drive):
    make_video(drive.inbox_path("IMG_5000.MOV"), apple_date="2024-07-14T15:30:22-0700",
               utc=datetime(2024, 7, 14, 22, 30, 25, tzinfo=timezone.utc))
    drive.organize(tz=LA)
    row = drive.row(original_name="IMG_5000.MOV")
    assert row["taken_at"] == "2024-07-14T15:30:22"
    assert row["date_source"] == "quicktime-creationdate"
    assert row["tz_offset"] == "-07:00"


def test_video_utc_converted_to_local(drive):
    make_video(drive.inbox_path("VID_0001.MP4"), utc=datetime(2024, 7, 14, 22, 30, 22, tzinfo=timezone.utc))
    drive.organize(tz=LA)
    row = drive.row(original_name="VID_0001.MP4")
    assert row["taken_at"] == "2024-07-14T15:30:22"
    assert row["rel_path"] == "My Photos/By Date/2024/2024-07-14_15-30-22.mp4"
    assert "All done! 1 video sorted" in drive.ui.infos[0]


# ---- guesses ----

def test_neighbor_guess(drive):
    make_image(drive.inbox_path("Camping", "DSC_0410.JPG"), "2011:08:20 10:00:00", model="D90")
    make_image(drive.inbox_path("Camping", "DSC_0411.JPG"), model="D90")
    make_image(drive.inbox_path("Camping", "DSC_0412.JPG"), model="D90")
    make_image(drive.inbox_path("Camping", "DSC_0413.JPG"), "2011:08:20 10:20:00", model="D90")
    drive.organize()
    assert drive.files(drive.unsorted) == [
        names.HOW_TO_FIX_FILE, "Probably 2011/Camping/DSC_0411.JPG", "Probably 2011/Camping/DSC_0412.JPG"]
    row = drive.row(original_name="DSC_0411.JPG")
    assert row["best_guess"] == "2011" and row["guess_source"] == "neighbors"


def test_majority_guess(drive):
    for i in range(1, 5):
        make_image(drive.inbox_path("Beach", f"beach_{i}.jpg"), f"2015:06:0{i} 10:00:00")
    make_image(drive.inbox_path("Beach", "beach_a.jpg"))
    drive.organize()
    row = drive.row(original_name="beach_a.jpg")
    assert row["rel_path"] == "My Photos/Unsorted/Probably 2015/Beach/beach_a.jpg"
    assert row["guess_source"] == "folder-majority"


def test_mtime_guess_and_bulk_copy(drive):
    for i, d in enumerate([(2008, 3, 4), (2008, 7, 19), (2008, 11, 2)], start=1):
        p = make_image(drive.inbox_path("Old Pics", f"old_{i}.jpg"))
        t = datetime(*d, 12).timestamp()
        os.utime(p, (t, t))
    same = time.time() - 86400 * 60
    for i in range(1, 4):
        p = make_image(drive.inbox_path("Copied", f"c_{i}.jpg"))
        os.utime(p, (same, same))
    drive.organize()
    assert drive.row(original_name="old_2.jpg")["rel_path"] == "My Photos/Unsorted/Probably 2008/Old Pics/old_2.jpg"
    assert drive.row(original_name="c_1.jpg")["rel_path"] == "My Photos/Unsorted/Date Unknown/Copied/c_1.jpg"


# ---- dry run, catalog backups, errors ----

def test_dry_run_changes_nothing(drive):
    make_image(drive.inbox_path("TRIP - Hawaii 2026", "IMG_2001.JPG"), "2026:07:10 11:00:00")
    before = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(drive.root) for f in fs)
    drive.organize(dry_run=True)
    after = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(drive.root) for f in fs)
    assert before == after
    assert not os.path.exists(drive.library)


def test_catalog_backups_keep_ten(drive):
    for _ in range(12):
        drive.organize()
    assert len(os.listdir(drive.backups)) == 10


def test_unexpected_error_shows_friendly_message(drive, monkeypatch):
    from conftest import FakeUI
    from photo_organizer import run as run_mod

    make_image(drive.inbox_path("a.jpg"), "2024:07:14 15:30:22")

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(run_mod, "reconcile", boom)
    ui = FakeUI()
    code = run_mod.run(drive.root, ui)
    assert code == 1
    assert ui.errors == [names.MSG_UNEXPECTED_ERROR]
    reports = [f for f in os.listdir(drive.logs) if f.startswith("error-")]
    assert reports
    with open(os.path.join(drive.logs, reports[0]), encoding="utf-8") as f:
        assert "kaboom" in f.read()
    assert os.path.exists(drive.inbox_path("a.jpg"))
    assert not os.path.exists(drive.lock)


def test_never_overwrites(drive):
    make_image(drive.inbox_path("a.jpg"), "2024:07:14 15:30:22")
    os.makedirs(os.path.join(drive.by_date, "2024"))
    make_file(os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg"), b"hers")
    drive.organize()
    with open(os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg"), "rb") as f:
        assert f.read() == b"hers"
    assert "2024/2024-07-14_15-30-22_2.jpg" in drive.files(drive.by_date)


def test_loose_inbox_files_get_no_pile_guess(drive):
    # Dated phone photos loose in the inbox must not make an undated loose photo "Probably 2024".
    for i in range(1, 5):
        make_image(drive.inbox_path(f"IMG_10{i}.JPG"), f"2024:07:0{i} 10:00:00")
    p = make_image(drive.inbox_path("photo.jpg"))
    t = datetime(2008, 5, 5, 12).timestamp()
    os.utime(p, (t, t))
    drive.organize()
    assert drive.row(original_name="photo.jpg")["rel_path"] == "My Photos/Unsorted/Date Unknown/photo.jpg"


def test_loose_inbox_neighbors_still_guess(drive):
    make_image(drive.inbox_path("DSC_0410.JPG"), "2011:08:20 10:00:00", model="D90")
    make_image(drive.inbox_path("DSC_0411.JPG"), model="D90")
    make_image(drive.inbox_path("DSC_0412.JPG"), "2011:08:20 10:20:00", model="D90")
    drive.organize()
    assert drive.row(original_name="DSC_0411.JPG")["rel_path"] == "My Photos/Unsorted/Probably 2011/DSC_0411.JPG"
