"""python -m photo_organizer.testdrive make|check ..."""

from __future__ import annotations

import argparse
import sys

from .check import FAIL, check, print_results
from .make import NotATestDrive, make


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="photo_organizer.testdrive", description="Fake photo drive for testing.")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="create a test drive")
    m.add_argument("folder")
    m.add_argument("--reset", action="store_true", help="wipe an existing test drive first")

    c = sub.add_parser("check", help="compare a test drive with expected.json")
    c.add_argument("folder")
    c.add_argument("--phase", default="first-run", choices=["first-run", "after-edit"])
    c.add_argument("--feature")

    args = p.parse_args(argv)
    if args.cmd == "make":
        try:
            manifest = make(args.folder, reset=args.reset)
        except NotATestDrive as e:
            print(e, file=sys.stderr)
            return 2
        print(f"Made {len(manifest['files'])} files in {args.folder}"
              + (f" ({len(manifest['skipped'])} skipped: {manifest['skipped'][0]['reason']})"
                 if manifest["skipped"] else ""))
        print(f"Next:  {manifest['run_command']}")
        print(f"Then:  python -m photo_organizer.testdrive check \"{args.folder}\"")
        return 0
    if args.cmd == "check":
        results = check(args.folder, args.phase, args.feature)
        print_results(args.folder, args.phase, results)
        return 1 if any(r.status == FAIL for r in results) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
