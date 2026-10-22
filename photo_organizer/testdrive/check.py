"""`check`: compare a test drive with its expected.json."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field

from .. import names
from ..fileops import symlinks_supported
from .features import BUILT_FEATURES
from .make import MANIFEST

PASS, FAIL, SKIP, PENDING = "pass", "fail", "skip", "pending"


@dataclass
class Result:
    id: str
    feature: str
    status: str
    detail: str = ""
    more: list[str] = field(default_factory=list)


def _symbols(stream) -> dict[str, str]:
    fancy = {PASS: "✓", FAIL: "✗", SKIP: "–", PENDING: "…"}
    enc = getattr(stream, "encoding", None) or "utf-8"
    try:
        "".join(fancy.values()).encode(enc)
        return fancy
    except (UnicodeEncodeError, LookupError):
        return {PASS: "OK", FAIL: "XX", SKIP: "--", PENDING: ".."}


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index_drive(root: str) -> dict[str, list[str]]:
    """sha256 -> drive-relative paths of real files (symlinks and app records excluded)."""
    skip_top = {MANIFEST}
    skip_app = {names.CATALOG, names.CATALOG_BACKUPS, names.LOGS, names.DRIVE_MARKER, names.LOCK}
    out: dict[str, list[str]] = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == names.APP_DATA:
            dirnames[:] = [d for d in dirnames if d not in skip_app]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if os.path.islink(p) or rel in skip_top:
                continue
            if rel_dir == names.APP_DATA and fn in skip_app:
                continue
            out[_sha(p)].append(rel)
    return out


def _catalog(root: str):
    path = os.path.join(root, names.APP_DATA, names.CATALOG)
    if not os.path.exists(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _labels_of(con, photo_id: int) -> list[str]:
    rows = con.execute("SELECT l.group_name, l.label FROM labels l JOIN photo_labels pl ON pl.label_id = l.id "
                       "WHERE pl.photo_id = ?", (photo_id,)).fetchall()
    return sorted(f"{r['group_name']}: {r['label']}" for r in rows)


def _check_file(root, entry, found, con, links_ok) -> Result:
    exp = entry["expect"]
    r = Result(entry["id"], entry["feature"], PASS)
    paths = found.get(entry["sha256"], [])
    want_dir, want_name = exp.get("dir"), exp.get("name")
    match = None
    for p in paths:
        d, n = (p.rsplit("/", 1) + [""])[:2] if "/" in p else ("", p)
        if (want_dir is None or d == want_dir) and (want_name is None or n == want_name):
            match = p
            break
    want = f"{want_dir}/{want_name or '<any name>'}"
    if match is None:
        r.status = FAIL
        r.detail = f"expected {want}"
        r.more.append("found    " + (", ".join(paths) if paths else "nowhere (file missing)"))
        return r
    r.detail = match

    row = con.execute("SELECT * FROM photos WHERE sha256 = ?", (entry["sha256"],)).fetchone() if con else None
    checks = {k: exp[k] for k in ("date", "precision", "reject_reason", "gps", "labels") if k in exp}
    if checks and row is None:
        r.status = FAIL
        r.more.append("not in the catalog" if con else "no catalog yet (has the organizer run?)")
        return r
    if "date" in checks and row["taken_at"] != checks["date"]:
        r.more.append(f"date: expected {checks['date']}, catalog has {row['taken_at']}")
    if "precision" in checks and row["date_precision"] != checks["precision"]:
        r.more.append(f"precision: expected {checks['precision']}, catalog has {row['date_precision']}")
    if "reject_reason" in checks and row["reject_reason"] != checks["reject_reason"]:
        r.more.append(f"reject reason: expected {checks['reject_reason']}, catalog has {row['reject_reason']}")
    if "gps" in checks:
        lat, lon = checks["gps"]
        if row["gps_lat"] is None or abs(row["gps_lat"] - lat) > 1e-4 or abs(row["gps_lon"] - lon) > 1e-4:
            r.more.append(f"gps: expected {lat}, {lon}, catalog has {row['gps_lat']}, {row['gps_lon']}")
    if "labels" in checks and _labels_of(con, row["id"]) != sorted(checks["labels"]):
        r.more.append(f"labels: expected {sorted(checks['labels'])}, catalog has {_labels_of(con, row['id'])}")
    if r.more:
        r.status = FAIL
        return r

    for folder in exp.get("links", []):
        if not links_ok:
            r.more.append(f"link check skipped (no symlinks here): {folder}")
            continue
        target = os.path.realpath(os.path.join(root, match))
        abs_folder = os.path.join(root, folder)
        hits = [f for f in (os.listdir(abs_folder) if os.path.isdir(abs_folder) else [])
                if os.path.islink(os.path.join(abs_folder, f))
                and os.path.realpath(os.path.join(abs_folder, f)) == target]
        if not hits:
            r.status = FAIL
            r.more.append(f"no link in {folder}")
    return r


def _check_other(root, c) -> Result:
    r = Result(c["id"], c["feature"], PASS)
    if c["type"] == "absent":
        if os.path.lexists(os.path.join(root, c["path"])):
            r.status, r.detail = FAIL, f"{c['path']} should be gone but is still there"
        else:
            r.detail = f"{c['path']} is gone"
    elif c["type"] == "inbox-only":
        inbox = os.path.join(root, names.INBOX)
        left = sorted(os.path.relpath(os.path.join(dp, f), inbox).replace(os.sep, "/")
                      for dp, _, fs in os.walk(inbox) for f in fs)
        if left != sorted(c["files"]):
            r.status = FAIL
            r.detail = f"inbox should hold only {sorted(c['files'])}"
            r.more.append(f"it holds {left}")
        else:
            r.detail = f"inbox holds only {', '.join(c['files'])}"
    return r


def _check_summary(con, expected: dict, phase: str) -> Result:
    r = Result("run-summary", "summary", PASS)
    if con is None:
        r.status, r.detail = FAIL, "no catalog yet (has the organizer run?)"
        return r
    runs = con.execute("SELECT counts FROM runs WHERE finished_at IS NOT NULL ORDER BY id").fetchall()
    if not runs:
        r.status, r.detail = FAIL, "no finished run in the catalog"
        return r
    counts = json.loads(runs[0]["counts"]) if phase == "first-run" else json.loads(runs[-1]["counts"])
    diffs = [f"{k}: expected {v}, run said {counts.get(k)}" for k, v in expected.items() if counts.get(k) != v]
    if diffs:
        r.status, r.detail, r.more = FAIL, "counts differ", diffs
    else:
        r.detail = ", ".join(f"{k}={v}" for k, v in expected.items() if v)
    return r


def check(root: str, phase: str = "first-run", feature: str | None = None) -> list[Result]:
    with open(os.path.join(root, MANIFEST), encoding="utf-8") as f:
        manifest = json.load(f)
    found = index_drive(root)
    con = _catalog(root)
    links_ok = symlinks_supported(os.path.join(root, names.APP_DATA))
    results: list[Result] = []
    try:
        for entry in manifest["files"]:
            if entry["phase"] != phase or (feature and entry["feature"] != feature):
                continue
            if entry["feature"] not in BUILT_FEATURES:
                results.append(Result(entry["id"], entry["feature"], PENDING, "feature not built yet"))
                continue
            results.append(_check_file(root, entry, found, con, links_ok))
        for c in manifest.get("checks", []):
            if c["phase"] != phase or (feature and c["feature"] != feature):
                continue
            if c["feature"] not in BUILT_FEATURES:
                results.append(Result(c["id"], c["feature"], PENDING, "feature not built yet"))
                continue
            results.append(_check_other(root, c))
        for s in manifest.get("skipped", []):
            if not feature or s["feature"] == feature:
                results.append(Result(s["id"], s["feature"], SKIP, s["reason"]))
        if not feature and phase in manifest.get("summary", {}):
            results.append(_check_summary(con, manifest["summary"][phase], phase))
    finally:
        if con:
            con.close()
    return results


def print_results(root: str, phase: str, results: list[Result], stream=None) -> None:
    stream = stream or sys.stdout
    sym = _symbols(stream)
    width = max((len(r.id) for r in results), default=10) + 2
    print(f"Test drive check: {root}  (phase: {phase})", file=stream)
    by_feature: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        by_feature[r.feature].append(r)
    for feat, items in by_feature.items():
        print(f"\n{feat}", file=stream)
        for r in items:
            print(f"  {sym[r.status]} {r.id.ljust(width)}{r.detail}", file=stream)
            for m in r.more:
                print(f"    {' ' * width}{m}", file=stream)
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, SKIP, PENDING)}
    print(f"\n{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped, {counts[PENDING]} pending",
          file=stream)
