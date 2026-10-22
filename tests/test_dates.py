from datetime import datetime

import pytest

from photo_organizer import dates
from photo_organizer.dates import FuzzyDate

NOW = datetime(2026, 10, 22, 12, 0, 0)


@pytest.mark.parametrize("text, expected", [
    ("2009", FuzzyDate("year", 2009)),
    ("June 2009", FuzzyDate("month", 2009, 6)),
    ("Jun 2009", FuzzyDate("month", 2009, 6)),
    ("june 2009", FuzzyDate("month", 2009, 6)),
    ("Sept 2009", FuzzyDate("month", 2009, 9)),
    ("2009-06", FuzzyDate("month", 2009, 6)),
    ("6/2009", FuzzyDate("month", 2009, 6)),
    ("July 4 2009", FuzzyDate("day", 2009, 7, 4)),
    ("July 4, 2009", FuzzyDate("day", 2009, 7, 4)),
    ("July 4th 2009", FuzzyDate("day", 2009, 7, 4)),
    ("7/4/2009", FuzzyDate("day", 2009, 7, 4)),   # US order: month/day
    ("2009-07-04", FuzzyDate("day", 2009, 7, 4)),
    ("1990s", FuzzyDate("decade", 1990)),
    ("90s", FuzzyDate("decade", 1990)),
    ("'90s", FuzzyDate("decade", 1990)),
    ("20s", FuzzyDate("decade", 2020)),            # most recent non-future 20s
    ("00s", FuzzyDate("decade", 2000)),
    ("1950s", FuzzyDate("decade", 1950)),
])
def test_date_folder_formats(text, expected):
    assert dates.parse_date_text(text, NOW) == expected


@pytest.mark.parametrize("text", [
    "a long time ago", "Summer 1998", "13/2009", "2/30/2009", "2031", "December 2026",
    "1995s", "", "June", "2009 2010",
])
def test_date_folder_rejects_unclear_or_future(text):
    assert dates.parse_date_text(text, NOW) is None


def test_two_digit_decade_never_in_future():
    assert dates.parse_date_text("30s", NOW) == FuzzyDate("decade", 1930)


@pytest.mark.parametrize("name, expected", [
    ("Christmas 2009", FuzzyDate("year", 2009)),
    ("2004", FuzzyDate("year", 2004)),
    ("2009-06", FuzzyDate("month", 2009, 6)),
    ("06-2009", FuzzyDate("month", 2009, 6)),
    ("June 2009", FuzzyDate("month", 2009, 6)),
    ("Beach June 2009 trip", FuzzyDate("month", 2009, 6)),
    ("2009-07-04 party", FuzzyDate("month", 2009, 7)),
    ("TRIP - Hawaii 2026", FuzzyDate("year", 2026)),
    ("Disneyland", None),
    ("Photos 12345", None),        # not a standalone 4-digit number
    ("Room 2077", None),           # future
    ("Grandpa 1850", None),        # too early
])
def test_folder_name_hint(name, expected):
    assert dates.folder_name_hint(name, NOW) == expected


def test_path_hint_uses_deepest_folder_with_a_year():
    assert dates.path_hint(["Old Laptop", "2004", "Disneyland"], NOW) == FuzzyDate("year", 2004)
    assert dates.path_hint(["2004", "Christmas 2005", "Day 1"], NOW) == FuzzyDate("year", 2005)
    assert dates.path_hint(["Stuff"], NOW) is None


@pytest.mark.parametrize("filename, expected", [
    ("IMG_20260714_153022.jpg", (2026, 7, 14, 15, 30, 22)),
    ("PXL_20260714_153022123.jpg", (2026, 7, 14, 15, 30, 22)),
    ("20260714_153022.jpg", (2026, 7, 14, 15, 30, 22)),
    ("VID_20260714_153022.mp4", (2026, 7, 14, 15, 30, 22)),
    ("Screenshot 2026-07-14 at 3.30.22 PM.png", (2026, 7, 14, 15, 30, 22)),
    ("Screenshot 2026-07-14 at 3.30.22 PM.png", (2026, 7, 14, 15, 30, 22)),
    ("Screenshot 2026-07-14 at 12.05.00 AM.png", (2026, 7, 14, 0, 5, 0)),
    ("WhatsApp Image 2026-07-14 at 15.30.22.jpeg", (2026, 7, 14, 15, 30, 22)),
    ("Screenshot_20260714-153022.png", (2026, 7, 14, 15, 30, 22)),
    ("2026-07-14 15.30.22.jpg", (2026, 7, 14, 15, 30, 22)),
])
def test_filename_dates(filename, expected):
    d = dates.date_from_filename(filename)
    assert d.precision == "exact"
    assert (d.year, d.month, d.day, d.hour, d.minute, d.second) == expected


def test_filename_whatsapp_android_is_day_only():
    assert dates.date_from_filename("IMG-20260714-WA0003.jpg") == FuzzyDate("day", 2026, 7, 14)


@pytest.mark.parametrize("filename", ["IMG_1234.jpg", "DSC_0412.JPG", "IMG_20261399_999999.jpg", "scan.jpg"])
def test_filename_without_date(filename):
    assert dates.date_from_filename(filename) is None


def test_sanity_checks():
    ok = FuzzyDate("exact", 2015, 6, 1, 10, 0, 0)
    assert dates.sanity_reject(ok, NOW) is None
    assert dates.sanity_reject(FuzzyDate("exact", 2027, 1, 5, 10), NOW) == "future"
    assert dates.sanity_reject(FuzzyDate("exact", 1985, 1, 5, 10), NOW) == "too-early"
    assert dates.sanity_reject(FuzzyDate("exact", 2000, 1, 1, 0, 3), NOW) == "camera-reset"
    assert dates.sanity_reject(FuzzyDate("exact", 1970, 1, 1, 0, 0), NOW) == "too-early"
    # A real New Year's photo on its own is fine.
    assert dates.sanity_reject(FuzzyDate("exact", 2016, 1, 1, 0, 10), NOW) is None


@pytest.mark.parametrize("fields, expected", [
    (("EPSON", "Perfection V600", None), True),
    ((None, None, "VueScan 9.8"), True),
    (("Canon", "CanoScan 9000F", None), True),
    ((None, None, "Google PhotoScan"), True),
    (("Epson", "FastFoto FF-680W", None), True),
    (("Apple", "iPhone 15", "17.1"), False),
    (("Canon", "Canon EOS 5D", None), False),
])
def test_scanner_detection(fields, expected):
    assert dates.is_scanner(*fields) is expected


def test_exif_parsing():
    assert dates.parse_exif_datetime("2009:06:14 10:22:05") == FuzzyDate("exact", 2009, 6, 14, 10, 22, 5)
    assert dates.parse_exif_datetime("0000:00:00 00:00:00") is None
    assert dates.parse_exif_datetime("") is None
    assert dates.parse_exif_datetime("garbage") is None


def test_iso_with_offset():
    d, tz = dates.parse_iso_with_offset("2026-07-14T15:30:22-0700")
    assert d == FuzzyDate("exact", 2026, 7, 14, 15, 30, 22)
    assert tz == "-07:00"


def test_names_and_folders():
    assert FuzzyDate("exact", 2026, 7, 14, 15, 30, 22).name_prefix() == "2026-07-14_15-30-22"
    assert FuzzyDate("month", 2009, 6).name_prefix() == "2009-06"
    assert FuzzyDate("year", 2009).year_folder() == "2009"
    assert FuzzyDate("decade", 1990).year_folder() == "1990s"
    assert FuzzyDate("decade", 1990).name_prefix() == "1990s"


@pytest.mark.parametrize("d", [
    FuzzyDate("exact", 2026, 7, 14, 15, 30, 22), FuzzyDate("day", 2009, 7, 4),
    FuzzyDate("month", 2009, 6), FuzzyDate("year", 2009), FuzzyDate("decade", 1990),
])
def test_iso_round_trip(d):
    assert FuzzyDate.from_iso(d.iso()) == d


def test_fits_folder():
    exact = FuzzyDate("exact", 2019, 6, 3, 10)
    assert exact.fits_folder(FuzzyDate("year", 2019))
    assert not exact.fits_folder(FuzzyDate("year", 2018))
    assert exact.fits_folder(FuzzyDate("decade", 2010))
    assert exact.fits_folder(FuzzyDate("month", 2019, 6))
    assert not exact.fits_folder(FuzzyDate("month", 2019, 7))
    assert not FuzzyDate("decade", 2010).fits_folder(FuzzyDate("year", 2019))
