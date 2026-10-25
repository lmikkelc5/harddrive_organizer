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

# expect key -> catalog column, for simple equality checks
_COLUMNS = {
    "date": "taken_at",
    "precision": "date_precision",
    "source": "date_source",
    "reject_reason": "reject_reason",
    "raw_meta_date": "raw_meta_date",
    "best_guess": "best_guess",
    "status": "status",
}


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


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_SKIP_APP = {names.CATALOG, names.CATALOG_BACKUPS, names.LOGS, names.DRIVE_MARKER, names.LOCK,
             names.CATALOG + "-journal", names.CATALOG + "-wal", names.CATALOG + "-shm"}


def index_drive(root: str) -> dict[str, list[str]]:
    """sha256 -> drive-relative paths of real files (symlinks and app records excluded)."""
    out: dict[str, list[str]] = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == names.APP_DATA:
            dirnames[:] = [d for d in dirnames if d not in _SKIP_APP]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if os.path.islink(p) or rel == MANIFEST or fn == names.LABEL_ID_FILE:
                continue
            if rel_dir == names.APP_DATA and fn in _SKIP_APP:
                continue
            out[sha256_of(p)].append(rel)
    return out


def open_catalog(root: str):
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


def _split(rel: str) -> tuple[str, str]:
    return tuple(rel.rsplit("/", 1)) if "/" in rel else ("", rel)


class Checker:
    def __init__(self, root: str, manifest: dict, phase: str) -> None:
        self.root = root
        self.manifest = manifest
        self.phase = phase
        self.found = index_drive(root)
        self.con = open_catalog(root)
        self.links_ok = symlinks_supported(os.path.join(root, names.APP_DATA))
        self.sha_of_id = {e["id"]: e["sha256"] for e in manifest["files"]}
        self.links_skipped = 0

    def close(self) -> None:
        if self.con:
            self.con.close()

    def _row(self, sha: str):
        if not self.con:
            return None
        return self.con.execute("SELECT * FROM photos WHERE sha256 = ?", (sha,)).fetchone()

    # ---- one file ----
    def file(self, entry: dict) -> Result:
        exp = entry["expect"]
        r = Result(entry["id"], entry["feature"], PASS)
        paths = self.found.get(entry["sha256"], [])

        if exp.get("deleted"):
            real = [p for p in paths if p.startswith(names.LIBRARY + "/")]
            if real:
                r.status, r.detail = FAIL, "should have been deleted"
                r.more.append("found    " + ", ".join(real))
            else:
                r.detail = "deleted, as Mom did"
            self._catalog_checks(entry, r)
            return r

        want_dir, want_name = exp.get("dir"), exp.get("name")
        match = next((p for p in paths
                      if (want_dir is None or _split(p)[0] == want_dir)
                      and (want_name is None or _split(p)[1] == want_name)), None)
        if match is None:
            r.status = FAIL
            r.detail = f"expected {want_dir}/{want_name or '<any name>'}"
            r.more.append("found    " + (", ".join(paths) if paths else "nowhere (file missing)"))
            return r
        r.detail = match
        self._catalog_checks(entry, r)
        if r.status == FAIL:
            return r
        self._link_checks(exp, match, r)
        return r

    def _catalog_checks(self, entry: dict, r: Result) -> None:
        exp = entry["expect"]
        if "sidecar_of" in exp:
            if not self.con:
                r.status = FAIL
                r.more.append("no catalog yet (has the organizer run?)")
                return
            owner = self._row(self.sha_of_id.get(exp["sidecar_of"], ""))
            sc = self.con.execute("SELECT * FROM sidecars WHERE rel_path = ?", (r.detail,)).fetchone()
            if sc is None:
                r.more.append("sidecar not in the catalog")
            elif owner is None or sc["photo_id"] != owner["id"]:
                r.more.append(f"sidecar not linked to {exp['sidecar_of']}")
            if r.more:
                r.status = FAIL
            return

        wanted = [k for k in (*_COLUMNS, "gps", "labels", "conflict", "pair_with", "edited_of") if k in exp]
        if not wanted:
            return
        row = self._row(entry["sha256"])
        if row is None:
            r.status = FAIL
            r.more.append("not in the catalog" if self.con else "no catalog yet (has the organizer run?)")
            return
        for key in wanted:
            want = exp[key]
            if key in _COLUMNS:
                have = row[_COLUMNS[key]]
                if have != want:
                    r.more.append(f"{key}: expected {want}, catalog has {have}")
            elif key == "gps":
                lat, lon = want
                if row["gps_lat"] is None or abs(row["gps_lat"] - lat) > 1e-4 or abs(row["gps_lon"] - lon) > 1e-4:
                    r.more.append(f"gps: expected {lat}, {lon}, catalog has {row['gps_lat']}, {row['gps_lon']}")
            elif key == "labels":
                have = _labels_of(self.con, row["id"])
                if have != sorted(want):
                    r.more.append(f"labels: expected {sorted(want)}, catalog has {have}")
            elif key == "conflict":
                if bool(row["date_conflict"]) != want:
                    r.more.append(f"date conflict should {'' if want else 'not '}be logged "
                                  f"(catalog has {row['date_conflict']!r})")
            elif key in ("pair_with", "edited_of"):
                other = self._row(self.sha_of_id.get(want, ""))
                col = "pair_id" if key == "pair_with" else "edited_of_id"
                if other is None or row[col] != other["id"]:
                    r.more.append(f"{key}: should point at {want}")
        if r.more:
            r.status = FAIL

    def _link_checks(self, exp: dict, match: str, r: Result) -> None:
        if not exp.get("links"):
            return
        if not self.links_ok:
            self.links_skipped += 1
            return
        target = os.path.realpath(os.path.join(self.root, match))
        for folder in exp["links"]:
            abs_folder = os.path.join(self.root, folder)
            entries = os.listdir(abs_folder) if os.path.isdir(abs_folder) else []
            if not any(os.path.islink(os.path.join(abs_folder, f))
                       and os.path.realpath(os.path.join(abs_folder, f)) == target for f in entries):
                r.status = FAIL
                r.more.append(f"no link in {folder}")

    # ---- other checks ----
    def other(self, c: dict) -> Result:
        r = Result(c["id"], c["feature"], PASS)
        t = c["type"]
        if c.get("needs_links") and not self.links_ok:
            return Result(c["id"], c["feature"], SKIP, "needs symlinks, which this computer can't make")
        if t in ("absent", "present"):
            there = os.path.lexists(os.path.join(self.root, c["path"]))
            if (t == "absent") == there:
                r.status = FAIL
                r.detail = f"{c['path']} should {'be gone' if t == 'absent' else 'exist'}"
            else:
                r.detail = f"{c['path']} {'is gone' if t == 'absent' else 'exists'}"
        elif t == "inbox-only":
            inbox = os.path.join(self.root, names.INBOX)
            left = sorted(os.path.relpath(os.path.join(dp, f), inbox).replace(os.sep, "/")
                          for dp, _, fs in os.walk(inbox) for f in fs)
            left_dirs = sorted(os.path.relpath(os.path.join(dp, d), inbox).replace(os.sep, "/")
                               for dp, ds, _ in os.walk(inbox) for d in ds)
            if left != sorted(c["files"]) or left_dirs:
                r.status = FAIL
                r.detail = f"inbox should hold only {sorted(c['files']) or 'nothing'}"
                r.more.append(f"it holds {left + [d + '/' for d in left_dirs]}")
            else:
                r.detail = "inbox holds only " + (", ".join(c["files"]) or "nothing")
        elif t == "label-count":
            if not self.con:
                return Result(c["id"], c["feature"], FAIL, "no catalog yet")
            n = self.con.execute("SELECT COUNT(*) FROM labels WHERE group_key = ? AND label_key = ?",
                                 (c["group"].lower(), c["label"].casefold())).fetchone()[0]
            if n != c["count"]:
                r.status, r.detail = FAIL, f"expected {c['count']} '{c['group']}: {c['label']}' label(s), found {n}"
            else:
                r.detail = f"{n} '{c['group']}: {c['label']}' label"
        elif t == "links-healthy":
            if not self.links_ok:
                return Result(c["id"], c["feature"], SKIP, "needs symlinks, which this computer can't make")
            broken = []
            for dp, ds, fs in os.walk(os.path.join(self.root, names.LIBRARY)):
                for f in fs + ds:
                    p = os.path.join(dp, f)
                    if os.path.islink(p) and not os.path.isfile(p):
                        broken.append(os.path.relpath(p, self.root).replace(os.sep, "/"))
            if broken:
                r.status, r.detail, r.more = FAIL, f"{len(broken)} broken link(s)", broken[:10]
            else:
                r.detail = "every link points at a real photo"
        elif t == "copy":
            paths = self.found.get(c["sha256"], [])
            rows = (self.con.execute("SELECT rel_path FROM photos WHERE sha256 = ?", (c["sha256"],)).fetchall()
                    if self.con else [])
            if c["path"] not in paths:
                r.status, r.detail = FAIL, f"her copy {c['path']} was moved or removed"
            elif len(rows) != 1 or rows[0]["rel_path"] == c["path"]:
                r.status, r.detail = FAIL, f"copy should be left out of the catalog (rows: {[x[0] for x in rows]})"
            else:
                r.detail = f"{c['path']} left alone, cataloged once"
        else:
            r.status, r.detail = FAIL, f"unknown check type {t}"
        return r

    def summary(self, expected: dict) -> Result:
        r = Result("run-summary", "summary", PASS)
        if self.con is None:
            return Result(r.id, r.feature, FAIL, "no catalog yet (has the organizer run?)")
        runs = self.con.execute("SELECT counts FROM runs WHERE finished_at IS NOT NULL ORDER BY id").fetchall()
        index = 0 if self.phase == "first-run" else self.manifest.get("edit_run_index")
        if index is None or index >= len(runs):
            return Result(r.id, r.feature, FAIL, "the organizer hasn't run for this phase yet")
        counts = json.loads(runs[index]["counts"])
        diffs = [f"{k}: expected {v}, run said {counts.get(k)}" for k, v in expected.items() if counts.get(k) != v]
        if diffs:
            r.status, r.detail, r.more = FAIL, "counts differ", diffs
        else:
            r.detail = ", ".join(f"{k}={v}" for k, v in expected.items() if v and not isinstance(v, list))
        return r


def check(root: str, phase: str = "first-run", feature: str | None = None) -> list[Result]:
    with open(os.path.join(root, MANIFEST), encoding="utf-8") as f:
        manifest = json.load(f)
    if phase == "after-edit" and "after-edit" not in manifest.get("summary", {}):
        return [Result("after-edit", "manual-edits", FAIL, "run `edit` (then the organizer) first")]
    ck = Checker(root, manifest, phase)
    results: list[Result] = []
    try:
        for entry in manifest["files"]:
            if entry["phase"] != phase or (feature and entry["feature"] != feature):
                continue
            if entry["feature"] not in BUILT_FEATURES:
                results.append(Result(entry["id"], entry["feature"], PENDING, "feature not built yet"))
                continue
            results.append(ck.file(entry))
        for c in manifest.get("checks", []):
            if c["phase"] != phase or (feature and c["feature"] != feature):
                continue
            if c["feature"] not in BUILT_FEATURES:
                results.append(Result(c["id"], c["feature"], PENDING, "feature not built yet"))
                continue
            results.append(ck.other(c))
        for s in manifest.get("skipped", []):
            if s.get("phase", "all") in ("all", phase) and (not feature or s["feature"] == feature):
                results.append(Result(s["id"], s["feature"], SKIP, s["reason"]))
        if ck.links_skipped:
            results.append(Result("link-checks", "summary", SKIP,
                                  f"links not checked for {ck.links_skipped} files (no symlinks on this computer)"))
        if not feature and phase in manifest.get("summary", {}):
            results.append(ck.summary(manifest["summary"][phase]))
    finally:
        ck.close()
    return results


def print_results(root: str, phase: str, results: list[Result], stream=None, quiet_features=("big",)) -> None:
    stream = stream or sys.stdout
    sym = _symbols(stream)
    width = max((len(r.id) for r in results if r.feature not in quiet_features), default=10) + 2
    print(f"Test drive check: {root}  (phase: {phase})", file=stream)
    by_feature: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        by_feature[r.feature].append(r)
    for feat, items in by_feature.items():
        print(f"\n{feat}", file=stream)
        shown = items
        if feat in quiet_features:
            # Thousands of lines aren't useful: show failures plus one summary line.
            shown = [r for r in items if r.status != PASS]
            ok = len(items) - len(shown)
            print(f"  {sym[PASS]} {ok} of {len(items)} files in the right place", file=stream)
        for r in shown:
            print(f"  {sym[r.status]} {r.id.ljust(width)}{r.detail}", file=stream)
            for m in r.more:
                print(f"    {' ' * width}{m}", file=stream)
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, SKIP, PENDING)}
    print(f"\n{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped, {counts[PENDING]} pending",
          file=stream)
