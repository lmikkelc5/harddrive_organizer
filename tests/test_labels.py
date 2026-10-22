from datetime import datetime

import pytest

from photo_organizer.dates import FuzzyDate
from photo_organizer.labels import Label, folder_context, parse_folder_name

NOW = datetime(2026, 10, 22)


@pytest.mark.parametrize("name, group, label", [
    ("TRIP - Hawaii 2026", "Trip", "Hawaii 2026"),
    ("trip - hawaii 2026", "Trip", "hawaii 2026"),
    ("Trips - Hawaii 2026", "Trip", "Hawaii 2026"),
    ("TRIP-Hawaii 2026", "Trip", "Hawaii 2026"),
    ("TRIP – Hawaii 2026", "Trip", "Hawaii 2026"),   # en dash
    ("TRIP — Hawaii 2026", "Trip", "Hawaii 2026"),   # em dash
    ("TRIP: Hawaii 2026", "Trip", "Hawaii 2026"),
    ("  TRIP  -   Hawaii   2026 ", "Trip", "Hawaii 2026"),
    ("TRIP - Hawaii - Maui", "Trip", "Hawaii - Maui"),  # first separator only
    ("EVENT - Christmas 2026", "Event", "Christmas 2026"),
    ("Events - Christmas 2026", "Event", "Christmas 2026"),
    ("WEDDING - Anna & Tom", "Wedding", "Anna & Tom"),  # any group word
    ("Christmas - 2026", "Christmas", "2026"),           # Christmas isn't a plural
])
def test_label_folders(name, group, label):
    m = parse_folder_name(name, NOW)
    assert m.kind == "label"
    assert m.label == Label(group, label)


def test_label_keys_match_case_insensitively():
    a = parse_folder_name("TRIP - Hawaii 2026").label
    b = parse_folder_name("trip - HAWAII 2026").label
    assert a.key == b.key


def test_date_is_reserved():
    m = parse_folder_name("DATE - June 2009", NOW)
    assert m.kind == "date" and m.date == FuzzyDate("month", 2009, 6)
    assert parse_folder_name("date: 1990s", NOW).date == FuzzyDate("decade", 1990)
    assert parse_folder_name("DATE - a long time ago", NOW).kind == "bad-date"


@pytest.mark.parametrize("name", ["Christmas 2026", "Grandma's Recipes", "2009-06", "2004", "Day 1"])
def test_plain_folders(name):
    assert parse_folder_name(name, NOW).kind == "plain"


def test_context_nesting_trip_and_date():
    ctx = folder_context(["TRIP - Hawaii", "DATE - June 2009", "Day 1"], NOW)
    assert ctx.labels == [Label("Trip", "Hawaii")]
    assert ctx.date == FuzzyDate("month", 2009, 6)
    assert ctx.bad_date_folder is None


def test_context_deepest_date_wins():
    ctx = folder_context(["DATE - 2009", "DATE - July 4 2009"], NOW)
    assert ctx.date == FuzzyDate("day", 2009, 7, 4)
    ctx = folder_context(["DATE - 2009", "DATE - whenever"], NOW)
    assert ctx.date is None and ctx.bad_date_folder == "DATE - whenever"
    ctx = folder_context(["DATE - whenever", "DATE - 2009"], NOW)
    assert ctx.date == FuzzyDate("year", 2009) and ctx.bad_date_folder is None


def test_context_albums_only_top_level_and_not_bare_dates():
    ctx = folder_context(["Old Laptop", "2004", "Disneyland"], NOW)
    assert ctx.labels == [Label("Album", "Old Laptop")]
    assert ctx.hint == FuzzyDate("year", 2004)
    assert folder_context(["2004", "Disneyland"], NOW).labels == []
    assert folder_context(["Christmas 2026"], NOW).labels == [Label("Album", "Christmas 2026")]


def test_context_trip_year_is_a_hint():
    ctx = folder_context(["TRIP - Hawaii 2026", "Day 1"], NOW)
    assert ctx.hint == FuzzyDate("year", 2026)
    assert ctx.labels == [Label("Trip", "Hawaii 2026")]


def test_context_multiple_labels():
    ctx = folder_context(["TRIP - Hawaii 2026", "EVENT - Wedding"], NOW)
    assert [l.group for l in ctx.labels] == ["Trip", "Event"]
