"""`snapshot`: every path on the drive with its hash, to prove a second run changes nothing."""

from __future__ import annotations

import os

from .. import names
from .check import sha256_of
from .make import MANIFEST

# App records that are expected to change on every run.
_VOLATILE = {names.CATALOG, names.CATALOG_BACKUPS, names.LOGS, names.LOCK, names.CATALOG + "-journal", names.CATALOG + "-wal", names.CATALOG + "-shm"}


def snapshot(root: str) -> list[str]:
    """Sorted lines: 'D path', 'F path sha256', 'L path -> target'."""
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == names.APP_DATA:
            dirnames[:] = [d for d in dirnames if d not in _VOLATILE]
            filenames = [f for f in filenames if f not in _VOLATILE]
        for d in dirnames:
            p = os.path.join(dirpath, d)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            lines.append(f"L {rel} -> {os.readlink(p)}" if os.path.islink(p) else f"D {rel}")
        for f in filenames:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel == MANIFEST:
                continue
            if os.path.islink(p):
                lines.append(f"L {rel} -> {os.readlink(p)}")
            else:
                lines.append(f"F {rel} {sha256_of(p)}")
    return sorted(lines)


def diff(before: list[str], after: list[str]) -> list[str]:
    b, a = set(before), set(after)
    return [f"- {x}" for x in sorted(b - a)] + [f"+ {x}" for x in sorted(a - b)]
