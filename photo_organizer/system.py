"""The small OS-specific parts: lock file, finding the drive, and dialogs.

Everything here sits behind tiny interfaces so tests can use fakes.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import sys
import time

from . import names

log = logging.getLogger(__name__)

STALE_LOCK_SECONDS = 60 * 60


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

class AlreadyRunning(Exception):
    pass


class RunLock:
    def __init__(self, path: str, now=time.time) -> None:
        self.path = path
        self._now = now
        self.held = False

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = self._now() - os.path.getmtime(self.path)
                except OSError:
                    continue
                if age < STALE_LOCK_SECONDS:
                    raise AlreadyRunning()
                log.warning("Removing stale lock (%.0f minutes old)", age / 60)
                try:
                    os.remove(self.path)
                except OSError:
                    pass
                continue
            with os.fdopen(fd, "w") as f:
                json.dump({"pid": os.getpid(), "started": self._now()}, f)
            self.held = True
            return
        raise AlreadyRunning()

    def release(self) -> None:
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.held = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


# ---------------------------------------------------------------------------
# Finding the drive
# ---------------------------------------------------------------------------

def _has_marker(root: str) -> bool:
    return os.path.isfile(os.path.join(root, names.APP_DATA, names.DRIVE_MARKER))


def app_bundle_path(executable: str | None = None) -> str | None:
    """'/Volumes/X/Organize photos.app' from the running executable, if inside a .app."""
    exe = os.path.abspath(executable or sys.executable)
    parts = exe.split(os.sep)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].endswith(".app"):
            return os.sep.join(parts[: i + 1])
    return None


def find_drive(executable: str | None = None, volumes_dir: str = "/Volumes") -> str | None:
    """Find the photo drive.

    1. Next to the app bundle (normal case: the app lives at the drive root).
       Accepted if that folder has our marker, or is itself a mounted volume
       (first run, before the marker exists).
    2. Otherwise (app in the Dock/Applications, or App Translocation moved it
       to a random path) look for the marker on every mounted volume.
    """
    bundle = app_bundle_path(executable)
    if bundle and "/AppTranslocation/" not in bundle:
        parent = os.path.dirname(bundle)
        if _has_marker(parent):
            return parent
        if os.path.dirname(parent) == volumes_dir:
            return parent
    for marker in sorted(glob.glob(os.path.join(volumes_dir, "*", names.APP_DATA, names.DRIVE_MARKER))):
        return os.path.dirname(os.path.dirname(marker))
    return None


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class ConsoleUI:
    """Used on Windows/Linux and for the CLI."""

    def __init__(self, stream=None) -> None:
        self.stream = stream

    def _print(self, text: str) -> None:
        stream = self.stream or sys.stdout
        enc = getattr(stream, "encoding", None) or "utf-8"
        # Windows consoles can't show every character (e.g. ▸); never crash over it.
        stream.write(text.encode(enc, "replace").decode(enc) + "\n")
        stream.flush()

    def info(self, message: str) -> None:
        self._print(f"\n[{names.APP_NAME}] {message}\n")

    def error(self, message: str) -> None:
        self._print(f"\n[{names.APP_NAME}] {message}\n")

    def notify(self, message: str) -> None:
        self._print(f"[{names.APP_NAME}] {message}")


class MacUI:
    """Native dialogs via osascript. The message is passed as an argument
    (not pasted into the script), so quotes and backslashes need no escaping."""

    @staticmethod
    def _dialog(icon: str) -> list[str]:
        return [
            "on run argv",
            "activate",
            'display dialog (item 1 of argv) with title (item 2 of argv) buttons {"OK"} '
            f'default button "OK" with icon {icon}',
            "end run",
        ]

    _NOTIFY = [
        "on run argv",
        "display notification (item 1 of argv) with title (item 2 of argv)",
        "end run",
    ]

    def _osascript(self, lines: list[str], *args: str) -> None:
        cmd = ["osascript"]
        for line in lines:
            cmd += ["-e", line]
        try:
            subprocess.run([*cmd, *args], check=False, capture_output=True)
        except Exception:
            log.exception("osascript failed")

    def info(self, message: str) -> None:
        self._osascript(self._dialog("note"), message, names.APP_NAME)

    def error(self, message: str) -> None:
        self._osascript(self._dialog("caution"), message, names.APP_NAME)

    def notify(self, message: str) -> None:
        self._osascript(self._NOTIFY, message, names.APP_NAME)


def default_ui():
    return MacUI() if sys.platform == "darwin" else ConsoleUI()
