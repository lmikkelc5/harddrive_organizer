# Organize Photos — Project Brief

A photo organizer for my mom. It lives on an external drive. She drops photos (or labeled folders of photos) into an inbox folder, opens the app, and her photos get sorted. She is **not tech-savvy**, so everything she touches has to be obvious, forgiving, and impossible to lose photos with.

I (Mikkel, the developer) **do not have a Mac**. I develop on Windows, and the Mac app is built and tested by **GitHub Actions** on GitHub's macOS runners. Her Mac is a new **Apple Silicon** Mac on current macOS (arriving Christmas 2026).

> Note: Mac apps are `.app` bundles, not `.exe` files. "The exe" in conversation means the `.app`.

---

## Core principles (never break these)

1. **Never lose a photo.** Nothing is ever deleted except an empty inbox folder after every file in it was moved successfully. Never overwrite a file. On any error, leave the file where it was.
2. **Mom never sees a terminal, a traceback, or jargon.** Every outcome ends in a plain-English dialog.
3. **When unsure, put it somewhere obvious** (`Unsorted`, `Duplicates`) instead of guessing.
4. **By Date holds the real files. Every other folder is a view made of links** and can be rebuilt from the catalog at any time.
5. **Built to grow.** I'll add more views later (By Place, etc.). Adding a view should mean writing one function, not restructuring.
6. **Her manual edits win.** If she moves, renames, or deletes something in My Photos, the app updates its records to match and never moves it back.

---

## Drive layout

```
/Volumes/<Drive>/
├── Organize Photos.app
├── Put New Photos Here/            ← the only folder she drops into
├── My Photos/
│   ├── By Date/2026/               ← REAL files live here (year folders only)
│   ├── By Trip/Hawaii 2026/        ← relative symlinks into By Date
│   ├── By Event/Christmas 2026/    ← relative symlinks into By Date
│   ├── Albums/<label>/             ← labeled folders with no group word
│   ├── Unsorted/                   ← no trustworthy date; grouped by best guess
│   └── Duplicates (safe to delete)/
└── .photo-organizer/               ← hidden; app data
    ├── drive-marker                ← identifies this drive
    ├── catalog.db                  ← SQLite source of truth
    ├── catalog-backups/            ← last N copies of catalog.db
    ├── sidecars/                   ← .AAE files (see special cases)
    ├── logs/                       ← run logs + error reports
    └── lock
```

- Create any missing folders on first run.
- The drive **must be APFS** (exFAT doesn't support symlinks). On startup, test whether symlinks can be created; if not, still sort by date, skip views, and log a clear warning for me.
- Keep every user-facing name (folder names, messages) in one module so they're easy to change.

---

## What a run does

1. **Find the drive.** First look relative to the app bundle's location. If that fails (the app was moved to the Dock or Applications, or macOS App Translocation put it in a random path containing `/AppTranslocation/`), scan `/Volumes/*` for `.photo-organizer/drive-marker`. If no drive is found, show the "plug in your drive" message.
2. **Take the lock.** If another run is active, show the "already working" message and exit. Treat a lock older than 1 hour as stale.
3. **Back up the catalog** (keep the last 10).
4. **Reconcile** the catalog with what's actually on the drive. Mom is allowed to move, rename, and delete things herself, and the catalog follows her (see **Manual edits** below).
5. **Scan the inbox** recursively. Skip hidden files, `.DS_Store`, `._*` AppleDouble files, and anything modified in the last ~15 seconds (it may still be copying; it gets picked up next run).
6. **For each item:** read metadata, compute SHA-256, check for duplicates, choose a destination, move it, and record it in the catalog.
7. **Apply labels** from labeled folders (see below).
8. **Sync views** from the catalog.
9. **Remove inbox subfolders that are now empty.**
10. **Show the summary dialog.**

### Moving files
The inbox and My Photos are on the same volume, so use `os.rename`, which is atomic and needs no copy. If that ever raises a cross-device error, fall back to copy → fsync → verify hash → then delete the source.

### Duplicates
Exact duplicates are matched by SHA-256, against the catalog and within the same batch. Move them to `Duplicates (safe to delete)/`. Never delete them automatically.

---

## Dates

Mom has a lot of old photos with missing or wrong dates: scanned prints, old cameras with reset clocks, photos saved from messages. The goals are:
- Date as many photos as possible automatically.
- **Never file a photo under a confidently wrong date.**
- Make the leftovers quick to fix by hand.

### Mom can set the date herself (`DATE -` folders)
If she knows when photos were taken, she names the folder with the reserved word `DATE`, the same way she names trip folders. Accepted formats:

| Precision | Examples |
|---|---|
| Year | `DATE - 2009` |
| Month | `DATE - June 2009`, `DATE - Jun 2009`, `DATE - 2009-06`, `DATE - 6/2009` |
| Day | `DATE - July 4 2009`, `DATE - 7/4/2009`, `DATE - 2009-07-04` |
| Decade | `DATE - 1990s`, `DATE - 90s` |

- **Parsing rules:** numeric dates use US month/day order. Two-digit decades map to the most recent decade that isn't in the future (`90s` → 1990s, `20s` → 2020s).
- **An explicit date beats every other source,** including good-looking metadata. It's her direct statement, and it's the main way to fix a camera with a wrong clock in bulk. Keep the metadata date in `raw_meta_date` and log big disagreements.
- **Plain folder names with a year** (`Christmas 2009`) are still only a fallback hint (below). Only `DATE -` overrides.
- **Nesting works.** `TRIP - Hawaii/DATE - June 2009/...` gets both the label and the date. Labels and dates inherit down the folder tree, and the deepest `DATE -` folder wins.
- **Where photos go:** `By Date/2009/` (day, month, or year), or `By Date/1990s/` (decade). The precision lives in the file name prefix and the catalog.
- **If the date can't be understood** (`DATE - a long time ago`), don't guess. Put the folder's photos in Unsorted, keeping the folder, and say so in the summary: "I couldn't read the date in "DATE - a long time ago", so those photos are in Unsorted."

### Automatic dating
For everything without a `DATE -` folder, try sources in this order and record which one was used (`date_source`) in the catalog. Dates from sources 1–3 must also pass the **sanity checks** below:

1. **Photos:** EXIF `DateTimeOriginal`, using `OffsetTimeOriginal` when present. Then `DateTimeDigitized`. Then IFD0 `DateTime`, which is sometimes the edit time, so it comes last.
2. **Videos:** iPhone videos store a local-time creation date in `com.apple.quicktime.creationdate`; prefer it. The generic `creation_time` is usually **UTC** and must be converted to local time.
3. **Filename patterns**, e.g. `IMG_20260714_153022`, `PXL_20260714_...`, `20260714_153022`, `Screenshot 2026-07-14 at 3.30.22 PM`, `WhatsApp Image 2026-07-14 at ...`.
4. **Folder-name hints** (see below).
5. **Otherwise → `Unsorted/`**, grouped by best guess (see below). Never use the file's modified time to sort into By Date. It's usually the copy or export time, and it would silently file photos under the wrong date.

### Sanity checks (a wrong date is worse than no date)
A date from metadata or a filename is **rejected** (treated as no date) if:
- **It's in the future**, or implausibly early for a digital file (before ~1990).
- **It's a camera reset default.** Examples: 1970-01-01, 1980-01-01, 2000-01-01, or a Jan 1 timestamp in the first hour of the year that repeats across several photos from the same camera model in one batch. A single real New Year's photo shouldn't be rejected.
- **It's a scan date.** EXIF Make/Model/Software identifies a scanner or scanning app (Epson, FastFoto, scanner models from Canon and others, VueScan, Google PhotoScan, etc.). Keep this list small, editable, and in one place.

Don't throw rejected dates away. Store them in the catalog (`raw_meta_date`, `reject_reason`) for reference.

If a trustworthy metadata date and a folder-name year disagree by more than a year, the metadata date wins. Log the conflict in the catalog.

### Folder-name hints (likely the biggest win for old photos)
Old photos usually live in folders like `Old Laptop/2004/Disneyland` or `Christmas 2009`.
- **Use the folder path's year as a fallback.** For files without a trustworthy date, look for a year (1900 to the current year) in the inbox folder path, using the deepest folder that has one. Pick up a month too when present (`June 2009`, `2009-06`, `06-2009`). Only count standalone 4-digit numbers.
- **Sort into By Date:** `By Date/2009/`, with the month (if any) in the name prefix (`2009-06 IMG_0001.jpg`). Record `date_source = folder-name`.
- **Combine with labels.** `TRIP - Hawaii 2026` labels the photos *and* gives undated ones a 2026 fallback.

### Unsorted: make the leftovers quick to fix
- **Keep the original folder structure** inside Unsorted so context isn't lost. For example, `Unsorted/Date Unknown/Grandma's 80th/...` instead of one flat pile of `IMG_0001.jpg`s.
- **Group by best guess** when there's a reasonable hint, so she can confirm a whole group with one drag. For example, `Unsorted/Probably 2008/Grandma's 80th/...`. Hints, strongest first:
  - **Neighbors:** undated, sequentially numbered files from the same camera sitting between dated ones in the same folder (e.g. `DSC_0412` between dated `DSC_0411` and `DSC_0415`).
  - **The majority year** of the dated photos in the same source folder.
  - **File modified time,** but only if it's well before the import date and isn't identical across the whole folder. Identical times usually mean a bulk copy.
- **Guesses never sort photos into By Date on their own.** She confirms a guess by moving the photos herself.

### Naming
- Date folders: **year folders only**, `By Date/YYYY/`, e.g. `By Date/2026/`. No month folders. Photos dated only to a decade go in `By Date/1990s/`.
- Files with an exact timestamp: `YYYY-MM-DD_HH-MM-SS.ext`, with the extension lowercased. On a collision, append `_2`, `_3`, and so on. Store the original filename in the catalog.
- Files dated less precisely (by a `DATE -` folder or a folder name) get a **date prefix plus their original name**, so everything sorts by date: `2009-07-04 IMG_0001.jpg` (day), `2009-06 IMG_0001.jpg` (month), `2009 IMG_0001.jpg` (year), `1990s IMG_0001.jpg` (decade). Collision suffixes still apply.
- Files she placed by hand are never renamed. Files in Unsorted keep their original names.

---

## Trip / Event labels

Mom can drop a **folder** into the inbox named like `TRIP - Hawaii 2026`. Everything inside it (including subfolders like `Day 1`) gets that label. Photos still go to By Date as normal, and links appear in `My Photos/By Trip/Hawaii 2026/`.

Parsing has to be forgiving, because she won't type it the same way twice:
- Pattern is roughly `^\s*(\w+)\s*[-–—:]\s*(.+)$`. Split on the **first** separator only, so `TRIP - Hawaii - Maui` gives the label `Hawaii - Maui`.
- Any dash type or a colon, with or without spaces, in any capitalization.
- Normalize the group word: `Trip`, `TRIP`, and `Trips` → group `Trip` → folder `By Trip`. `EVENT - Christmas 2026` → `By Event/Christmas 2026`. Any group word works, so new groups need no code changes.
- **`DATE` is reserved.** `DATE - June 2009` sets a date (see Dates) instead of creating a view. Otherwise it would collide with the `By Date` folder.
- A folder name with no separator (`Christmas 2026`) goes under `Albums/Christmas 2026`.
- Labels match case-insensitively, so dropping another `trip - hawaii 2026` folder later adds to the same trip.
- Loose photos dropped directly into the inbox get no label, just date sorting.
- A photo can have multiple labels. Views are just links, so that's free.

---

## Views (link folders)

- Views are generated from the catalog by **registered view functions**. Each one maps catalog → `{folder path: [files]}`. v1 views: By Trip / By Event / Albums. Later: By Place, etc.
- Use **relative symlinks**, so they keep working if the drive mounts under a different `/Volumes/` name.
- Link names follow the same date-first naming so they sort chronologically.
- **Sync, don't nuke:** create missing links and remove stale ones. View syncing may only ever delete **symlinks and empty folders**. Never a real file.
- **If a real file is found inside a view folder** (e.g. she drags a photo into `By Trip/Hawaii 2026`), it's a request to label it. If its hash matches a catalog entry (she moved it out of By Date), put it back at its last known By Date location; otherwise import it as new. Either way, add the label and link it back. This is the one exception to "never move a file that's already in My Photos."
- **Renaming:** each label folder contains a hidden `.label-id` file holding its catalog ID. Before syncing, if a folder with a known ID has a new name, update the label in the catalog to match. Then her rename sticks instead of being reverted.
- v1 behavior for deleted links or label folders: they come back on the next run. The photos are safe in By Date either way. Document this; we may treat deletions as "remove label" later.

---

## Manual edits (Mom can rearrange things herself)

She should be able to fix things by hand in Finder, e.g. drag a photo from `Unsorted` into `By Date/2019`. The app adapts to her and never fights her.

- **The app never moves a file that's already in My Photos.** Wherever she puts it, it stays, and the app updates the catalog to match. The only exception is real files dragged into view folders (see Views).
- **Detecting moves and renames.** Each run, compare the catalog with what's on disk in By Date and Unsorted:
  - Catalog entries whose file is gone are *missing*.
  - Files at paths the catalog doesn't know are *unknown*.
  - Match unknown → missing by size, confirm with SHA-256, then update `rel_path`. Labels and history carry over.
  - Only hash files that are new or changed (by size + mtime), so runs stay fast on big libraries.
- **Folder location sets the date.**
  - A file she places in `By Date/2019/` (or any subfolder of it) is dated 2019, and one in `By Date/1990s/` is dated to the decade. The app never creates month folders, but if she makes one named like `06 - June` inside a year, files in it are dated to that month.
  - Record `date_source = manual` and the precision (month, year, or decade).
  - This applies even if the photo had an EXIF date and she moved it to a different year. Camera clocks are often wrong, and her placement wins. If the existing date already fits the folder (moved within the same year), the more precise date is kept.
- **Her own subfolders are fine.** `2019/Beach Day/` is allowed. Files inside are dated by the nearest year, decade, or month folder above them. Folders that don't match the year (`2009`), decade (`1990s`), or `MM - Month` pattern are ignored for dating.
- **Don't rename files she placed by hand.** We don't know their exact time, and she may have named them on purpose.
- **Moved into Unsorted:** the date becomes unknown.
- **Deleted or moved off the drive:** mark it missing and remove its links on the next view sync. This isn't an error and isn't worth mentioning to her.
- **A copy she made** (same hash as a file that still exists): leave it where it is, don't catalog it twice, and log it. Don't move it to Duplicates; that would be the app moving her stuff.
- **Leave `Duplicates (safe to delete)` alone** during reconcile. She can delete from it whenever she wants.
- **Put a short `How to fix these.txt` in `Unsorted/`:** "Folders under "Probably 2008" (and so on) are our best guess. If one looks right, drag it into that year in By Date. Know roughly when the others were taken? Drag them into the right year folder in By Date. Organize Photos will remember."
- **Limitation:** a fixed date lives in the folder and the catalog, not inside the photo file. A copy taken off the drive is undated again. Writing dates back into the file is a "later" idea.

---

## Catalog (SQLite)

A rough schema; adjust as needed. All paths are stored **relative to the drive root**.

- `photos`: id, sha256 (unique), rel_path, original_name, original_inbox_path, kind (photo/video), taken_at, tz_offset, date_source, date_precision (exact/day/month/year/decade/unknown), raw_meta_date, reject_reason, best_guess, guess_source, gps_lat, gps_lon, camera_make, camera_model, size, mtime, imported_at, run_id, status (ok/missing), pair_id (Live Photo), edited_of_id
- `labels`: id, group_name, label
- `photo_labels`: photo_id, label_id
- `runs`: id, started_at, finished_at, app_version, counts
- `moves`: run_id, src, dst, so I can write an undo tool if something goes wrong

**Store GPS and camera info now** even though v1 doesn't use them. A future By Place view is then just one function, without re-reading every photo.

---

## File types & special cases

- **v1 images:** jpg, jpeg, heic, heif, png, gif, tif, tiff, webp, dng.
- **v1 videos:** mov, mp4, m4v.
- **Non-photo files** (PDFs, docs, etc.): move to `Unsorted/Not Photos/` so the inbox actually empties, and mention them in the summary.
- **iPhone Live Photos:** a `IMG_1234.HEIC` + `IMG_1234.MOV` pair in the same folder is one item. Both get the photo's date and the same base name; record them as a pair.
- **iPhone edited versions:** `IMG_E1234.HEIC` is an edit of `IMG_1234.HEIC`. Keep it next to the original, named `<base>_edited.ext`.
- **`.AAE` sidecars:** only meaningful to Apple Photos and confusing to Mom. Move them to `.photo-organizer/sidecars/`, linked to their photo in the catalog.
- HEIC support: Pillow + `pillow-heif` (call `register_heif_opener()`).

---

## User experience

The app opens, does its work, shows a dialog, and quits. There's no main window.

- Use **native macOS dialogs and notifications via `osascript`** (`display dialog`, `display notification`). They look native and need no extra dependencies. Escape quotes properly.
- For big batches, show a notification at the start ("Sorting 412 photos — this may take a few minutes"). A small progress window can come later.
- On non-Mac platforms (my Windows dev machine), the UI layer falls back to printing to the console.

Message drafts (keep this tone):
- **Success:** "All done! 143 photos sorted into My Photos. Updated: Hawaii 2026, Christmas 2026. 3 photos didn't have a date, so they're in My Photos ▸ Unsorted."
- **Nothing to do:** "There's nothing to sort yet. Drag photos into the "Put New Photos Here" folder on your photo drive, then open Organize Photos again."
- **No drive:** "I can't find your photo drive. Plug it in, wait a few seconds, and try again."
- **Already running:** "Organize Photos is already working. Give it a minute."
- **Drive almost full (>90%):** a gentle heads-up added to the summary.
- **Any unexpected error:** "Something went wrong, but none of your photos were lost. Anything that wasn't sorted is still in "Put New Photos Here." Please let Mikkel know." Then write a detailed error report to `.photo-organizer/logs/`.

Wrap the entire run in a top-level handler, so no exception ever reaches her as a crash.

---

## Packaging & GitHub Actions

- **Python 3.12. PyInstaller in `--onedir --windowed` mode** to produce `Organize Photos.app`. Don't use `--onefile` with `--windowed` on macOS; PyInstaller has deprecated that combination.
- Bundle identifier: something like `com.mikkel.organizephotos`. Include a hidden import for `pillow_heif` if needed.
- **Unsigned** (no Apple Developer account). PyInstaller ad-hoc signs the bundle, which Apple Silicon requires; verify it with `codesign --verify --deep`.
- **Workflow** (`.github/workflows/`):
  - Run tests on every push and pull request on `macos-latest`. Windows too, if cheap.
  - Build job on `macos-latest` (Apple Silicon). Verify the binary is arm64. Zip the app with `ditto -c -k --keepParent` (a plain `zip` can break `.app` bundles). Upload it as a workflow artifact.
  - On a `v*` tag, attach the zip to a GitHub Release.
  - Allow a manual trigger (`workflow_dispatch`). Keep macOS jobs lean to save Actions minutes.

### Expected macOS behavior (document it in the README)
- **First launch:** because the app is unsigned and downloaded, macOS blocks it. Fix it once at setup with either System Settings → Privacy & Security → **Open Anyway**, or in Terminal: `xattr -dr com.apple.quarantine "Organize Photos.app"`. Clearing quarantine also prevents App Translocation.
- **First run:** macOS asks to let the app access files on a removable volume. She clicks Allow. Each new build may ask again, because an ad-hoc signature changes with every build.

---

## Developing & testing without a Mac

- Keep the core logic (metadata, naming, label parsing, catalog, view planning) **pure Python and platform-independent**. Put macOS-specific code (dialogs, `/Volumes` discovery) behind small interfaces with fakes for tests.
- CLI entry point for development: `python -m photo_organizer --drive <path> [--dry-run] [--verbose]`. Here `<path>` is any folder pretending to be the drive, and `--dry-run` prints the plan without touching anything.
- **Tests (pytest):** generate test images with known EXIF dates and GPS at test time using Pillow, and HEIC with pillow-heif. For videos, either check in one or two tiny sample files with known metadata, or mock the video metadata reader. No personal photos in the repo.
- **Date tests:** reset-default dates, future dates, scanner EXIF, folder-name parsing (`Christmas 2009`, `2009-06`, `June 2009`, nested paths), metadata-vs-folder conflicts, and neighbor guessing. For `DATE -` folders, test every format, decades, US numeric order, unparseable dates, overriding metadata, and nesting inside a TRIP folder.
- **Manual-edit tests:** move an Unsorted file into a month folder, rename a file, delete one, make a copy, and drag one into a trip folder. Confirm that labels survive, dates update, and nothing gets moved back.
- Symlinks on Windows need Developer Mode. Symlink tests should skip when unsupported locally; they always run in CI on macOS.

---

## Setup on Mom's Mac (Christmas checklist for me)

1. Format the drive as **APFS** in Disk Utility and give it a friendly name (e.g. "Family Photos").
2. Download the latest release zip, unzip it, and copy `Organize Photos.app` to the drive root.
3. Clear quarantine (see above) and open the app once. Click Allow on the removable-volume prompt.
4. Optionally drag the app to her Dock. Thanks to the drive marker, it still finds the drive.
5. Set up a backup (a second drive or a cloud service). One drive is one copy.
6. Do the first big import of her old photos together, then go through Unsorted with her once so she sees how fixing works.

---

## Out of scope for v1 (but don't paint us into a corner)

- **By Place view** (reverse geocode the stored GPS offline, e.g. with the `reverse_geocoder` package; photos without GPS go to "Unknown Place").
- **Folder Action automation:** sort automatically when files land in the inbox, no double-click.
- **"Back Up Now":** mirror My Photos to a second drive.
- Finder tags for labels (so she can click "Hawaii 2026" in the Finder sidebar).
- Treating deleted view links or folders as "remove label".
- Auto-grouping photos into events by gaps in time and location.
- RAW formats (NEF, CR2, ARW).
- Writing manually fixed dates back into the photo file's own metadata. This changes the original file, so only do it carefully.
- **Near-duplicate detection** (perceptual hashing) to catch resized or emailed copies of the same photo, so an undated copy can inherit its dated original's date.
- **A "shift dates" tool** for a camera whose clock was off by a fixed amount (e.g. set to the wrong year).
- An undo tool built on the `moves` table.
- A small progress window and an app icon.

---

## Decisions settled (Oct 2026)

- **By Date has year folders only** (see Naming). Dates finer than a year live in the file name and the catalog.
- **Albums:** only plain folders dropped *directly* into the inbox become albums. Deeper plain folders (`Day 1`, `Disneyland`) are just context: they're kept inside Unsorted paths and used for date hints. `GROUP - label` folders count at any depth.
- **A folder named only as a date** (`2004`, `June 2009`, `1990s`) is a date hint, never an album.
- **Finder stores a `/` typed in a name as `:` on disk,** so the DATE parser treats `:` like `/` (`DATE - 7:4:2009`).
- **The organizer's time zone is a setting** (`--timezone`, default: the computer's local zone), so UTC video times convert the same way in tests everywhere. Tests pin `America/Los_Angeles`. The `tzdata` package is a dependency so this works on Windows too.
- **A folder left with only ignorable files** (`.DS_Store`, `._*`) counts as empty: those junk files are deleted and the folder is removed.
- **A label keeps the spelling it was first created with.** Later case-insensitive matches join it without renaming it. Only a rename of the view folder in Finder changes it.
- **Group-word plurals:** `Trips` → `Trip`, `Events` → `Event`, but words ending in `ss/as/is/us/os` (`Christmas`) are left alone.
- **When two inbox files are identical,** the one named like a copy (`IMG_1 copy.JPG`, `IMG_1 (1).JPG`) is the one moved to Duplicates.
- **A copy of an already-cataloged photo dragged into a view folder** gets the label and is moved to Duplicates.
- **App name** `Organize Photos`, bundle id `com.mikkel.organizephotos`, folder names as above. No icon yet.
- **Local dev machine:** Windows Smart App Control blocks the uv-downloaded Python 3.12 and pillow-heif's DLL, so local development uses Python 3.14 (code must stay 3.12-compatible; CI runs 3.12). HEIC and symlink tests skip locally and run in CI.

## How to work on this repo

- **Start by proposing a plan** and module layout, then build in small, testable steps:
  1. Date sorting + dry-run on Windows
  2. Catalog
  3. Labels + views
  4. Mac UI + drive discovery
  5. GitHub Actions build
  6. Polish
- Ask before adding dependencies beyond: Pillow, pillow-heif, a pure-Python video metadata reader (e.g. hachoir), pytest, and PyInstaller.
- I can't test on a Mac myself, so briefly explain any macOS-specific decision, and lean on CI to verify Mac behavior.
- Open decisions to confirm with me when they come up: drive name, final folder names, app name and icon.
