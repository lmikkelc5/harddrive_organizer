"""Paths on the drive, and helpers to convert between absolute and drive-relative."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from . import names


class Drive:
    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.inbox = self.path(names.INBOX)
        self.library = self.path(names.LIBRARY)
        self.by_date = os.path.join(self.library, names.BY_DATE)
        self.unsorted = os.path.join(self.library, names.UNSORTED)
        self.duplicates = os.path.join(self.library, names.DUPLICATES)
        self.app_data = self.path(names.APP_DATA)
        self.marker = os.path.join(self.app_data, names.DRIVE_MARKER)
        self.catalog = os.path.join(self.app_data, names.CATALOG)
        self.backups = os.path.join(self.app_data, names.CATALOG_BACKUPS)
        self.sidecars = os.path.join(self.app_data, names.SIDECARS)
        self.logs = os.path.join(self.app_data, names.LOGS)
        self.lock = os.path.join(self.app_data, names.LOCK)

    def path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def rel(self, abs_path: str) -> str:
        return os.path.relpath(abs_path, self.root).replace(os.sep, "/")

    def abs(self, rel_path: str) -> str:
        return os.path.join(self.root, *rel_path.split("/"))

    def lib_rel(self, abs_path: str) -> list[str]:
        """Path parts relative to My photos."""
        return os.path.relpath(abs_path, self.library).replace(os.sep, "/").split("/")

    def ensure_layout(self, ops) -> None:
        for p in (self.inbox, self.library, self.by_date, self.unsorted, self.duplicates,
                  self.app_data, self.backups, self.sidecars, self.logs):
            ops.makedirs(p)
        if not ops.exists(self.marker):
            ops.write_text(self.marker, f"{uuid.uuid4()}\ncreated {datetime.now().isoformat(timespec='seconds')}\n")
