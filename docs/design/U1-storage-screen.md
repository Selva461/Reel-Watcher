# U1: one "Storage" screen (design, not approved)

Base for every file:line below: `origin/stabilize/s4-4-files-set-aside` at **563f81f** (PR #70, **not merged**, 1.3.25 / 32; it contains Task 4, 5a-1, S4-1 to S4-4 and Task 2b). Lines marked **A2-3** are from `origin/stabilize/a2-3-existing-models` at **fd16625** (PR #68, not merged, a sibling line). The default branch (1.3.11) has none of S4, 5a or A2. Planning only: no code was changed.

## Problem
- Reel Shelf writes several kinds of files into its private storage (library, its `.bak`, files set aside for safety, AI and speech models, copies of shared pictures and videos, temporary files). Nothing shows the user what takes the space. The only size the user can see today is the AI model's (`local.js:1563`).
- The inboxes are not bounded (5a/5b design, "Storage (order of magnitude)": 100 shared reel videos can take 0.5 to 4 GB). Android's own app-storage page shows one total and offers "Clear storage", which deletes the whole library.
- The 5a design already asked for this screen: "A U1 Storage screen should *show* the inboxes ... with sizes and buttons the user chooses to press, instead of growing the automatic rules" (`docs/design/5a-5b-temp-files.md:156`).
- Goal: show, never delete by itself, and add **no new way to delete user data**.

## Verified in code (563f81f unless marked)
| What | Where on the phone | Written by | Shown today | Deleted today by |
|---|---|---|---|---|
| Library `reels.json`, `shots.json`, their `.bak`, `.tmp` | `files/` | `LibraryFile` (names at LibraryFile.java:115-116, schema 46-47) | nothing | `.bak` only by "Delete all reels and notes" (`dropBackup`, LibraryFile.java:570; local.js:1637) |
| Files kept for safety `NAME.bad-*`, `NAME.bak.bad-*`, `NAME.before-restore-*`, and the leftovers of `restore-staging/`, `backup-check/` as one row | `files/` | LibraryFile.java:373-377, 468-469; LocalBridge.java:357, 443 | `#/kept` (local.js:1462-1475), listed by `KeptFiles.listJson` (KeptFiles.java:292) | only the S4-4 Delete with a one-use token (KeptFiles.java:405, 442; local.js:1494-1545). **That Delete awaits the owner's decision** (PROJECT_CONTINUATION.md:42) |
| Backups made by Back up now | `Downloads/ReelShelf/` (Android 10+), or the app's own external folder on 8 and 9 (BackupNow.java:114) | `LocalBridge.backupLibrary` (LocalBridge.java:331) | the result of the last run only, in memory (`backup.result`, local.js:1200-1207) | never by the app |
| AI models `*.litertlm`, `.part` | `files/models/` (LocalModel.java:50) | download, `pickModel` | Settings card (local.js:1560-1566); `modelInfo` gives `bytes`, `partial`, `free`, `installed` (LocalBridge.java:949-968) | "Delete the model" with `confirm()` (local.js:1617; LocalBridge.java:1006-1013) |
| Model check sidecar `<file>.check` | next to the model | **A2-3** ModelCheck.java:100-155 | no | with the model (**A2-3** ModelCheck.java:150-155) |
| Speech model | `files/speech/` (SpeechModel.java:27) | `downloadSpeech` (LocalBridge.java:1185) | ready yes/no and the fixed size (LocalBridge.java:1171-1180) | "Delete the speech model" with `confirm()` (local.js:1192) |
| Shared pictures, videos | `files/shot-inbox/`, `files/video-inbox/` (ScreenshotReader.java:139, 149) | Task 4 `MediaBatch`/`MediaCopy` | no | never (5b, undecided) |
| Temporary files | `files/share-staging/` (SharedItems.java:36), `cache/reel-video*.mp4` (ReelVideo.java:58, 75), `cache/reel-media/` (ReelVideo.java:207), `*.json.tmp` | various | no | the 5a sweep, an allowlist (TempSweep.java:77-83), once per process 20 s after start (MainActivity.java:105) |
| Last sweep `{at, files, bytes, left_unknown}` | prefs `reelshelf`, key `last_sweep` | TempSweeper.java:103-105 | **nothing reads it** (only that line refers to it) | n/a |
| WebView data, LiteRT engine cache | `app_webview/`, `cache/` | the system, the engine | no | the system |

Also verified: no record of the last backup survives a restart (only `lastBackupNameTime` in memory, LocalBridge.java:46, 403-404); the manifest asks for no storage or media permission (AndroidManifest.xml:3-13), so the app cannot list files in Downloads that another install made; `allowBackup` is false (AndroidManifest.xml:24).

## Options
1. **A read-only Storage screen that links to the existing actions** (recommended). Sizes per kind, plus a link to the screen that already owns each action. No new delete.
2. Storage screen with its own buttons (delete model, delete kept file, clean temp). It duplicates confirm paths and would widen S4-4's Delete before the owner decides. Rejected.
3. Show sizes inside the existing Settings cards only. There is no single view, and the inboxes and temporary files have no card. Rejected.

## The change (option 1)
**Java, read-only:** a new pure class `StorageInfo` with `measure(File filesDir, File cacheDir, Io io)` (tested on a computer like `TempSweep`), and a bridge method `storageInfo(int id)` that runs on a background executor and answers through `done(id, ...)`. It must not run on the page thread, because walking the inboxes can be slow (NEEDS VERIFICATION on a phone with thousands of files).
- Rules, copied from the 5a sweep: fixed folders only; `NOFOLLOW_LINKS` (a link is counted as 0 and never followed); at most 2,000 entries per folder (then `"capped": true`); an `IOException` or `SecurityException` on a folder gives `"unknown"`, never 0. It deletes, renames and writes nothing.
- The answer contains **no file names and no paths**: `{at, free, groups: {library: {bytes, files}, library_backup_copy, kept: {bytes, files}, models: {bytes, files, partial_bytes}, speech, shot_inbox, video_inbox, temporary, ...}, last_sweep}`. `kept` takes its total from `KeptFiles.list` (the same allowlist, so the two screens agree).
- Optional, D-U1-6: Android's own total for the app (`StorageStatsManager.queryStatsForPackage` for our own package; that it needs no permission is NEEDS VERIFICATION).

**Page:** a route `#/storage` (a new row in `ROUTES`, local.js:1642-1651) opened from a "Storage" link in Settings next to "Backup and restore". One card per kind, from biggest to smallest:
| Card | Text (draft) | Action on this screen |
|---|---|---|
| Your library | "Reels, notes, watchlist: 34 MB. Previous copy (made at each save): 34 MB." | link "Back up now" (Settings, `#backup`) |
| Backups | "Backups are saved in Downloads/ReelShelf, outside Reel Shelf, and are not counted here." Plus D-U1-2. | link "Backup and restore" |
| Files kept for safety | "3 files, 70 MB. Reel Shelf never deletes them by itself." | link "See the files" (`#/kept`, the existing S4-4 screen, unchanged) |
| On-phone AI models | "Gemma 4 E2B: 2.6 GB. A paused download: 0.4 GB." | link "AI settings" (Settings) |
| Speech model | size, ready or not | link "Speech settings" |
| Shared pictures and videos | "Reel Shelf keeps its own copy of what you share: 812 pictures, 1.2 GB; 46 videos, 1.9 GB. Your gallery is not touched." | none (5b is not decided) |
| Temporary files | "12 MB. Cleaned automatically when the app starts. Last cleanup: 18 Nov, 3 files, 140 MB." | none (D-U1-4) |
| Free space | "Free on this phone: 21 GB" | none |

- "Measuring..." while the answer is coming; "unknown" when a group could not be read; "at least" when capped. Sizes use the existing `mb()` (local.js:38).
- No size is ever shown in red or called "too big". The screen never suggests deleting the library, kept files or inbox files.
- Works while the library is locked (sizes are file facts), but then it only shows (no links into Settings actions, as today's locked screen allows none).
- U1 adds no delete, no rename and no write. Every existing delete keeps its own confirmation where it is today.

## Failure modes
- Sizes change while a job runs (a share, a night run, a download). The screen says "as of 14:02" and has "Measure again"; it does not poll.
- The measure is still running when the user leaves: the answer is dropped (the same `kept === mine` pattern, local.js:1490, 1541).
- A huge inbox: capped at 2,000 entries per folder, shown as "at least". Slow storage: the page stays responsive because the work is off the page thread.
- A link inside an inbox (made by another app or a rooted user): counted as 0, never followed.
- Totals will not match Android's app-info number (code, WebView data and the engine cache are counted there). The screen says so in one line.
- The nightly page (`isNight`) never calls it; the headless run has no screen.

## Tests
- **JUnit `StorageInfoTest`** (temp folders): each group sums the right files; `.bak` and `.tmp` go to the right group; a symlinked file and a symlinked folder count 0 and the target is untouched; more than 2,000 entries gives `capped`; an unreadable folder gives `unknown`; the JSON has no file name or path (search the output for every name created); the folders are byte-identical before and after (no write).
- **JUnit:** `kept` equals `KeptFiles.list` for the same folder.
- **Phone harness `tests/test_storage_screen.py`** (fake `RN.storageInfo`): every card and text; "unknown" and "at least"; leaving during "Measuring..." does not repaint; the screen has no button whose label contains "Delete" or "Remove"; the links go to `#/kept` and `#/settings`; locked library shows sizes with no links; the Settings link exists; nothing calls `deleteKept`, `deleteModel`, `deleteSpeech` or `dropBackup`.

## PR split
1. **U1-1** (stacked on #70; publishing PR, left READY): `StorageInfo.java`, `StorageInfoTest.java`, `LocalBridge.storageInfo`, the `#/storage` route and screen, the Settings link, `tests/test_storage_screen.py`, CHANGELOG, TESTING rows, version bump. One Opus review (it reads every app folder, so data safety first).
2. Later, only with D-U1-2: record the last backup's time and size in prefs from `backupLibrary`.

## Device checks (owner only; the AI ran no phone test)
- U1-a: with a big library, 100+ shared videos and a model, open Storage: the numbers appear within a few seconds and the app stays responsive. Record the time (NEEDS VERIFICATION).
- U1-b: compare the total with Android Settings > Apps > Reel Shelf > Storage and note the difference.
- U1-c: open Storage during a nightly run and during a share: no error, no change to the library.
- U1-d: every link opens the right place; nothing is deleted by any tap on the screen.

## Owner decisions (recommended default first)
- **D-U1-1** Where: a "Storage" link in Settings. Alternative: a card on the Inbox tab.
- **D-U1-2** Remember the last backup (time, size, file name without a path) in prefs, so the Backups card can say "Last backup: 18 Nov, 34 MB". Alternative: nothing (today's behaviour).
- **D-U1-3** Models and speech: a link to Settings, where Delete already is. Alternative: a Delete button on Storage that calls the same `deleteModel` with the same `confirm()` text.
- **D-U1-4** Temporary files: show only; the 5a sweep stays automatic. Alternative: a "Clean up now" button that runs the same `TempSweeper` allowlist.
- **D-U1-5** Shared pictures and videos: totals only until 5b is decided. Alternative: a per-reel list (which reels hold which videos), still with no delete.
- **D-U1-6** Show Android's own total (if it needs no permission). Alternative: leave it out.

## Risks
- A user reads a big number as advice to clear the app in Android settings, which deletes the library. Mitigation: one line on the screen: "Clearing Reel Shelf's storage in Android settings deletes your library. Back up first."
- Measuring thousands of files on a slow phone could take long or wake the disk often (NEEDS VERIFICATION, U1-a).
- The S4-4 Delete decision changes what the "Files kept for safety" link leads to; U1 does not depend on it either way.

## Out of scope
Deleting anything new; 5b; listing files in Downloads (needs a permission the app does not ask for); WebView cache control; quotas or warnings.
