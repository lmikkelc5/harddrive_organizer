"""Lock, drive discovery, dialogs, messages, and the CLI."""

import io
import os
import time
from types import SimpleNamespace

import pytest

from conftest import FakeUI, make_image
from photo_organizer import names, system
from photo_organizer.run import RunSummary, message_for, run
from photo_organizer.system import AlreadyRunning, ConsoleUI, MacUI, RunLock, find_drive


def test_lock_blocks_second_run(tmp_path):
    a = RunLock(str(tmp_path / "lock"))
    a.acquire()
    with pytest.raises(AlreadyRunning):
        RunLock(str(tmp_path / "lock")).acquire()
    a.release()
    RunLock(str(tmp_path / "lock")).acquire()


def test_stale_lock_is_taken_over(tmp_path):
    p = tmp_path / "lock"
    p.write_text("{}")
    old = time.time() - 2 * 3600
    os.utime(p, (old, old))
    lock = RunLock(str(p))
    lock.acquire()
    assert lock.held


def test_already_running_message(drive):
    os.makedirs(drive.app_data, exist_ok=True)
    open(drive.lock, "w").close()
    ui = FakeUI()
    assert run(drive.root, ui) == 3
    assert ui.infos == [names.MSG_ALREADY_RUNNING]


def test_no_drive_message():
    ui = FakeUI()
    assert run(None, ui, finder=lambda: None) == 2
    assert ui.errors == [names.MSG_NO_DRIVE]


def test_full_run_through_cli(drive, capsys):
    from photo_organizer.__main__ import main
    make_image(drive.inbox_path("a.jpg"), "2024:07:14 15:30:22")
    assert main(["--drive", drive.root]) == 0
    assert "All done! 1 photo sorted into My photos." in capsys.readouterr().out


def test_dry_run_cli_prints_plan(drive, capsys):
    from photo_organizer.__main__ import main
    make_image(drive.inbox_path("a.jpg"), "2024:07:14 15:30:22")
    main(["--drive", drive.root, "--dry-run"])
    out = capsys.readouterr().out
    assert "[dry-run] move Put new photos here/a.jpg -> My photos/By date/2024/2024-07-14_15-30-22.jpg" in out
    assert os.path.exists(drive.inbox_path("a.jpg"))


# ---- drive discovery (paths are POSIX-style like on the Mac) ----

def _fake_volumes(tmp_path, with_marker=True):
    vols = tmp_path / "Volumes"
    d = vols / "Family Photos"
    (d / ".photo-organizer").mkdir(parents=True)
    if with_marker:
        (d / ".photo-organizer" / "drive-marker").write_text("x")
    return str(vols), str(d)


def test_find_drive_next_to_app(tmp_path):
    vols, d = _fake_volumes(tmp_path)
    exe = os.path.join(d, "Organize photos.app", "Contents", "MacOS", "Organize photos")
    assert find_drive(exe, vols) == d


def test_find_drive_first_run_at_volume_root(tmp_path):
    vols, d = _fake_volumes(tmp_path, with_marker=False)
    exe = os.path.join(d, "Organize photos.app", "Contents", "MacOS", "Organize photos")
    assert find_drive(exe, vols) == d


def test_find_drive_from_applications_scans_volumes(tmp_path):
    vols, d = _fake_volumes(tmp_path)
    exe = os.path.join(str(tmp_path), "Applications", "Organize photos.app", "Contents", "MacOS", "Organize photos")
    assert find_drive(exe, vols) == d


def test_find_drive_translocated(tmp_path):
    vols, d = _fake_volumes(tmp_path)
    exe = "/private/var/folders/xy/T/AppTranslocation/ABC/d/Organize photos.app/Contents/MacOS/Organize photos"
    assert find_drive(exe, vols) == d


def test_find_drive_none(tmp_path):
    vols, _ = _fake_volumes(tmp_path, with_marker=False)
    exe = os.path.join(str(tmp_path), "Applications", "Organize photos.app", "Contents", "MacOS", "x")
    assert find_drive(exe, vols) is None


# ---- dialogs ----

def test_mac_ui_passes_message_as_argument(monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=0))
    msg = 'She said "hi" \\ and ▸ left'
    MacUI().info(msg)
    cmd = calls[0]
    assert cmd[0] == "osascript"
    assert cmd[-2:] == [msg, names.APP_NAME]
    assert not any(msg in part for part in cmd[:-2])  # never pasted into the script


def test_console_ui_survives_unencodable_text():
    raw = io.BytesIO()
    s = io.TextIOWrapper(raw, encoding="cp1252")
    ConsoleUI(s).info("Unsorted ▸ Not photos")
    assert b"Unsorted ? Not photos" in raw.getvalue()


# ---- messages ----

def test_summary_message_matches_the_draft():
    s = RunSummary(sorted_photos=143, unsorted=3, updated_labels=["Hawaii 2026", "Christmas 2026"])
    assert message_for(s) == (
        "All done! 143 photos sorted into My photos. Updated: Hawaii 2026, Christmas 2026. "
        "3 photos didn't have a date, so they're in My photos ▸ Unsorted.")


def test_summary_mentions_full_drive():
    s = RunSummary(sorted_photos=2, drive_percent_full=93)
    assert "almost full (93%)" in message_for(s)
    assert "almost full" not in message_for(RunSummary(sorted_photos=2, drive_percent_full=80))


def test_summary_mixed_photos_and_videos():
    assert message_for(RunSummary(sorted_photos=2, sorted_videos=1)).startswith(
        "All done! 3 photos and videos sorted")
