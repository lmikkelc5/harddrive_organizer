"""End to end on a generated test drive (TEST_DRIVE.md):

phase 1 → second run changes nothing → Mom's edits → phase 2 → second run changes nothing.
Unbuilt features are xfail; HEIC/macOS/symlink-only scenarios skip with a reason.
"""

import os

import pytest

from photo_organizer.testdrive.check import FAIL, PENDING, SKIP
from photo_organizer.testdrive.flow import full, in_process_organizer
from photo_organizer.testdrive.make import NotATestDrive, make


@pytest.fixture(scope="module")
def flow(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("td") / "drive")
    return full(root, in_process_organizer(), big=50, progress=lambda *_: None)


def _failures(results):
    return "\n".join(f"{r.id}: {r.detail} {r.more}" for r in results if r.status == FAIL)


@pytest.mark.parametrize("phase", ["first-run", "after-edit"])
def test_phase(flow, phase):
    results = [r for r in flow[phase] if r.feature != "idempotency"]
    assert not _failures(results), _failures(results)


@pytest.mark.parametrize("phase", ["first-run", "after-edit"])
def test_second_run_changes_nothing(flow, phase):
    results = [r for r in flow[phase] if r.feature == "idempotency"]
    assert results and not _failures(results), _failures(results)


@pytest.mark.parametrize("phase", ["first-run", "after-edit"])
def test_nothing_pending_or_skipped(flow, phase):
    pending = [r.id for r in flow[phase] if r.status == PENDING]
    if pending:
        pytest.xfail(f"features not built yet: {pending}")
    skipped = [f"{r.id} ({r.detail})" for r in flow[phase] if r.status == SKIP]
    if skipped:
        pytest.skip("skipped here: " + "; ".join(skipped))


def test_make_refuses_to_wipe_a_real_folder(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "precious.jpg").write_bytes(b"x")
    with pytest.raises(NotATestDrive):
        make(str(tmp_path / "real"), reset=True)
    assert os.path.exists(tmp_path / "real" / "precious.jpg")


def test_make_is_deterministic(tmp_path):
    a = make(str(tmp_path / "a"), big=5)
    b = make(str(tmp_path / "b"), big=5)
    assert [f["sha256"] for f in a["files"]] == [f["sha256"] for f in b["files"]]
