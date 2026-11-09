"""python -m photo_organizer.testdrive make|check|edit|snapshot|full ..."""

from __future__ import annotations

import argparse
import os
import sys

from .check import FAIL, check, print_results
from .edit import EditError, edit
from .make import NotATestDrive, make
from .snapshot import diff, snapshot


def annotate(message: str) -> None:
    """On GitHub Actions, also show a problem as a public annotation on the run."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=test drive::{message.replace(chr(10), ' | ')[:900]}")


def annotate_failures(results) -> None:
    for r in results:
        if r.status == FAIL:
            annotate(f"{r.id}: {r.detail} {' '.join(r.more)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="photo_organizer.testdrive", description="Fake photo drive for testing.")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="create a test drive")
    m.add_argument("folder")
    m.add_argument("--reset", action="store_true", help="wipe an existing test drive first")
    m.add_argument("--big", type=int, default=0, metavar="N", help="also add N plain phone photos")

    c = sub.add_parser("check", help="compare a test drive with expected.json")
    c.add_argument("folder")
    c.add_argument("--phase", default="first-run", choices=["first-run", "after-edit"])
    c.add_argument("--feature")

    e = sub.add_parser("edit", help="rearrange things like Mom would, and add a second small batch")
    e.add_argument("folder")

    s = sub.add_parser("snapshot", help="print every path + hash")
    s.add_argument("folder")
    s.add_argument("--save", metavar="FILE", help="write the snapshot to FILE")
    s.add_argument("--compare", metavar="FILE", help="compare with a saved snapshot; exit 1 if different")

    f = sub.add_parser("full", help="make, run, check, edit, run, check, with second-run checks")
    f.add_argument("folder")
    f.add_argument("--app", help="path to a built organizer binary (default: this Python package)")
    f.add_argument("--big", type=int, default=0, metavar="N")

    args = p.parse_args(argv)
    if args.cmd == "make":
        try:
            manifest = make(args.folder, reset=args.reset, big=args.big)
        except NotATestDrive as err:
            print(err, file=sys.stderr)
            return 2
        print(f"Made {len(manifest['files'])} files in {args.folder}")
        for sk in manifest["skipped"]:
            print(f"  skipped {sk['id']}: {sk['reason']}")
        print(f"Next:  {manifest['run_command']}")
        print(f"Then:  python -m photo_organizer.testdrive check \"{args.folder}\"")
        return 0

    if args.cmd == "check":
        results = check(args.folder, args.phase, args.feature)
        print_results(args.folder, args.phase, results)
        annotate_failures(results)
        return 1 if any(r.status == FAIL for r in results) else 0

    if args.cmd == "edit":
        try:
            manifest = edit(args.folder)
        except EditError as err:
            print(err, file=sys.stderr)
            return 2
        for line in manifest["edits"]:
            print(f"  {line}")
        for sk in manifest["skipped"]:
            if sk.get("phase") == "after-edit":
                print(f"  skipped: {sk['reason']}")
        print(f"Next: run the organizer, then: python -m photo_organizer.testdrive check \"{args.folder}\" "
              "--phase after-edit")
        return 0

    if args.cmd == "snapshot":
        lines = snapshot(args.folder)
        if args.compare:
            with open(args.compare, encoding="utf-8") as fh:
                before = fh.read().splitlines()
            changes = diff(before, lines)
            for line in changes:
                print(line)
            print("No changes." if not changes else f"{len(changes)} change(s).")
            return 1 if changes else 0
        if args.save:
            with open(args.save, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            print(f"Saved {len(lines)} paths to {args.save}")
        else:
            print("\n".join(lines))
        return 0

    if args.cmd == "full":
        from .flow import any_failed, full, subprocess_organizer
        try:
            results = full(args.folder, subprocess_organizer(args.app), big=args.big)
        except (NotATestDrive, EditError) as err:
            print(err, file=sys.stderr)
            annotate(f"stopped: {err}")
            # Show what the first run did, to explain why the edit step stopped.
            try:
                first = check(args.folder, "first-run")
                print_results(args.folder, "first-run", first)
                annotate_failures(first)
            except Exception:
                pass
            return 2
        except Exception as err:
            annotate(f"crashed: {type(err).__name__}: {err}")
            raise
        for phase, rs in results.items():
            print()
            print_results(args.folder, phase, rs)
            annotate_failures(rs)
        failed = any_failed(results)
        print("\nRESULT: " + ("FAILED" if failed else "all good"))
        return 1 if failed else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
