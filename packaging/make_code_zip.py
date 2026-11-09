"""Build the code-only update for a release: photo_organizer-code.zip + .sha256.

The app's shell downloads these from the latest GitHub Release (see app_shell/).
Usage: python packaging/make_code_zip.py [--out DIR] [--version X.Y.Z]
(--version overrides __version__ inside the zip; only for tests/CI smoke tests.)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PACKAGE = "photo_organizer"
SKIP_DIRS = {"__pycache__", "testdrive"}


def read_meta() -> tuple[str, int]:
    with open(os.path.join(ROOT, PACKAGE, "__init__.py"), encoding="utf-8") as f:
        text = f.read()
    version = re.search(r'__version__ = "([^"]+)"', text).group(1)
    m = re.search(r"REQUIRES_SHELL = (\d+)", text)
    return version, int(m.group(1)) if m else 1


def build(out_dir: str, version: str | None = None, break_it: bool = False) -> str:
    real_version, requires_shell = read_meta()
    version = version or real_version
    os.makedirs(out_dir, exist_ok=True)
    zpath = os.path.join(out_dir, "photo_organizer-code.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("update.json", json.dumps({"version": version, "requires_shell": requires_shell}))
        pkg_root = os.path.join(ROOT, PACKAGE)
        for dirpath, dirnames, filenames in os.walk(pkg_root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                arc = os.path.relpath(path, ROOT).replace(os.sep, "/")
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                if arc == f"{PACKAGE}/__init__.py":
                    text = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', text)
                    if break_it:  # CI smoke test: code that can't start
                        text += "\nraise RuntimeError('deliberately broken update')\n"
                z.writestr(arc, text)
    with open(zpath, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(zpath + ".sha256", "w") as f:
        f.write(f"{digest}  photo_organizer-code.zip\n")
    return zpath


def write_local_release(out_dir: str, tag: str) -> str:
    """A latest.json shaped like GitHub's API, pointing at local files (for tests)."""
    def url(name: str) -> str:
        return "file:///" + os.path.abspath(os.path.join(out_dir, name)).replace(os.sep, "/").lstrip("/")
    data = {"tag_name": tag, "assets": [
        {"name": "photo_organizer-code.zip", "browser_download_url": url("photo_organizer-code.zip")},
        {"name": "photo_organizer-code.zip.sha256", "browser_download_url": url("photo_organizer-code.zip.sha256")},
    ]}
    path = os.path.join(out_dir, "latest.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(ROOT, "dist"))
    p.add_argument("--version")
    p.add_argument("--local-release", action="store_true", help="also write latest.json for a local test release")
    p.add_argument("--broken", action="store_true", help="make code that fails to start (CI smoke test)")
    args = p.parse_args()
    z = build(args.out, args.version, args.broken)
    print(z)
    if args.local_release:
        print(write_local_release(args.out, "v" + (args.version or read_meta()[0])))
    sys.exit(0)
