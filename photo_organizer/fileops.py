"""All changes to the drive go through here, so --dry-run can't touch anything.

Rules: never overwrite, never delete a real file (the only deletions are
empty folders, symlinks, and macOS junk files in emptied inbox folders).
"""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil

log = logging.getLogger(__name__)

CHUNK = 1 << 20


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class FileExistsAtDestination(Exception):
    pass


class FileOps:
    """Real operations."""

    dry_run = False

    def __init__(self, root: str | None = None) -> None:
        self.actions: list[str] = []
        self.root = root

    def _show(self, path: str) -> str:
        if self.root:
            try:
                return os.path.relpath(path, self.root).replace(os.sep, "/")
            except ValueError:
                pass
        return path

    def _note(self, text: str) -> None:
        self.actions.append(text)
        log.debug(text)

    # ---- queries (dry-run overrides these to see planned changes) ----
    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    # ---- changes ----
    def makedirs(self, path: str) -> None:
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            self._note(f"mkdir {self._show(path)}")

    def move(self, src: str, dst: str) -> None:
        """Move a file without ever overwriting. Raises on failure; src is untouched then."""
        if self.exists(dst):
            raise FileExistsAtDestination(dst)
        self.makedirs(os.path.dirname(dst))
        try:
            os.rename(src, dst)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            self._copy_verify_delete(src, dst)
        self._note(f"move {self._show(src)} -> {self._show(dst)}")

    def _copy_verify_delete(self, src: str, dst: str) -> None:
        src_hash = sha256_file(src)
        tmp = dst + ".partial"
        try:
            with open(src, "rb") as fi, open(tmp, "xb") as fo:
                shutil.copyfileobj(fi, fo, CHUNK)
                fo.flush()
                os.fsync(fo.fileno())
            shutil.copystat(src, tmp)
            if sha256_file(tmp) != src_hash:
                raise OSError(f"copy of {src} didn't verify")
            if self.exists(dst):
                raise FileExistsAtDestination(dst)
            os.rename(tmp, dst)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        os.remove(src)

    def symlink(self, target: str, link: str) -> None:
        if self.exists(link):
            raise FileExistsAtDestination(link)
        os.symlink(target, link)
        self._note(f"link {self._show(link)} -> {target}")

    def remove_symlink(self, path: str) -> None:
        if not os.path.islink(path):
            raise ValueError(f"refusing to remove non-symlink {path}")
        os.unlink(path)
        self._note(f"unlink {self._show(path)}")

    def rmdir_if_empty(self, path: str) -> bool:
        try:
            os.rmdir(path)
        except OSError:
            return False
        self._note(f"rmdir {self._show(path)}")
        return True

    def remove_junk(self, path: str) -> None:
        """Delete a .DS_Store / ._* file (Finder metadata, never a photo)."""
        base = os.path.basename(path)
        if not (base == ".DS_Store" or base.startswith("._")):
            raise ValueError(f"refusing to remove {path}")
        os.remove(path)
        self._note(f"remove junk {self._show(path)}")

    def remove_app_file(self, path: str) -> None:
        """Delete one of our own hidden marker files (e.g. .label-id)."""
        os.remove(path)
        self._note(f"remove {self._show(path)}")

    def write_text(self, path: str, text: str) -> None:
        self.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self._note(f"write {self._show(path)}")


class DryRunOps(FileOps):
    """Records what would happen and tracks planned paths so collisions still resolve."""

    dry_run = True

    def __init__(self, root: str | None = None) -> None:
        super().__init__(root)
        self._added: set[str] = set()
        self._removed: set[str] = set()

    def _norm(self, p: str) -> str:
        return os.path.normcase(os.path.abspath(p))

    def exists(self, path: str) -> bool:
        n = self._norm(path)
        if n in self._added:
            return True
        if n in self._removed:
            return False
        return os.path.lexists(path)

    def makedirs(self, path: str) -> None:
        if not self.exists(path):
            self._added.add(self._norm(path))
            self._note(f"[dry-run] mkdir {self._show(path)}")

    def move(self, src: str, dst: str) -> None:
        if self.exists(dst):
            raise FileExistsAtDestination(dst)
        self._added.add(self._norm(dst))
        self._removed.add(self._norm(src))
        self._note(f"[dry-run] move {self._show(src)} -> {self._show(dst)}")

    def symlink(self, target: str, link: str) -> None:
        if self.exists(link):
            raise FileExistsAtDestination(link)
        self._added.add(self._norm(link))
        self._note(f"[dry-run] link {self._show(link)} -> {target}")

    def remove_symlink(self, path: str) -> None:
        self._removed.add(self._norm(path))
        self._note(f"[dry-run] unlink {self._show(path)}")

    def rmdir_if_empty(self, path: str) -> bool:
        self._note(f"[dry-run] rmdir {self._show(path)} (if empty)")
        return False

    def remove_junk(self, path: str) -> None:
        self._note(f"[dry-run] remove junk {self._show(path)}")

    def remove_app_file(self, path: str) -> None:
        self._note(f"[dry-run] remove {self._show(path)}")

    def write_text(self, path: str, text: str) -> None:
        self._added.add(self._norm(path))
        self._note(f"[dry-run] write {self._show(path)}")


def free_name(ops: FileOps, folder: str, stem: str, exts: list[str]) -> str:
    """Pick a stem so that folder/stem+ext is free for every ext (_2, _3, ...)."""
    candidate = stem
    n = 1
    while any(ops.exists(os.path.join(folder, candidate + e)) for e in exts):
        n += 1
        candidate = f"{stem}_{n}"
    return candidate


def symlinks_supported(test_dir: str) -> bool:
    target = os.path.join(test_dir, ".symlink-test-target")
    link = os.path.join(test_dir, ".symlink-test-link")
    try:
        os.makedirs(test_dir, exist_ok=True)
        with open(target, "w") as f:
            f.write("x")
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(os.path.basename(target), link)
        ok = os.path.islink(link)
    except (OSError, NotImplementedError):
        ok = False
    finally:
        for p in (link, target):
            try:
                if os.path.lexists(p):
                    os.unlink(p)
            except OSError:
                pass
    return ok
