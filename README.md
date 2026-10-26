# Organize photos

A photo organizer that lives on an external drive. Drop photos into **Put new photos here**, double-click **Organize photos**, and they get sorted into **My photos**. See [CLAUDE.md](CLAUDE.md) for the full design and [TEST_DRIVE.md](TEST_DRIVE.md) for the end-to-end test drive.

```
My photos/
├── By date/2024/2024-07-14_15-30-22.jpg   ← real files, one folder per year
├── By date/2009/2009-06 scan_101.jpg      ← dated to the month by a DATE folder
├── By date/1990s/1990s p_1.jpg            ← dated to the decade
├── By event/Christmas 2025/…              ← links into By date
├── Unsorted/Probably 2008/<folder>/…      ← no trustworthy date; best guess
├── Unsorted/Date unknown/<folder>/…
├── Unsorted/Not photos/…
└── Duplicates (safe to delete)/
```

## Develop (Windows is fine)

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Run against any folder pretending to be the drive:

```bash
python -m photo_organizer --drive <folder> [--dry-run] [--verbose] [--timezone America/Los_Angeles]
```

`--dry-run` prints every move, link, and folder it would make, and changes nothing. `--timezone` sets the zone used to convert UTC video timestamps (default: the computer's own zone).

### Test drive

```bash
python -m photo_organizer.testdrive full test-drives/full          # everything, both phases
python -m photo_organizer.testdrive full test-drives/big --big 5000  # plus a 5,000-photo import

# or step by step:
python -m photo_organizer.testdrive make test-drives/one --reset
python -m photo_organizer --drive test-drives/one --timezone America/Los_Angeles
python -m photo_organizer.testdrive check test-drives/one
python -m photo_organizer.testdrive edit test-drives/one
python -m photo_organizer --drive test-drives/one --timezone America/Los_Angeles
python -m photo_organizer.testdrive check test-drives/one --phase after-edit
```

`test-drives/` is git-ignored, so real photos dropped into a test inbox never get committed. `make --reset` refuses to wipe any folder that has no `expected.json`.

### Things that skip on this Windows PC (and run in CI)

- **By event** folders are made of links (symlinks), which Windows only allows with Developer Mode on, so those tests skip locally. They run on the macOS and Windows CI runners.
- **The `DATE - 7:4:2009` scenario** needs a Mac, because Windows doesn't allow `:` in folder names.
- **Python 3.12:** Windows Smart App Control blocked the Python builds downloaded by `uv`, so local development uses the installed Python 3.14. CI uses Python 3.12, and the code avoids anything newer than 3.12.

## Layout of the code

| Module | Job |
|---|---|
| `names.py` | Every folder name and message Mom sees |
| `dates.py` | Date parsing, sanity checks, scanner list, naming |
| `labels.py` | `EVENT -` / `DATE -` folder names |
| `metadata.py` | EXIF + GPS via Pillow, a small MP4/MOV atom reader for video dates |
| `importer.py` | Inbox → dedupe → Live Photos, edits, `.AAE` sidecars → date → move → catalog |
| `guess.py` | "Probably 2008" guesses for Unsorted |
| `reconcile.py` | Follows Mom's moves, renames, deletes, and copies |
| `views.py` | Registered view functions + symlink sync (add a view = one function) |
| `catalog.py` | SQLite schema, backups |
| `fileops.py` | All file changes (never overwrite; dry-run version) |
| `system.py` | Lock, finding the drive, macOS dialogs |
| `run.py` | One run, wrapped so errors become a friendly dialog |
| `testdrive/` | Fake-drive generator and checker |

## Build and release (GitHub Actions)

`.github/workflows/ci.yml`:

- **Every push and PR:** tests on macOS and Windows, plus the full test drive (both phases, second-run checks, a 500-photo import).
- **On `main`, `v*` tags, and manual runs:** builds `Organize photos.app` on Apple Silicon with PyInstaller (`--onedir`, windowed, from `packaging/organize_photos.spec`). It checks the binary is arm64, verifies the ad-hoc signature with `codesign --verify --deep --strict`, runs the full test drive with the built app, zips it with `ditto -c -k --keepParent`, and uploads the zip as a workflow artifact.
- **On a `v*` tag:** also attaches the zip to a GitHub Release.

To release: bump `__version__` in `photo_organizer/__init__.py`, then `git tag v0.1.0 && git push --tags`.

## What to expect on the Mac

- **First launch is blocked** because the app is unsigned and downloaded. Fix it once with either System Settings → Privacy & Security → **Open Anyway**, or in Terminal: `xattr -dr com.apple.quarantine "Organize photos.app"`. Clearing quarantine also stops App Translocation, which runs downloaded apps from a random hidden path.
- **First run:** macOS asks to let the app access files on a removable volume. Click **Allow**. Each new build may ask again, because an ad-hoc signature changes with every build.
- **The app finds the drive** next to itself, or, if it's in the Dock, in Applications, or translocated, by looking for `.photo-organizer/drive-marker` on every mounted volume.
- **Dialogs** use `osascript`. The message is passed as an argument instead of pasted into the AppleScript, so quotes in folder names can't break it.
- **The drive must be APFS.** On exFAT, links can't be made, so the app still sorts by date, skips the link folders, and logs a warning.
- **Deleted links or label folders come back** on the next run (v1 behavior). The photos are safe in By date either way. To really remove a photo, delete it from By date.
- **Dragging a real photo into a view folder** (e.g. `By event/Hawaii 2026`) labels it. If it came from By date, it's moved back there. A copy of a photo that's already in My photos goes to Duplicates. A new photo is imported normally.

## Logs and recovery

- `.photo-organizer/logs/run-*.log` holds one log per run (the last 30). `error-*.txt` holds tracebacks.
- `.photo-organizer/catalog-backups/` holds the last 10 copies of the catalog.
- The `moves` table in `catalog.db` records every move (`src → dst`), for a future undo tool.
