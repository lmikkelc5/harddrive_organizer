"""The SQLite catalog: the source of truth for every photo on the drive.

All paths are stored relative to the drive root, with forward slashes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    app_version TEXT,
    counts TEXT
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    rel_path TEXT NOT NULL,
    original_name TEXT,
    original_inbox_path TEXT,
    kind TEXT NOT NULL,                 -- photo / video / other
    taken_at TEXT,                      -- ISO, precision-shaped (see dates.FuzzyDate.iso)
    tz_offset TEXT,
    date_source TEXT,
    date_precision TEXT NOT NULL DEFAULT 'unknown',
    raw_meta_date TEXT,
    reject_reason TEXT,
    date_conflict TEXT,
    best_guess TEXT,
    guess_source TEXT,
    gps_lat REAL,
    gps_lon REAL,
    camera_make TEXT,
    camera_model TEXT,
    size INTEGER,
    mtime REAL,
    imported_at TEXT,
    run_id INTEGER REFERENCES runs(id),
    status TEXT NOT NULL DEFAULT 'ok',  -- ok / missing
    pair_id INTEGER,                    -- Live Photo partner
    edited_of_id INTEGER                -- iPhone edit of this photo
);
CREATE INDEX IF NOT EXISTS photos_rel_path ON photos(rel_path);
CREATE INDEX IF NOT EXISTS photos_size ON photos(size);

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY,
    group_name TEXT NOT NULL,
    label TEXT NOT NULL,
    group_key TEXT NOT NULL,
    label_key TEXT NOT NULL,
    UNIQUE (group_key, label_key)
);

CREATE TABLE IF NOT EXISTS photo_labels (
    photo_id INTEGER NOT NULL REFERENCES photos(id),
    label_id INTEGER NOT NULL REFERENCES labels(id),
    PRIMARY KEY (photo_id, label_id)
);

CREATE TABLE IF NOT EXISTS sidecars (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER REFERENCES photos(id),
    rel_path TEXT NOT NULL,
    original_name TEXT,
    original_inbox_path TEXT,
    run_id INTEGER
);

CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    reason TEXT,
    at TEXT NOT NULL
);

-- Copies Mom made inside My photos: left alone, remembered so we don't re-hash them.
CREATE TABLE IF NOT EXISTS known_copies (
    rel_path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER,
    mtime REAL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    kind TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def label_keys(group: str, label: str) -> tuple[str, str]:
    return group.lower(), label.casefold()


class Catalog:
    def __init__(self, path: str) -> None:
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            # WAL makes the commit after every moved file cheap (big imports were
            # spending half their time here) and still survives an app crash.
            self.db.execute("PRAGMA journal_mode = WAL")
            self.db.execute("PRAGMA synchronous = NORMAL")
        self.db.executescript(SCHEMA)
        self.db.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()
        self.run_id: int | None = None

    @classmethod
    def in_memory_copy(cls, path: str) -> "Catalog":
        """For --dry-run: work on a throwaway copy of the real catalog."""
        cat = cls(":memory:")
        if os.path.exists(path):
            src = sqlite3.connect(path)
            src.backup(cat.db)
            src.close()
            cat.db.executescript(SCHEMA)
        return cat

    def close(self) -> None:
        self.db.close()

    def commit(self) -> None:
        self.db.commit()

    # ---- runs ----
    def start_run(self, app_version: str) -> int:
        cur = self.db.execute(
            "INSERT INTO runs(started_at, app_version) VALUES (?, ?)", (now_iso(), app_version)
        )
        self.db.commit()
        self.run_id = cur.lastrowid
        return self.run_id

    def finish_run(self, counts: dict) -> None:
        self.db.execute(
            "UPDATE runs SET finished_at = ?, counts = ? WHERE id = ?",
            (now_iso(), json.dumps(counts), self.run_id),
        )
        self.db.commit()

    def log_event(self, kind: str, detail: str) -> None:
        self.db.execute(
            "INSERT INTO events(run_id, kind, detail, at) VALUES (?, ?, ?, ?)",
            (self.run_id, kind, detail, now_iso()),
        )

    def record_move(self, src: str, dst: str, reason: str) -> None:
        self.db.execute(
            "INSERT INTO moves(run_id, src, dst, reason, at) VALUES (?, ?, ?, ?, ?)",
            (self.run_id, src, dst, reason, now_iso()),
        )

    # ---- photos ----
    def add_photo(self, **fields) -> int:
        fields.setdefault("imported_at", now_iso())
        fields.setdefault("run_id", self.run_id)
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self.db.execute(f"INSERT INTO photos({cols}) VALUES ({marks})", tuple(fields.values()))
        return cur.lastrowid

    def update_photo(self, photo_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE photos SET {sets} WHERE id = ?", (*fields.values(), photo_id))

    def photo(self, photo_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()

    def photo_by_hash(self, sha: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM photos WHERE sha256 = ?", (sha,)).fetchone()

    def photos(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.db.execute("SELECT * FROM photos WHERE status = ? ORDER BY id", (status,)).fetchall()
        return self.db.execute("SELECT * FROM photos ORDER BY id").fetchall()

    # ---- labels ----
    def get_or_create_label(self, group: str, label: str) -> int:
        gk, lk = label_keys(group, label)
        row = self.db.execute(
            "SELECT id FROM labels WHERE group_key = ? AND label_key = ?", (gk, lk)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.db.execute(
            "INSERT INTO labels(group_name, label, group_key, label_key) VALUES (?, ?, ?, ?)",
            (group, label, gk, lk),
        )
        return cur.lastrowid

    def label(self, label_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()

    def find_label(self, group: str, label: str) -> sqlite3.Row | None:
        gk, lk = label_keys(group, label)
        return self.db.execute(
            "SELECT * FROM labels WHERE group_key = ? AND label_key = ?", (gk, lk)
        ).fetchone()

    def labels(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM labels ORDER BY group_name, label").fetchall()

    def rename_label(self, label_id: int, new_label: str) -> int:
        """Rename; if another label already has that name, merge into it. Returns the surviving id."""
        row = self.label(label_id)
        existing = self.find_label(row["group_name"], new_label)
        if existing and existing["id"] != label_id:
            self.db.execute(
                "INSERT OR IGNORE INTO photo_labels(photo_id, label_id) "
                "SELECT photo_id, ? FROM photo_labels WHERE label_id = ?",
                (existing["id"], label_id),
            )
            self.db.execute("DELETE FROM photo_labels WHERE label_id = ?", (label_id,))
            self.db.execute("DELETE FROM labels WHERE id = ?", (label_id,))
            return existing["id"]
        _, lk = label_keys(row["group_name"], new_label)
        self.db.execute("UPDATE labels SET label = ?, label_key = ? WHERE id = ?", (new_label, lk, label_id))
        return label_id

    def add_label(self, photo_id: int, label_id: int) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO photo_labels(photo_id, label_id) VALUES (?, ?)", (photo_id, label_id)
        )
        return cur.rowcount > 0

    def photos_with_label(self, label_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT p.* FROM photos p JOIN photo_labels pl ON pl.photo_id = p.id "
            "WHERE pl.label_id = ? AND p.status = 'ok' ORDER BY p.taken_at, p.id",
            (label_id,),
        ).fetchall()

    def labels_of(self, photo_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT l.* FROM labels l JOIN photo_labels pl ON pl.label_id = l.id WHERE pl.photo_id = ?",
            (photo_id,),
        ).fetchall()

    # ---- sidecars ----
    def add_sidecar(self, **fields) -> int:
        fields.setdefault("run_id", self.run_id)
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self.db.execute(f"INSERT INTO sidecars({cols}) VALUES ({marks})", tuple(fields.values())).lastrowid

    # ---- known copies ----
    def known_copy(self, rel_path: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM known_copies WHERE rel_path = ?", (rel_path,)).fetchone()

    def remember_copy(self, rel_path: str, sha: str, size: int, mtime: float) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO known_copies(rel_path, sha256, size, mtime) VALUES (?, ?, ?, ?)",
            (rel_path, sha, size, mtime),
        )

    def forget_copies_not_in(self, rel_paths: Iterable[str]) -> None:
        keep = set(rel_paths)
        for row in self.db.execute("SELECT rel_path FROM known_copies").fetchall():
            if row["rel_path"] not in keep:
                self.db.execute("DELETE FROM known_copies WHERE rel_path = ?", (row["rel_path"],))


def backup_catalog(catalog_path: str, backup_dir: str, keep: int = 10) -> str | None:
    """Copy catalog.db into catalog-backups/, keeping the newest `keep` copies."""
    if not os.path.exists(catalog_path):
        return None
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dst = os.path.join(backup_dir, f"catalog-{stamp}.db")
    src = sqlite3.connect(catalog_path)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    backups = sorted(f for f in os.listdir(backup_dir) if f.startswith("catalog-") and f.endswith(".db"))
    for old in backups[:-keep]:
        os.remove(os.path.join(backup_dir, old))
    return dst
