"""`full`: the whole test-drive sequence in one go.

make → organize → check first-run → organize again, nothing changes →
edit → organize → check after-edit → organize again, nothing changes.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Callable

from .check import FAIL, PASS, Result, check
from .edit import edit
from .features import TEST_TIMEZONE
from .make import make
from .snapshot import diff, snapshot


def subprocess_organizer(app: str | None = None) -> Callable[[str], None]:
    """Run the organizer as a separate program: the Python package, or a built app binary."""
    base = [app] if app else [sys.executable, "-m", "photo_organizer"]

    def run(root: str) -> None:
        proc = subprocess.run([*base, "--drive", root, "--timezone", TEST_TIMEZONE],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"organizer exited {proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
    return run


def in_process_organizer() -> Callable[[str], None]:
    from ..layout import Drive
    from ..run import get_timezone, organize

    class _Quiet:
        def info(self, m): pass
        def error(self, m): pass
        def notify(self, m): pass

    def run(root: str) -> None:
        organize(Drive(root), _Quiet(), tz=get_timezone(TEST_TIMEZONE))
    return run


def _idempotent(root: str, organizer, label: str) -> Result:
    before = snapshot(root)
    organizer(root)
    changes = diff(before, snapshot(root))
    r = Result(f"second-run-{label}", "idempotency", PASS, "running again changed nothing")
    if changes:
        r.status, r.detail, r.more = FAIL, f"running again changed {len(changes)} path(s)", changes[:20]
    return r


def full(root: str, organizer=None, big: int = 0, progress=print) -> dict[str, list[Result]]:
    organizer = organizer or subprocess_organizer()
    out: dict[str, list[Result]] = {}

    progress(f"Making test drive in {root} ...")
    make(root, reset=True, big=big)
    t = time.time()
    progress("Running the organizer (first run) ...")
    organizer(root)
    progress(f"  took {time.time() - t:.1f} s")
    out["first-run"] = check(root, "first-run")
    out["first-run"].append(_idempotent(root, organizer, "after-first-run"))

    progress("Making Mom's edits, then running the organizer again ...")
    edit(root)
    organizer(root)
    out["after-edit"] = check(root, "after-edit")
    out["after-edit"].append(_idempotent(root, organizer, "after-edit"))
    return out


def any_failed(results: dict[str, list[Result]]) -> bool:
    return any(r.status == FAIL for rs in results.values() for r in rs)
