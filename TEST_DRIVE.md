# Test Drive — build spec

Build a **fake photo drive** I can generate on my Windows PC, run the organizer against, and check automatically. It's the main way I'll verify the app, since I don't have a Mac.

**Before starting:** read `CLAUDE.md` and the existing code. Plug into the existing CLI and modules; don't restructure working code.

Expected results below follow `CLAUDE.md`. If an expectation here conflicts with `CLAUDE.md` or the current code, **stop and ask me which is right**. Never weaken a test, or the spec, just to make it pass.

> **Settled Oct 2026** (these override the first draft of this file):
> - **Only two views: By date and By event.** No By Trip, no Albums. App-made names use sentence case (`My photos`, `By date`, `Put new photos here`).
> - By date has **year folders only** (`By date/2024/`), with no month folders.
> - Files without an exact timestamp get a **date prefix + original name** (`2004 dl_1.jpg`, `2009-06 scan_101.jpg`, `1990s p_1.jpg`).
> - Videos are made by the **built-in MP4/MOV writer** (`photo_organizer/testdrive/media.py`), not ffmpeg, so video scenarios always run. The files aren't playable, but the organizer only reads their metadata.
> - The "still copying" file gets a modified time **in the future**, so it stays inside the 15-second window however long you wait before running.

**Status:** all six steps are built. `python -m photo_organizer.testdrive full <folder>` runs everything in one go, and CI runs it on every push (and again against the built Mac app).

---

## Commands

All under `python -m photo_organizer.testdrive`:

| Command | Does |
|---|---|
| `make <folder> [--reset]` | Creates a folder laid out like Mom's drive (`.photo-organizer/drive-marker`, empty `My photos/`, and `Put new photos here/` filled with the scenarios below) plus `expected.json`. `--reset` wipes the folder first (it refuses if the folder has no `expected.json`). |
| `make <folder> --big 5000` | Same layout, plus 5,000 plain phone-style photos (EXIF dates spread over 2015–2025), for timing a first big import. |
| `check <folder> [--phase first-run\|after-edit] [--feature X]` | Compares the drive to `expected.json`. Prints one ✓/✗ line per file, grouped by feature, then a summary. Exits non-zero on any failure. |
| `edit <folder>` | Simulates Mom rearranging things after the first run, and drops a second small batch into the inbox (see Phase 2). |
| `snapshot <folder> [--save FILE] [--compare FILE]` | Prints a list of every path + hash, used for the "second run changes nothing" check. `--compare` diffs against a saved snapshot. |
| `full <folder> [--app BINARY] [--big N]` | The whole sequence: make → organize → check → organize again (nothing may change) → edit → organize → check after-edit → organize again. `--app` runs a built app binary instead of the Python package. |

Run the organizer in between with `python -m photo_organizer --drive <folder> --timezone America/Los_Angeles`. `make` prints the exact command.

Default location for test drives: `test-drives/` in the repo. It's in `.gitignore`. I may drop real photos into a test inbox by hand, and they must never be committed.

---

## Generator requirements

- **Deterministic.** Use fixed dates. Set every file's modified time explicitly with `os.utime`. By default, every file gets the same old modified time (2026-01-15 12:00). It's outside the "still copying" window, and because it's identical across a folder it never produces a modified-time guess. Only the future-date and still-copying scenarios depend on today's date.
- **Each image tells its own story.** Use Pillow to draw on the picture:
  - The scenario name.
  - The file's ID.
  - Where it should end up, e.g. "Expected: By date/2024/2024-07-14_15-30-22.jpg".

  Give each scenario its own background colour. `ImageFont.load_default(size=…)` is fine. Keep images ~640×480.
- **Unique bytes.** Every file must be unique, or the organizer will treat them as duplicates. The only exception is the deliberate duplicate scenario. This applies to `--big` too: vary the drawn text.
- **EXIF writing.** Use Pillow's `Image.Exif`:
  - `DateTimeOriginal` (+ `OffsetTimeOriginal` where noted).
  - `Make` / `Model` / `Software`.
  - The GPS IFD.

  Use pillow-heif for HEIC with EXIF. Where pillow-heif can't load, HEIC scenarios are reported as **skipped**.
- **Videos.** Use the built-in writer to set the `mvhd` creation time (UTC, which is what ffmpeg's `creation_time` writes) and/or Apple's `com.apple.quicktime.creationdate`.
- **Time zone is pinned for tests.** The organizer accepts `--timezone` (default: the computer's local zone). Tests pin `America/Los_Angeles`, so UTC video timestamps convert the same way on every machine.

---

## Manifest (`expected.json`)

One entry per generated file:

```json
{
  "id": "event-exif-1",
  "feature": "labels",
  "phase": "first-run",
  "source": "Put new photos here/EVENT - Hawaii 2026/IMG_2001.JPG",
  "sha256": "…",
  "expect": {
    "dir": "My photos/By date/2026",
    "name": "2026-07-10_11-00-00.jpg",
    "date": "2026-07-10T11:00:00",
    "precision": "exact",
    "labels": ["Event: Hawaii 2026"],
    "links": ["My photos/By event/Hawaii 2026"]
  }
}
```

- **Match files by hash.** `check` finds each file by `sha256`, because names change.
- **Optional fields.** `name: null` means "any name". `date`, `precision`, `reject_reason`, `gps`, and `labels` are checked against the catalog.
- **Expected links:** a symlink in each `links` folder pointing at the file. If symlinks are unsupported (Windows without Developer Mode), link checks are reported as skipped.
- **Features not built yet.** The list of built features is in `photo_organizer/testdrive/features.py`. `check` and pytest report scenarios for unbuilt features as **pending**, not failed.
- The manifest also holds non-file checks (`absent`, `inbox-only`), the expected run-summary counts, and the scenarios that were skipped and why.

---

## Phase 1 scenarios (first run)

Paths are relative to `Put new photos here/` (input) and `My photos/` (expected), unless they start with `.photo-organizer/`.

### `date-basic`
| Input | Setup | Expected |
|---|---|---|
| `IMG_0001.JPG` | EXIF 2024-07-14 15:30:22 | `By date/2024/2024-07-14_15-30-22.jpg` |
| `IMG_0002.HEIC` | EXIF 2025-03-08 09:05:00 + GPS | `By date/2025/2025-03-08_09-05-00.heic`, GPS in catalog |
| `IMG_0003–0005.JPG` | all EXIF 2024-07-14 16:00:00 (burst) | same folder: `2024-07-14_16-00-00.jpg`, `…_2.jpg`, `…_3.jpg` |
| `Screenshot 2025-03-02 at 9.14.07 AM.png` | no EXIF | `By date/2025/2025-03-02_09-14-07.png` |
| `WhatsApp Image 2023-11-05 at 18.22.10.jpeg` | no EXIF | `By date/2023/2023-11-05_18-22-10.jpeg` |
| `IMG_0006.JPG` | EXIF 2020-01-01 00:00:30, Make Apple (a real New Year's photo, single) | `By date/2020/` (**not** rejected) |
| `VID_0001.MP4` | creation time 2024-07-14T22:30:22Z | `By date/2024/2024-07-14_15-30-22.mp4` (UTC → LA time) |

### `iphone`
| Input | Setup | Expected |
|---|---|---|
| `IMG_1234.HEIC` + `IMG_1234.MOV` | EXIF 2024-12-25 08:00:00 on the HEIC | both in `By date/2024/` as `2024-12-25_08-00-00.heic` / `.mov`, recorded as a pair |
| `IMG_E1234.HEIC` | edited version | same folder, `2024-12-25_08-00-00_edited.heic` |
| `IMG_1234.AAE` | sidecar | `.photo-organizer/sidecars/`, linked to its photo in the catalog |

### `sanity`
| Input | Setup | Expected |
|---|---|---|
| `scan_001.jpg` | Make EPSON, Model Perfection V600, EXIF 2021-05-01 | `Unsorted/Date unknown/scan_001.jpg`, reject reason = scanner |
| `DSC00001–3.JPG` | Model DSC-W55, EXIF 2000-01-01 00:00:05 / 00:00:12 / 00:00:40 | `Unsorted/Date unknown/` (original names), reject reason = reset default |
| `IMG_0007.JPG` | EXIF now + 2 years | `Unsorted/Date unknown/`, reject reason = future |
| `photo.jpg` | no EXIF, no clues | `Unsorted/Date unknown/photo.jpg` |

### `guesses`
| Input | Setup | Expected |
|---|---|---|
| `Camping/DSC_0410.JPG`, `DSC_0413.JPG` | EXIF 2011-08-20 10:00 and 10:20 | `By date/2011/` |
| `Camping/DSC_0411.JPG`, `DSC_0412.JPG` | no EXIF (between dated neighbors) | `Unsorted/Probably 2011/Camping/` |
| `Beach/beach_1–4.jpg` | EXIF June 2015 | `By date/2015/` |
| `Beach/beach_a.jpg`, `beach_b.jpg` | no EXIF, no neighbors | `Unsorted/Probably 2015/Beach/` (majority year) |
| `Old Pics/old_1–3.jpg` | no EXIF; mtimes 2008-03-04, 2008-07-19, 2008-11-02 | `Unsorted/Probably 2008/Old Pics/` |
| `Copied/c_1–3.jpg` | no EXIF; identical mtime (yesterday) | `Unsorted/Date unknown/Copied/` (bulk copy → no guess) |

Plain folders here (`Camping`, `Beach`, `Old Pics`, `Copied`) make no views; they're only context and date hints.

### `folder-hints`
| Input | Setup | Expected |
|---|---|---|
| `Old Laptop/2004/Disneyland/dl_1.jpg`, `dl_2.jpg` | no EXIF | `By date/2004/2004 dl_1.jpg` (year precision, date prefix) |
| `Old Laptop/2004/Disneyland/dl_3.jpg` | EXIF 2004-05-02 | `By date/2004/2004-05-02_…jpg` |
| `Christmas 2009/xmas_1.jpg`, `xmas_2.jpg` | no EXIF | `By date/2009/2009 xmas_1.jpg` |
| `Christmas 2009/xmas_3.jpg` | EXIF 2005-12-24 | `By date/2005/` (metadata wins), conflict logged in the catalog |

There is **no** `Albums` folder at all (plain folders never make views).

### `labels`
| Input | Setup | Expected |
|---|---|---|
| `EVENT - Hawaii 2026/IMG_2001–2003.JPG` | EXIF 2026-07-10…12 | `By date/2026/` + links in `By event/Hawaii 2026/` |
| `EVENT - Hawaii 2026/hawaii_nodate.jpg` | no EXIF | `By date/2026/2026 hawaii_nodate.jpg` (year fallback) + link in `By event/Hawaii 2026/` |
| `EVENT - Christmas 2025/IMG_3001–3002.JPG` | EXIF 2025-12-25 | `By date/2025/` + `By event/Christmas 2025/` |
| `EVENT - Yellowstone 2019/Day 1/IMG_4001–4002.JPG` | EXIF June 2019 | `By date/2019/` + `By event/Yellowstone 2019/` (no `Day 1` anywhere in views) |
| `Grandma's Recipes/r_1–2.jpg` | EXIF Oct 2022 | `By date/2022/` (no view: plain folder) |
| `Trip-Zion 2021/z_1.jpg` | EXIF May 2021 | `By event/Zion 2021/` (another word before the dash still makes an event) |
| `Event – Graduation 2018/g_1.jpg` | EXIF May 2018; **en dash** | `By event/Graduation 2018/` |

### `date-folders`
| Input | Setup | Expected |
|---|---|---|
| `DATE - June 2009/scan_101–102.jpg` | scanner EXIF 2021 | `By date/2009/2009-06 scan_101.jpg` |
| `DATE - June 2009/cam_101.jpg` | camera EXIF 2012-03-03 | `By date/2009/2009-06 cam_101.jpg` (DATE overrides metadata), metadata date kept in `raw_meta_date` |
| `DATE - 1990s/p_1–2.jpg` | no EXIF | `By date/1990s/1990s p_1.jpg`, precision decade |
| `DATE - July 4 2009/j_1.jpg` | no EXIF | `By date/2009/2009-07-04 j_1.jpg`, precision day |
| `DATE - 7:4:2009/k_1.jpg` | **macOS only** | `By date/2009/2009-07-04 k_1.jpg`, precision day |
| `EVENT - Hawaii 2009/DATE - June 2009/h_1–2.jpg` | camera EXIF 2013 | `By date/2009/2009-06 h_1.jpg` + `By event/Hawaii 2009/` |
| `DATE - a long time ago/lt_1.jpg` | no EXIF | `Unsorted/Date unknown/DATE - a long time ago/lt_1.jpg`; the run summary mentions the unreadable date; no `By date/<label>` view is created |

### `edge`
| Input | Setup | Expected |
|---|---|---|
| `IMG_0001 copy.JPG` | exact same bytes as `IMG_0001.JPG` | `Duplicates (safe to delete)/` |
| `recipe.pdf` | a tiny PDF | `Unsorted/Not photos/recipe.pdf` |
| `Junk Only/.DS_Store`, `Junk Only/._IMG_0001.JPG`, `Junk Only/Deeper/.DS_Store` | — | ignored; the folder counts as empty and is removed |
| `IMG_0099.JPG` | EXIF 2024-01-01 12:00; **mtime in the future** (still copying) | stays in the inbox after this run, gets sorted on the next run |

**After phase 1:** the inbox holds only `IMG_0099.JPG`, and the run summary counts match the manifest.

---

## Phase 2: Mom edits things (`edit`, then run again, then `check --phase after-edit`)

`edit` performs these on the organized drive, recording expectations for each:

| Edit | Expected after the next run |
|---|---|
| Move `Unsorted/Date unknown/photo.jpg` into `By date/2010/` | stays there; catalog date 2010, precision year, source manual |
| Move another Unsorted photo into a month folder she made, `By date/2010/03 - March/` | stays there; catalog date March 2010, precision month, source manual |
| Drag the whole `Unsorted/Probably 2011/Camping` folder into `By date/2011/` | files stay in `By date/2011/Camping/`, dated 2011 (nearest year folder); the guess is cleared because she confirmed it |
| Rename `By event/Hawaii 2026` → `Maui 2026` | stays `Maui 2026`, links intact, and `Hawaii 2026` is **not** recreated |
| Delete one Christmas 2025 photo from `By date` | its link disappears from `By event/Christmas 2025/`; catalog status missing; no error |
| Move `By date/2022/<recipe photo>` into `By event/Maui 2026/` | moved back to its By date spot; link added in `Maui 2026` |
| Rename `By date/2024/2024-07-14_15-30-22.jpg` → `Mom favorite.jpg` | stays renamed; catalog path updated; nothing else changes |
| Copy a photo within its By date folder | copy left alone, not cataloged twice, logged |
| Delete one link from `By event/Yellowstone 2019/` | link comes back (v1 behavior) |
| Drop a new inbox folder `event - yellowstone 2019/` with 1 photo (EXIF June 2019) | joins the existing `By event/Yellowstone 2019/` (case-insensitive match, no second event) |
| Make `IMG_0099.JPG` old enough to pick up | now sorted into `By date/2024/2024-01-01_12-00-00.jpg` |

---

## Idempotency

- **After phase 1:** `snapshot` → run again → `snapshot`. They must be identical, and the summary says there was nothing to sort (or only that `IMG_0099.JPG` is still copying).
- **After phase 2:** run again; the snapshots must again be identical.

---

## pytest end-to-end

`tests/test_testdrive_e2e.py`:
1. Generate into `tmp_path` (with `--big 50`), run the organizer, assert phase 1.
2. Assert idempotency.
3. Run `edit`, run the organizer, assert phase 2, then assert idempotency again.

Unbuilt features are `xfail` (pending), not skipped silently. The macOS-only and HEIC scenarios are skipped with a clear reason where unavailable. This runs in the GitHub Actions jobs.

---

## Rules this file settles (now in `CLAUDE.md`)

1. **Only `EVENT - name` folders make views** (By event). Any other word before the dash (`TRIP`, a typo) also becomes an event. Plain folders (`Day 1`, `Disneyland`) are just context: kept inside Unsorted paths and used for date hints.
2. **A folder named only as a date** (`2004`, `June 2009`, `1990s`) is a date hint.
3. **Finder stores a `/` typed in a name as `:` on disk.** So the DATE parser treats `:` like `/` (`DATE - 7:4:2009`). Such names can't exist on Windows, so this scenario runs on macOS only.
4. **The organizer's time zone is a setting** (default: the Mac's local zone), so tests are deterministic.
5. **A folder left with only ignorable files** (`.DS_Store`, `._*`) counts as empty and is removed.
6. **A label keeps the spelling it was first created with.** Later case-insensitive matches join it without renaming it.

---

## Order of work

1. ✅ Generator + `expected.json` for `date-basic` and `edge`, and the `check` command.
2. ✅ The remaining phase 1 scenarios.
3. ✅ `snapshot` + the idempotency check.
4. ✅ `edit` + phase 2.
5. ✅ `--big`. (5,000 photos sort in about 16 s on the dev PC.)
6. ✅ The pytest e2e test and CI.

Show me `check` output after step 1 so I can see the format before you go further.
