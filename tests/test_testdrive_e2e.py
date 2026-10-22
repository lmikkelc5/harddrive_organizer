"""End to end: generate a test drive, run the organizer, check against expected.json.

Phase 2 (edits) and idempotency are added in later steps of TEST_DRIVE.md.
"""

import os

import pytest

from conftest import FakeUI
from photo_organizer.run import get_timezone, organize
from photo_organizer.layout import Drive
from photo_organizer.testdrive.check import FAIL, PENDING, SKIP, check
from photo_organizer.testdrive.features import TEST_TIMEZONE
from photo_organizer.testdrive.make import NotATestDrive, make


@pytest.fixture(scope="module")
def first_run(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("td") / "drive")
    manifest = make(root)
    organize(Drive(root), FakeUI(), tz=get_timezone(TEST_TIMEZONE))
    return root, manifest, check(root, "first-run")


def test_phase1_files(first_run):
    _, _, results = first_run
    failures = [f"{r.id}: {r.detail} {r.more}" for r in results if r.status == FAIL]
    assert not failures, "\n".join(failures)


def test_phase1_reports_skips_and_pending(first_run):
    _, manifest, results = first_run
    for r in results:
        if r.status == SKIP:
            pytest.skip(f"{r.id} skipped: {r.detail}")  # e.g. HEIC on a PC without pillow-heif
        if r.status == PENDING:
            pytest.xfail(f"{r.id}: feature {r.feature} not built yet")


def test_make_refuses_to_wipe_a_real_folder(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "precious.jpg").write_bytes(b"x")
    with pytest.raises(NotATestDrive):
        make(str(tmp_path / "real"), reset=True)
    assert os.path.exists(tmp_path / "real" / "precious.jpg")


def test_make_is_deterministic(tmp_path):
    a = make(str(tmp_path / "a"))
    b = make(str(tmp_path / "b"))
    assert [f["sha256"] for f in a["files"]] == [f["sha256"] for f in b["files"]]
