"""Views: folders of relative symlinks, generated from the catalog.

Adding a view = writing one function decorated with @register_view that
returns a list of ViewFolder. Sync only ever deletes symlinks, empty folders
and our own .label-id markers, never a real file.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable

from . import names
from .catalog import Catalog
from .fileops import FileOps, free_name, sha256_file
from .labels import FolderContext, Label
from .layout import Drive
from . import dates

log = logging.getLogger(__name__)


@dataclass
class ViewFolder:
    parts: tuple[str, ...]          # path under My Photos, e.g. ("By Trip", "Hawaii 2026")
    photos: list = field(default_factory=list)  # catalog rows
    label_id: int | None = None


ViewFn = Callable[[Catalog], list[ViewFolder]]
VIEWS: list[ViewFn] = []


def register_view(fn: ViewFn) -> ViewFn:
    VIEWS.append(fn)
    return fn


def safe_folder_name(text: str) -> str:
    """Make a label usable as a folder name on macOS."""
    t = re.sub(r"[/:]", "-", text).strip().strip(".")
    return t or "Untitled"


def _hide_live_videos(cat: Catalog, rows: list) -> list:
    """Live Photo videos would show up as a confusing second copy; hide them in views."""
    kinds = {r["id"]: r["kind"] for r in cat.photos()}
    return [r for r in rows if not (r["kind"] == "video" and r["pair_id"] and kinds.get(r["pair_id"]) == "photo")]


@register_view
def label_views(cat: Catalog) -> list[ViewFolder]:
    """By Trip / By Event / ... / Albums, one folder per label."""
    out = []
    for lab in cat.labels():
        rows = _hide_live_videos(cat, cat.photos_with_label(lab["id"]))
        if rows:
            out.append(ViewFolder((names.group_folder(lab["group_name"]), safe_folder_name(lab["label"])),
                                  rows, lab["id"]))
    return out


# ---------------------------------------------------------------------------
# Which top-level folders belong to views
# ---------------------------------------------------------------------------

_RESERVED = {names.BY_DATE, names.UNSORTED, names.DUPLICATES}


def group_for_root(root_name: str) -> str | None:
    if root_name == names.ALBUMS:
        return names.ALBUM_GROUP
    if root_name.startswith("By ") and root_name not in _RESERVED:
        return root_name[3:]
    return None


def view_roots(drive: Drive) -> list[str]:
    if not os.path.isdir(drive.library):
        return []
    return sorted(d for d in os.listdir(drive.library)
                  if group_for_root(d) and os.path.isdir(os.path.join(drive.library, d))
                  and not os.path.islink(os.path.join(drive.library, d)))


def _read_label_id(folder: str) -> int | None:
    try:
        with open(os.path.join(folder, names.LABEL_ID_FILE), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _real_files(folder: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            if not fn.startswith(".") and not os.path.islink(p):
                out.append(p)
    return out


# ---------------------------------------------------------------------------
# Before syncing: follow Mom's renames and photos she dragged into views
# ---------------------------------------------------------------------------

@dataclass
class AdoptReport:
    renamed: list[tuple[str, str]] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    to_import: list = field(default_factory=list)   # importer.SourceFile
    labeled: list[str] = field(default_factory=list)


def adopt_view_changes(drive: Drive, cat: Catalog, ops: FileOps) -> AdoptReport:
    report = AdoptReport()
    seen_ids: set[int] = set()
    for root in view_roots(drive):
        group = group_for_root(root)
        root_abs = os.path.join(drive.library, root)
        for child in sorted(os.listdir(root_abs)):
            folder = os.path.join(root_abs, child)
            if child.startswith(".") or os.path.islink(folder) or not os.path.isdir(folder):
                continue
            label_row = None
            lid = _read_label_id(folder)
            if lid is not None and lid not in seen_ids:
                label_row = cat.label(lid)
                if label_row and label_row["group_key"] != group.lower():
                    label_row = None
            if label_row is not None:
                seen_ids.add(label_row["id"])
                if safe_folder_name(label_row["label"]) != child:
                    new_id = cat.rename_label(label_row["id"], child)
                    report.renamed.append((label_row["label"], child))
                    log.info("Label renamed by hand: %s -> %s", label_row["label"], child)
                    cat.log_event("label-rename", f"{label_row['label']} -> {child}")
                    label_row = cat.label(new_id)
                    seen_ids.add(new_id)

            real = _real_files(folder)
            if not real:
                continue
            label_id = label_row["id"] if label_row else cat.get_or_create_label(group, child)
            seen_ids.add(label_id)
            for path in real:
                _adopt_file(drive, cat, ops, path, group, cat.label(label_id)["label"], label_id, report)
    cat.commit()
    return report


def _adopt_file(drive, cat, ops, path, group, label_name, label_id, report) -> None:
    from .importer import SourceFile

    try:
        sha = sha256_file(path)
    except OSError as e:
        log.warning("Can't read %s: %s", path, e)
        return
    row = cat.photo_by_hash(sha)
    if row is None:
        hint = dates.folder_name_hint(label_name)
        ctx = FolderContext(labels=[Label(group, label_name)], hint=hint)
        report.to_import.append(SourceFile(path, [], ctx, drive.rel(path)))
        return
    try:
        if row["status"] == "missing" or not os.path.exists(drive.abs(row["rel_path"])):
            # She moved it out of By Date into the view: put it back where it was.
            want = drive.abs(row["rel_path"])
            folder, base = os.path.split(want)
            stem, ext = os.path.splitext(base)
            dst = os.path.join(folder, free_name(ops, folder, stem, [ext]) + ext)
            ops.move(path, dst)
            st = None if ops.dry_run else os.stat(dst)
            cat.update_photo(row["id"], rel_path=drive.rel(dst), status="ok",
                             size=st.st_size if st else row["size"], mtime=st.st_mtime if st else row["mtime"])
            cat.record_move(drive.rel(path), drive.rel(dst), "label-request")
            report.restored.append(drive.rel(dst))
        else:
            # A copy of a photo that's already safe in My Photos.
            stem, ext = os.path.splitext(os.path.basename(path))
            dst = os.path.join(drive.duplicates, free_name(ops, drive.duplicates, stem, [ext]) + ext)
            ops.move(path, dst)
            cat.record_move(drive.rel(path), drive.rel(dst), "view-copy")
        cat.add_label(row["id"], label_id)
        report.labeled.append(label_name)
        cat.commit()
    except Exception:
        log.exception("Couldn't adopt %s from a view folder; leaving it", path)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@dataclass
class SyncReport:
    created: int = 0
    removed: int = 0


def plan_views(cat: Catalog) -> list[ViewFolder]:
    folders: list[ViewFolder] = []
    for fn in VIEWS:
        folders.extend(fn(cat))
    return folders


def _link_names(drive: Drive, vf: ViewFolder) -> dict[str, str]:
    """{link name: absolute target}, date-first names, collisions get _2, _3."""
    out: dict[str, str] = {}
    lowered: set[str] = set()
    for row in sorted(vf.photos, key=lambda r: (r["taken_at"] or "9999", r["id"])):
        target = drive.abs(row["rel_path"])
        base = os.path.basename(target)
        stem, ext = os.path.splitext(base)
        name, n = base, 1
        while name.lower() in lowered:
            n += 1
            name = f"{stem}_{n}{ext}"
        out[name] = target
        lowered.add(name.lower())
    return out


def sync_views(drive: Drive, cat: Catalog, ops: FileOps) -> SyncReport:
    report = SyncReport()
    wanted: dict[str, ViewFolder] = {}
    for vf in plan_views(cat):
        wanted[os.path.join(drive.library, *vf.parts)] = vf

    for folder, vf in wanted.items():
        ops.makedirs(folder)
        if vf.label_id is not None and _read_label_id(folder) != vf.label_id:
            id_file = os.path.join(folder, names.LABEL_ID_FILE)
            if os.path.lexists(id_file) and not ops.dry_run:
                os.remove(id_file)
            ops.write_text(id_file, f"{vf.label_id}\n")
        links = _link_names(drive, vf)
        for name, target in links.items():
            link = os.path.join(folder, name)
            rel_target = os.path.relpath(target, folder)
            if os.path.islink(link):
                if os.readlink(link) == rel_target:
                    continue
                ops.remove_symlink(link)
                report.removed += 1
            elif os.path.lexists(link):
                # A real file is sitting here: never touch it, use another name.
                stem, ext = os.path.splitext(name)
                link = os.path.join(folder, free_name(ops, folder, stem, [ext]) + ext)
            ops.symlink(rel_target, link)
            report.created += 1
        # Stale links at the top of this folder; broken links anywhere in it.
        wanted_names = set(links)
        for dirpath, dirnames, filenames in os.walk(folder):
            top_level = os.path.normcase(os.path.abspath(dirpath)) == os.path.normcase(os.path.abspath(folder))
            for fn in filenames + dirnames:
                p = os.path.join(dirpath, fn)
                if not os.path.islink(p) or (top_level and fn in wanted_names):
                    continue
                if top_level or not os.path.exists(p):
                    ops.remove_symlink(p)
                    report.removed += 1
        _remove_empty_subdirs(folder, ops)

    # Label folders nobody wants any more, then empty view roots.
    for root in view_roots(drive):
        root_abs = os.path.join(drive.library, root)
        for child in os.listdir(root_abs):
            folder = os.path.join(root_abs, child)
            if folder in wanted or os.path.islink(folder) or not os.path.isdir(folder):
                continue
            for dirpath, dirnames, filenames in os.walk(folder):
                for fn in filenames + dirnames:
                    p = os.path.join(dirpath, fn)
                    if os.path.islink(p):
                        ops.remove_symlink(p)
                        report.removed += 1
            _remove_empty_subdirs(folder, ops)
            leftovers = [e for e in os.listdir(folder) if not os.path.islink(os.path.join(folder, e))]
            if leftovers == [names.LABEL_ID_FILE]:
                ops.remove_app_file(os.path.join(folder, names.LABEL_ID_FILE))
            ops.rmdir_if_empty(folder)
        ops.rmdir_if_empty(root_abs)
    return report


def _remove_empty_subdirs(folder: str, ops: FileOps) -> None:
    for dirpath, dirnames, filenames in os.walk(folder, topdown=False):
        if os.path.normcase(os.path.abspath(dirpath)) == os.path.normcase(os.path.abspath(folder)):
            continue
        if not os.path.islink(dirpath):
            ops.rmdir_if_empty(dirpath)
