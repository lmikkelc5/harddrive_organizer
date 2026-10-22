"""Entry point.

Development:  python -m photo_organizer --drive <folder> [--dry-run] [--verbose]
Mac app:      launched with no arguments; finds the drive and uses native dialogs.
"""

from __future__ import annotations

import argparse
import sys

from .run import run
from .system import ConsoleUI, default_ui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="photo_organizer", description="Sort photos on the photo drive.")
    parser.add_argument("--drive", help="folder to treat as the photo drive (default: find it)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without changing anything")
    parser.add_argument("--verbose", action="store_true", help="show detailed log output")
    parser.add_argument("--timezone", help="IANA zone for video UTC times, e.g. America/Los_Angeles "
                        "(default: this computer's zone)")
    parser.add_argument("--dialogs", action="store_true", help="use native dialogs even with --drive")
    # macOS may add arguments like -psn_0_12345 when launching an app; ignore them.
    args, _unknown = parser.parse_known_args(argv)
    ui = default_ui() if (args.dialogs or not args.drive) else ConsoleUI()
    return run(args.drive, ui, dry_run=args.dry_run, verbose=args.verbose,
               timezone=args.timezone)


if __name__ == "__main__":
    sys.exit(main())
