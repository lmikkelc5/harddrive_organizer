"""Start Organize photos: update the sorting code if possible, then run it.

Order of preference:
1. The newest downloaded release that is newer than the code built into the
   app and hasn't failed before.
2. The code built into the app (always there, always the fallback).

If downloaded code fails to even start (import error), it's marked bad and
the built-in code runs instead, so one bad release can't lock Mom out.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import logging
import os
import sys

from . import updater

log = logging.getLogger("app_shell")
ENV_CODE = "ORGANIZE_PHOTOS_CODE"   # tells the run log which code ran


class _UpdatedCodeFinder(importlib.abc.MetaPathFinder):
    """Load photo_organizer from a downloaded folder instead of the frozen copy.

    Installed first in sys.meta_path, so it wins over PyInstaller's importer
    for photo_organizer only; every other module (Pillow, stdlib) still comes
    from the app.
    """

    def __init__(self, root: str) -> None:
        self.root = root

    def find_spec(self, fullname, path=None, target=None):
        if fullname == updater.PACKAGE:
            return importlib.machinery.PathFinder.find_spec(fullname, [self.root])
        if fullname.startswith(updater.PACKAGE + "."):
            return importlib.machinery.PathFinder.find_spec(fullname, path)
        return None


def _forget_package() -> None:
    for name in list(sys.modules):
        if name == updater.PACKAGE or name.startswith(updater.PACKAGE + "."):
            del sys.modules[name]


def _setup_logging(home: str) -> None:
    try:
        os.makedirs(home, exist_ok=True)
        path = os.path.join(home, "updates.log")
        if os.path.exists(path) and os.path.getsize(path) > 200_000:
            os.replace(path, path + ".old")
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    except OSError:
        pass


def bundled_version() -> tuple[int, ...]:
    import photo_organizer  # the frozen copy; only reads __version__

    v = updater.parse_version(photo_organizer.__version__) or (0, 0, 0)
    _forget_package()
    return v


def load_main(home: str | None = None, check=True, fetch=None):
    """Return (main function, version text, source). Never raises for update problems."""
    home = home or updater.home_dir()
    # Start clean, in case code was already loaded in this process.
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _UpdatedCodeFinder)]
    _forget_package()
    try:
        bundled = bundled_version()
        if check and not os.environ.get(updater.ENV_DISABLE):
            kwargs = {"fetch": fetch} if fetch else {}
            updater.check_for_update(bundled, home, **kwargs)
        options = updater.candidates(bundled, home)
    except Exception as e:
        log.warning("Update step failed, using built-in code: %s", e)
        options = []

    # Newest downloaded code first; if it won't start, try the next one.
    for version, folder in options:
        finder = _UpdatedCodeFinder(folder)
        sys.meta_path.insert(0, finder)
        try:
            pkg = importlib.import_module(updater.PACKAGE)
            if updater.parse_version(pkg.__version__) != version:
                raise ImportError(f"folder {folder} holds version {pkg.__version__}")
            main = importlib.import_module(updater.PACKAGE + ".__main__").main
            text = ".".join(map(str, version))
            log.info("Running downloaded code %s", text)
            return main, text, "update"
        except Exception:
            log.exception("Downloaded code %s failed to start; trying the next option", version)
            updater.mark_bad(version, home)
            sys.meta_path.remove(finder)
            _forget_package()

    pkg = importlib.import_module(updater.PACKAGE)
    main = importlib.import_module(updater.PACKAGE + ".__main__").main
    log.info("Running built-in code %s", pkg.__version__)
    return main, pkg.__version__, "built-in"


def main() -> int:
    home = updater.home_dir()
    _setup_logging(home)
    run_main, version, source = load_main(home)
    os.environ[ENV_CODE] = f"{version} ({source})"
    return run_main()


if __name__ == "__main__":
    sys.exit(main())
