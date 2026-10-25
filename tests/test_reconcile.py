"""Mom rearranges things in Finder; the catalog follows and nothing gets moved back."""

import os
import shutil

from conftest import make_file, make_image
from photo_organizer import names
from photo_organizer.reconcile import folder_date
from photo_organizer.dates import FuzzyDate


def test_folder_date_rules():
    assert folder_date(["By Date", "2019", "x.jpg"]) == FuzzyDate("year", 2019)
    assert folder_date(["By Date", "1990s", "x.jpg"]) == FuzzyDate("decade", 1990)
    assert folder_date(["By Date", "2019", "Beach Day", "x.jpg"]) == FuzzyDate("year", 2019)
    assert folder_date(["By Date", "2019", "06 - June", "x.jpg"]) == FuzzyDate("month", 2019, 6)
    assert folder_date(["By Date", "Misc", "x.jpg"]) is None
    assert folder_date(["By Date", "x.jpg"]) is None
    assert folder_date(["Unsorted", "Probably 2008", "x.jpg"]) == "unsorted"
    assert folder_date(["Duplicates (safe to delete)", "x.jpg"]) is None


def _first_run(drive):
    make_image(drive.inbox_path("photo.jpg"))  # undated -> Unsorted
    make_image(drive.inbox_path("IMG_0001.JPG"), "2024:07:14 15:30:22")
    make_image(drive.inbox_path("IMG_0002.JPG"), "2019:06:03 10:00:00")
    drive.organize()


def test_move_unsorted_into_year_folder(drive):
    _first_run(drive)
    dst_dir = os.path.join(drive.by_date, "2010")
    os.makedirs(dst_dir)
    shutil.move(os.path.join(drive.unsorted, "Date Unknown", "photo.jpg"), os.path.join(dst_dir, "photo.jpg"))
    drive.organize()
    assert os.path.exists(os.path.join(dst_dir, "photo.jpg"))
    row = drive.row(original_name="photo.jpg")
    assert row["rel_path"] == "My Photos/By Date/2010/photo.jpg"
    assert (row["taken_at"], row["date_precision"], row["date_source"]) == ("2010", "year", "manual")
    assert row["status"] == "ok"


def test_move_into_her_own_month_folder(drive):
    _first_run(drive)
    dst_dir = os.path.join(drive.by_date, "2010", "03 - March")
    os.makedirs(dst_dir)
    shutil.move(os.path.join(drive.unsorted, "Date Unknown", "photo.jpg"), os.path.join(dst_dir, "photo.jpg"))
    drive.organize()
    row = drive.row(original_name="photo.jpg")
    assert (row["taken_at"], row["date_precision"]) == ("2010-03", "month")


def test_placement_beats_exif(drive):
    _first_run(drive)
    src = os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg")
    os.makedirs(os.path.join(drive.by_date, "2018"))
    shutil.move(src, os.path.join(drive.by_date, "2018", "2024-07-14_15-30-22.jpg"))
    drive.organize()
    row = drive.row(original_name="IMG_0001.JPG")
    assert (row["taken_at"], row["date_source"]) == ("2018", "manual")
    assert os.path.exists(os.path.join(drive.by_date, "2018", "2024-07-14_15-30-22.jpg"))


def test_subfolder_in_same_year_keeps_exact_date(drive):
    _first_run(drive)
    beach = os.path.join(drive.by_date, "2019", "Beach Day")
    os.makedirs(beach)
    shutil.move(os.path.join(drive.by_date, "2019", "2019-06-03_10-00-00.jpg"), beach)
    drive.organize()
    row = drive.row(original_name="IMG_0002.JPG")
    assert row["rel_path"] == "My Photos/By Date/2019/Beach Day/2019-06-03_10-00-00.jpg"
    assert (row["taken_at"], row["date_source"]) == ("2019-06-03T10:00:00", "exif-original")


def test_rename(drive):
    _first_run(drive)
    os.rename(os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg"),
              os.path.join(drive.by_date, "2024", "Mom favorite.jpg"))
    drive.organize()
    row = drive.row(original_name="IMG_0001.JPG")
    assert row["rel_path"] == "My Photos/By Date/2024/Mom favorite.jpg"
    assert row["taken_at"] == "2024-07-14T15:30:22"
    assert os.path.exists(os.path.join(drive.by_date, "2024", "Mom favorite.jpg"))


def test_delete_marks_missing_quietly(drive):
    _first_run(drive)
    os.remove(os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg"))
    s = drive.organize()
    assert drive.row(original_name="IMG_0001.JPG")["status"] == "missing"
    assert s.failed == 0
    assert drive.ui.infos == [names.MSG_NOTHING_TO_DO]


def test_copy_left_alone_not_cataloged_twice(drive):
    _first_run(drive)
    src = os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg")
    shutil.copy2(src, os.path.join(drive.by_date, "2024", "copy of it.jpg"))
    drive.organize()
    drive.organize()
    assert os.path.exists(os.path.join(drive.by_date, "2024", "copy of it.jpg"))
    with drive.db() as con:
        assert con.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM events WHERE kind = 'copy'").fetchone()[0] == 1
    assert drive.files(drive.duplicates) == []


def test_copy_becomes_the_photo_if_original_deleted(drive):
    _first_run(drive)
    src = os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg")
    copy = os.path.join(drive.by_date, "2024", "copy.jpg")
    shutil.copy2(src, copy)
    drive.organize()
    os.remove(src)
    drive.organize()
    row = drive.row(original_name="IMG_0001.JPG")
    assert row["status"] == "ok" and row["rel_path"] == "My Photos/By Date/2024/copy.jpg"


def test_move_into_unsorted_makes_date_unknown(drive):
    _first_run(drive)
    shutil.move(os.path.join(drive.by_date, "2024", "2024-07-14_15-30-22.jpg"),
                os.path.join(drive.unsorted, "later.jpg"))
    drive.organize()
    row = drive.row(original_name="IMG_0001.JPG")
    assert row["taken_at"] is None and row["date_precision"] == "unknown"


def test_new_file_placed_directly_in_by_date(drive):
    _first_run(drive)
    make_image(os.path.join(drive.by_date, "1990s", "old.jpg"))
    drive.organize()
    row = drive.row(original_name="old.jpg")
    assert (row["taken_at"], row["date_precision"], row["date_source"]) == ("1990s", "decade", "manual")
    assert os.path.exists(os.path.join(drive.by_date, "1990s", "old.jpg"))  # not renamed


def test_duplicates_folder_is_ignored(drive):
    _first_run(drive)
    make_file(os.path.join(drive.duplicates, "whatever.jpg"))
    drive.organize()
    assert drive.row(original_name="whatever.jpg") is None


def test_second_run_is_a_no_op(drive):
    _first_run(drive)
    before = drive.files()
    s = drive.organize()
    assert s.nothing_to_do
    assert drive.files() == before


def test_photo_dropped_into_year_keeps_its_exact_date_if_it_fits(drive):
    _first_run(drive)
    make_image(os.path.join(drive.by_date, "2019", "from phone.jpg"), "2019:08:01 09:00:00")
    make_image(os.path.join(drive.by_date, "2019", "wrong clock.jpg"), "2012:08:01 09:00:00")
    drive.organize()
    fits = drive.row(original_name="from phone.jpg")
    assert (fits["taken_at"], fits["date_source"]) == ("2019-08-01T09:00:00", "exif-original")
    wrong = drive.row(original_name="wrong clock.jpg")
    assert (wrong["taken_at"], wrong["date_source"]) == ("2019", "manual")  # her placement wins


def test_catalog_lost_mid_import_is_recovered(drive):
    """A power cut after a move but before the catalog write: the next run re-finds the file."""
    _first_run(drive)
    with drive.db() as con:
        con.execute("DELETE FROM photos WHERE original_name = 'IMG_0001.JPG'")
    drive.organize()
    row = drive.row(rel_path="My Photos/By Date/2024/2024-07-14_15-30-22.jpg")
    assert row["taken_at"] == "2024-07-14T15:30:22"
