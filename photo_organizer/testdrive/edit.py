"""`edit`: act like Mom rearranging things in Finder after the first run.

Each edit records what the next organizer run should leave behind, as
"after-edit" entries in expected.json. Files not touched by an edit keep
their first-run expectations.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime

from .. import names
from ..fileops import symlinks_supported
from .check import index_drive, open_catalog
from .make import MANIFEST, write_spec
from .scenarios import (BY_DATE, DEFAULT_MTIME, LIB, Check, Spec, exact, exif_at, expected_summary, event)

F = "manual-edits"


class EditError(Exception):
    pass


class _Editor:
    def __init__(self, root: str, manifest: dict) -> None:
        self.root = root
        self.manifest = manifest
        self.found = index_drive(root)
        self.links_ok = symlinks_supported(os.path.join(root, names.APP_DATA))
        self.first = {e["id"]: e for e in manifest["files"] if e["phase"] == "first-run"}
        self.after = {}
        for i, e in self.first.items():
            a = copy.deepcopy(e)
            a["phase"] = "after-edit"
            self.after[i] = a
        self.checks: list[Check] = []
        self.done: list[str] = []
        self.skipped: list[dict] = []

    # ---- helpers ----
    def abs(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/"))

    def where(self, file_id: str) -> str:
        e = self.first[file_id]
        rel = f"{e['expect']['dir']}/{e['expect']['name']}"
        if rel not in self.found.get(e["sha256"], []):
            raise EditError(f"{file_id} isn't at {rel}. Run the organizer and `check` before `edit`.")
        return rel

    def move(self, src: str, dst: str) -> None:
        os.makedirs(os.path.dirname(self.abs(dst)), exist_ok=True)
        os.rename(self.abs(src), self.abs(dst))

    def expect(self, file_id: str, **changes) -> None:
        a = self.after[file_id]
        a["feature"] = F
        a["expect"].update(changes)

    def skip(self, edit_id: str, why: str) -> None:
        self.skipped.append(dict(id=edit_id, feature=F, reason=why, phase="after-edit"))

    def has(self, *ids: str) -> bool:
        return all(i in self.first for i in ids)

    # ---- the edits (TEST_DRIVE.md, Phase 2) ----
    def run(self) -> None:
        if self.has("sanity-no-clues"):
            self.move(self.where("sanity-no-clues"), f"{BY_DATE}/2010/photo.jpg")
            self.expect("sanity-no-clues", dir=f"{BY_DATE}/2010", name="photo.jpg", date="2010",
                        precision="year", source="manual")
            self.done.append("Moved Unsorted/Date unknown/photo.jpg into By date/2010/")

        if self.has("sanity-future"):
            self.move(self.where("sanity-future"), f"{BY_DATE}/2010/03 - March/IMG_0007.JPG")
            self.expect("sanity-future", dir=f"{BY_DATE}/2010/03 - March", date="2010-03",
                        precision="month", source="manual")
            self.done.append("Moved IMG_0007.JPG into a month folder she made: By date/2010/03 - March/")

        if self.has("guess-camping-411", "guess-camping-412"):
            self.where("guess-camping-411")
            self.move(f"{LIB}/Unsorted/Probably 2011/Camping", f"{BY_DATE}/2011/Camping")
            for n in (411, 412):
                # Her placement confirms the guess, so it's no longer stored as one.
                self.expect(f"guess-camping-{n}", dir=f"{BY_DATE}/2011/Camping", date="2011",
                            precision="year", source="manual", best_guess=None)
            self.done.append("Dragged the whole Unsorted/Probably 2011/Camping folder into By date/2011/")

        hawaii = f"{LIB}/By event/Hawaii 2026"
        maui = f"{LIB}/By event/Maui 2026"
        renamed = False
        if self.links_ok and os.path.isdir(self.abs(hawaii)):
            os.rename(self.abs(hawaii), self.abs(maui))
            renamed = True
            for a in self.after.values():
                exp = a["expect"]
                if "Event: Hawaii 2026" in exp.get("labels", []):
                    a["feature"] = F
                    exp["labels"] = [("Event: Maui 2026" if l == "Event: Hawaii 2026" else l) for l in exp["labels"]]
                    exp["links"] = [(maui if l == hawaii else l) for l in exp.get("links", [])]
            self.checks += [Check("edit-hawaii-not-recreated", F, "absent", path=hawaii, phase="after-edit"),
                            Check("edit-maui-kept", F, "present", path=maui, needs_links=True, phase="after-edit"),
                            Check("edit-one-maui-label", F, "label-count", group="Event", label="Maui 2026",
                                  count=1, phase="after-edit"),
                            Check("edit-no-hawaii-label", F, "label-count", group="Event", label="Hawaii 2026",
                                  count=0, phase="after-edit")]
            self.done.append("Renamed By event/Hawaii 2026 to Maui 2026")
        else:
            self.skip("edit-rename-event", "renaming an event folder needs symlinks, which this computer can't make")

        if self.has("label-christmas-2", "label-christmas-1"):
            os.remove(self.abs(self.where("label-christmas-2")))
            a = self.after["label-christmas-2"]
            a["feature"] = F
            a["expect"] = dict(deleted=True, status="missing")
            self.done.append("Deleted one Christmas 2025 photo from By date")

        if renamed and self.has("label-recipes-1"):
            src = self.where("label-recipes-1")
            self.move(src, f"{maui}/{src.rsplit('/', 1)[1]}")
            exp = self.after["label-recipes-1"]["expect"]
            self.expect("label-recipes-1", labels=sorted(exp["labels"] + ["Event: Maui 2026"]),
                        links=exp.get("links", []) + [maui])
            self.done.append("Moved a recipe photo from By date/2022/ into By event/Maui 2026/")
        else:
            self.skip("edit-drag-into-event", "dragging into an event folder needs symlinks, which this computer can't make")

        if self.has("basic-exif"):
            src = self.where("basic-exif")
            self.move(src, f"{BY_DATE}/2024/Mom favorite.jpg")
            self.expect("basic-exif", name="Mom favorite.jpg")
            self.done.append("Renamed By date/2024/2024-07-14_15-30-22.jpg to Mom favorite.jpg")

        if self.has("basic-whatsapp"):
            src = self.where("basic-whatsapp")
            dst = f"{BY_DATE}/2023/2023-11-05_18-22-10 copy.jpeg"
            shutil.copy2(self.abs(src), self.abs(dst))
            self.checks.append(Check("edit-copy-left-alone", F, "copy", path=dst,
                                     sha256=self.first["basic-whatsapp"]["sha256"], phase="after-edit"))
            self.done.append("Copied a photo within By date/2023/")

        if self.links_ok and self.has("label-yellowstone-1"):
            name = self.where("label-yellowstone-1").rsplit("/", 1)[1]
            link = self.abs(f"{LIB}/By event/Yellowstone 2019/{name}")
            if os.path.islink(link):
                os.unlink(link)
                self.after["label-yellowstone-1"]["feature"] = F
                self.done.append("Deleted one link from By event/Yellowstone 2019/ (it should come back)")
        else:
            self.skip("edit-delete-link", "deleting a link needs symlinks, which this computer can't make")

        new = Spec("edit-yellowstone-new", F, "event - yellowstone 2019/y_new.jpg", phase="after-edit",
                   exif=exif_at("2019-06-15 08:00:00"),
                   expect=exact("2019-06-15 08:00:00", **event("Yellowstone 2019")))
        entry = write_spec(self.root, new, {}, datetime.now())
        self.new_specs = [new]
        self.new_entries = [entry]
        self.checks.append(Check("edit-one-yellowstone-label", F, "label-count", group="Event",
                                 label="Yellowstone 2019", count=1, phase="after-edit"))
        self.done.append("Dropped a new inbox folder 'event - yellowstone 2019' with 1 photo")

        if self.has("edge-still-copying"):
            p = self.abs(self.where("edge-still-copying"))
            t = DEFAULT_MTIME.timestamp()
            os.utime(p, (t, t))
            self.expect("edge-still-copying", **exact("2024-01-01 12:00:00"))
            self.new_specs.append(Spec("edge-still-copying", F, "IMG_0099.JPG", expect={}, phase="after-edit"))
            self.done.append("Made IMG_0099.JPG old enough to pick up")

        self.checks += [Check("edit-inbox-empty", F, "inbox-only", files=[], phase="after-edit"),
                        Check("edit-links-healthy", F, "links-healthy", phase="after-edit")]
        # Keep the first run's folder checks, except ones the edits change on purpose.
        for c in self.manifest.get("checks", []):
            if c["phase"] != "first-run" or c["type"] == "inbox-only":
                continue
            if renamed and c.get("path") == hawaii:
                continue
            c2 = dict(c, phase="after-edit")
            self.checks.append(Check(**c2))


def edit(root: str) -> dict:
    path = os.path.join(root, MANIFEST)
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    if "after-edit" in manifest.get("summary", {}):
        raise EditError("This test drive was already edited. Make a fresh one with `make --reset`.")
    con = open_catalog(root)
    if con is None:
        raise EditError("Run the organizer on this test drive before `edit`.")
    try:
        runs_done = con.execute("SELECT COUNT(*) FROM runs WHERE finished_at IS NOT NULL").fetchone()[0]
    finally:
        con.close()

    ed = _Editor(root, manifest)
    ed.run()
    manifest["files"] += list(ed.after.values()) + ed.new_entries
    manifest["checks"] += [c.__dict__ for c in ed.checks]
    manifest["skipped"] += ed.skipped
    summary = expected_summary(ed.new_specs, "after-edit")
    manifest["summary"]["after-edit"] = summary
    manifest["edit_run_index"] = runs_done
    manifest["edits"] = ed.done
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest
