"""Link folders (By Trip, By Event, Albums). Most need symlinks, so they run on macOS CI."""

import os
import shutil

from conftest import make_image, needs_symlinks
from photo_organizer import names
from photo_organizer.catalog import Catalog
from photo_organizer.views import VIEWS, plan_views, register_view, safe_folder_name


def _links(folder):
    return sorted(f for f in os.listdir(folder) if os.path.islink(os.path.join(folder, f)))


def test_safe_folder_name():
    assert safe_folder_name("Hawaii/Maui: 2026") == "Hawaii-Maui- 2026"
    assert safe_folder_name("...") == "Untitled"


def test_plan_views_from_catalog(drive):
    make_image(drive.inbox_path("TRIP - Hawaii 2026", "a.jpg"), "2026:07:10 11:00:00")
    make_image(drive.inbox_path("TRIP - Hawaii 2026", "Day 1", "b.jpg"), "2026:07:11 11:00:00")
    make_image(drive.inbox_path("Grandma's Recipes", "r.jpg"), "2022:10:01 11:00:00")
    drive.organize()
    cat = Catalog(drive.catalog)
    plan = {vf.parts: len(vf.photos) for vf in plan_views(cat)}
    cat.close()
    assert plan == {("By Trip", "Hawaii 2026"): 2, ("Albums", "Grandma's Recipes"): 1}


def test_adding_a_view_is_one_function(drive):
    from photo_organizer.views import ViewFolder

    @register_view
    def everything(cat):
        return [ViewFolder(("By Everything", "All"), cat.photos("ok"))]

    try:
        make_image(drive.inbox_path("a.jpg"), "2026:07:10 11:00:00")
        drive.organize()
        cat = Catalog(drive.catalog)
        assert ("By Everything", "All") in [vf.parts for vf in plan_views(cat)]
        cat.close()
    finally:
        VIEWS.remove(everything)


def test_same_label_typed_differently_joins(drive):
    make_image(drive.inbox_path("TRIP - Hawaii 2026", "a.jpg"), "2026:07:10 11:00:00")
    drive.organize()
    make_image(drive.inbox_path("trip - hawaii 2026", "b.jpg"), "2026:07:11 11:00:00")
    drive.organize()
    with drive.db() as con:
        rows = con.execute("SELECT label FROM labels").fetchall()
    assert [r[0] for r in rows] == ["Hawaii 2026"]  # first spelling kept


@needs_symlinks
def test_links_are_relative_and_work(drive):
    make_image(drive.inbox_path("TRIP - Hawaii 2026", "Day 1", "IMG_2001.JPG"), "2026:07:10 11:00:00")
    make_image(drive.inbox_path("EVENT - Christmas 2025", "IMG_3001.JPG"), "2025:12:25 09:00:00")
    drive.organize()
    trip = drive.lib("By Trip", "Hawaii 2026")
    assert _links(trip) == ["2026-07-10_11-00-00.jpg"]
    link = os.path.join(trip, "2026-07-10_11-00-00.jpg")
    assert not os.path.isabs(os.readlink(link))
    assert os.readlink(link) == os.path.join("..", "..", "By Date", "2026", "2026-07-10_11-00-00.jpg")
    assert os.path.isfile(link)
    assert not os.path.exists(drive.lib("By Trip", "Day 1"))
    assert _links(drive.lib("By Event", "Christmas 2025")) == ["2025-12-25_09-00-00.jpg"]
    with open(os.path.join(trip, names.LABEL_ID_FILE)) as f:
        assert f.read().strip().isdigit()


@needs_symlinks
def test_live_photo_video_hidden_from_views(drive):
    from conftest import make_video
    make_image(drive.inbox_path("TRIP - X", "IMG_1.JPG"), "2026:07:10 11:00:00")
    make_video(drive.inbox_path("TRIP - X", "IMG_1.MOV"))
    drive.organize()
    assert _links(drive.lib("By Trip", "X")) == ["2026-07-10_11-00-00.jpg"]


@needs_symlinks
def test_rename_label_folder_sticks(drive):
    make_image(drive.inbox_path("TRIP - Hawaii 2026", "a.jpg"), "2026:07:10 11:00:00")
    drive.organize()
    os.rename(drive.lib("By Trip", "Hawaii 2026"), drive.lib("By Trip", "Maui 2026"))
    drive.organize()
    assert not os.path.exists(drive.lib("By Trip", "Hawaii 2026"))
    assert _links(drive.lib("By Trip", "Maui 2026")) == ["2026-07-10_11-00-00.jpg"]
    with drive.db() as con:
        assert [r[0] for r in con.execute("SELECT label FROM labels")] == ["Maui 2026"]


@needs_symlinks
def test_deleted_photo_link_removed(drive):
    make_image(drive.inbox_path("EVENT - Christmas 2025", "a.jpg"), "2025:12:25 09:00:00")
    make_image(drive.inbox_path("EVENT - Christmas 2025", "b.jpg"), "2025:12:25 10:00:00")
    drive.organize()
    os.remove(os.path.join(drive.by_date, "2025", "2025-12-25_09-00-00.jpg"))
    drive.organize()
    assert _links(drive.lib("By Event", "Christmas 2025")) == ["2025-12-25_10-00-00.jpg"]


@needs_symlinks
def test_all_photos_of_label_deleted_removes_folder(drive):
    make_image(drive.inbox_path("EVENT - Party", "a.jpg"), "2025:12:25 09:00:00")
    drive.organize()
    os.remove(os.path.join(drive.by_date, "2025", "2025-12-25_09-00-00.jpg"))
    drive.organize()
    assert not os.path.exists(drive.lib("By Event"))


@needs_symlinks
def test_deleted_link_comes_back(drive):
    make_image(drive.inbox_path("TRIP - Yellowstone 2019", "a.jpg"), "2019:06:10 09:00:00")
    drive.organize()
    os.unlink(drive.lib("By Trip", "Yellowstone 2019", "2019-06-10_09-00-00.jpg"))
    drive.organize()
    assert _links(drive.lib("By Trip", "Yellowstone 2019")) == ["2019-06-10_09-00-00.jpg"]


@needs_symlinks
def test_drag_photo_from_by_date_into_trip(drive):
    make_image(drive.inbox_path("TRIP - Maui", "a.jpg"), "2026:07:10 11:00:00")
    make_image(drive.inbox_path("Grandma's Recipes", "r.jpg"), "2022:10:01 11:00:00")
    drive.organize()
    shutil.move(os.path.join(drive.by_date, "2022", "2022-10-01_11-00-00.jpg"), drive.lib("By Trip", "Maui"))
    drive.organize()
    assert os.path.isfile(os.path.join(drive.by_date, "2022", "2022-10-01_11-00-00.jpg"))
    assert _links(drive.lib("By Trip", "Maui")) == ["2022-10-01_11-00-00.jpg", "2026-07-10_11-00-00.jpg"]
    assert _links(drive.lib("Albums", "Grandma's Recipes")) == ["2022-10-01_11-00-00.jpg"]


@needs_symlinks
def test_drag_new_photo_into_trip_imports_it(drive):
    make_image(drive.inbox_path("TRIP - Maui 2026", "a.jpg"), "2026:07:10 11:00:00")
    drive.organize()
    make_image(drive.lib("By Trip", "Maui 2026", "new.jpg"), "2026:07:12 08:00:00")
    s = drive.organize()
    assert os.path.isfile(os.path.join(drive.by_date, "2026", "2026-07-12_08-00-00.jpg"))
    assert _links(drive.lib("By Trip", "Maui 2026")) == ["2026-07-10_11-00-00.jpg", "2026-07-12_08-00-00.jpg"]
    assert s.sorted_photos == 1


@needs_symlinks
def test_copy_dragged_into_trip_goes_to_duplicates(drive):
    make_image(drive.inbox_path("TRIP - Maui", "a.jpg"), "2026:07:10 11:00:00")
    make_image(drive.inbox_path("b.jpg"), "2026:07:11 11:00:00")
    drive.organize()
    shutil.copy2(os.path.join(drive.by_date, "2026", "2026-07-11_11-00-00.jpg"), drive.lib("By Trip", "Maui"))
    drive.organize()
    assert drive.files(drive.duplicates) == ["2026-07-11_11-00-00.jpg"]
    assert "2026-07-11_11-00-00.jpg" in _links(drive.lib("By Trip", "Maui"))


@needs_symlinks
def test_sync_never_deletes_real_files(drive):
    make_image(drive.inbox_path("TRIP - Maui", "a.jpg"), "2026:07:10 11:00:00")
    drive.organize()
    # Her own top-level folder full of real files is not a view and is left alone.
    make_image(drive.lib("Grandkids", "k.jpg"))
    drive.organize()
    assert os.path.isfile(drive.lib("Grandkids", "k.jpg"))


def test_no_symlinks_still_sorts_by_date(drive, monkeypatch):
    from photo_organizer import run as run_mod
    monkeypatch.setattr(run_mod, "symlinks_supported", lambda _: False)
    make_image(drive.inbox_path("TRIP - Maui", "a.jpg"), "2026:07:10 11:00:00")
    s = drive.organize()
    assert not s.views_enabled
    assert drive.files(drive.by_date) == ["2026/2026-07-10_11-00-00.jpg"]
    assert not os.path.exists(drive.lib("By Trip"))
