# S4: real backup and restore of the library (design, not approved)

Base: `origin/ccr-d0c0b070-bdpssy` at f6a3f29 (Reel Shelf 1.3.11, versionCode 18). Planning only: no code was changed.

## Problem
`allowBackup="false"`, so Android keeps no copy. The only "backup" today is `Notes.exportJson` (Settings "Save JSON", and step 5 of the manual Overnight run, whose text calls it "a backup"). It keeps 15 note fields per reel. It drops the watchlist (`db.media`), quotes, products, `inbox`, `verify_rules`, YouTube transcripts, on-screen text, `status` and every other field. Nothing can read it back. If the phone is lost or the app is uninstalled, the library is gone.

## What a backup is
One **ZIP** file (`java.util.zip`, DEFLATED; JSON usually compresses several times smaller) named `ReelShelf-backup-YYYYMMDD-HHMMSS.zip` in `Downloads/ReelShelf` (MIME `application/zip`). It holds three entries:
- `reels.json`: a **byte-exact** copy of the file on disk, which already holds the reels, watchlist, quotes, products and inbox.
- `shots.json`: a byte-exact copy, when that file exists.
- `manifest.json`, written last: `{"format":"reelshelf-backup","format_version":1,"created_at":ISO,"app":{"version_name","version_code"},"files":{"reels.json":{"bytes","sha256","schema_version"},"shots.json":{...}},"counts":{"reels","titles","screenshots"},"contains":"reels, notes, watchlist, quotes, products; no settings, no API keys, no pictures or videos"}`.
  `counts` is only for display. The page passes it in (`db.reels.length`, `db.media.length`), so Java never parses the library to make a backup.

**Left out on purpose:**
- **Settings (SharedPreferences `local_settings`).** They hold the optional TMDB/OMDb keys. A file in Downloads can be read by file managers and by apps with storage access, and people copy it to cloud drives. The model file name and the persisted folder URIs do not carry over to another phone anyway.
- **Models and the speech model** (several GB, downloadable again).
- **Media:** `shot-inbox/`, `video-inbox/`, Task 4's `share-staging/`, and folder grants.
- `verify-results.json`, `.bak` and `.bad-*` files.

The page must say all of this in plain words (see UI).

## Making a backup without loading the library twice
New pure-Java class **`LibraryBackup`** (files, org.json, `java.util.zip`, `MessageDigest`; JUnit-testable like `LibraryFile`). It is called from a new bridge method `LocalBridge.backupLibrary(int id, String countsJson)` on the `work` executor:
1. Refuse when `reelsFile().locked()` (unreadable, or "newer" after R4). The page then offers the existing `saveUnreadable` instead.
2. **Snapshot under the lock, in microseconds:** a new `LibraryFile.snapshotTo(File dest)` (synchronized) makes a **hard link** (`Files.createLink`) of `main` into `filesDir/backup-work/`. This is safe because `LibraryFile` never rewrites `main` in place. Every save writes `.tmp` and renames it (`write`, `move`), so the linked inode never changes. If linking fails, it falls back to `Files.copy`, still under the lock. Both files are snapshotted with the reels lock taken first and the shots lock inside it, so the pair is consistent. Nothing else takes both locks, so there is no lock-order inversion.
3. Check free space: the estimate is the sum of the raw sizes plus the same 100 MB reserve Task 4 uses (`SharedItems.RESERVE_BYTES` on its branch; use a local constant if Task 4 is not merged yet).
4. Stream each snapshot through a `DigestInputStream` into a `ZipOutputStream`, using the existing `saveToDownloads(name, mime, Writer)` (LocalBridge.java:214), which deletes a half-written MediaStore entry on failure. Write `manifest.json` last. Memory use is a 64 KB buffer: nothing is parsed or held whole.
5. **Read it back:** open the saved URI and run `LibraryBackup.check` on it (step A of restore below, without installing anything). A backup that cannot be restored is reported as failed and its entry is deleted.
6. Remove the files in `backup-work/`. They are our own temporary links, not user data.

The page shows a progress state and then "Saved to Downloads/ReelShelf/ReelShelf-backup-....zip (N reels, X MB)". `saveToDownloads` currently hard-codes the message "There is no unreadable file to save" for `w.to() < 0`. That message must become a parameter.

**Android 8 and 9** (minSdk 26): `saveToDownloads` falls back to `getExternalFilesDir(...)`, which **Android deletes on uninstall**. On those versions the page must say so (owner decision D3).

## Restoring safely (two steps; nothing changes until the second)
**A. Check** (`RN.chooseBackup(id)`): the page refuses while `run`, `night`, `Verify.job` or `Shots` work is running. Java checks again: `WorkService.isRunning()`, and on Task 2b `WorkService.nightActive()`. The app is visible during a restore, so 2b's `NightGuard` skips a nightly alarm (`SKIP_VISIBLE`).
- Pick the file with the existing `act.pickModelFile` (ACTION_OPEN_DOCUMENT, `*/*`). Reusing it avoids changing `Host`, `MainActivity` and `NightRun.Headless`. A null URI means "No file chosen" and nothing happens.
- `LibraryBackup.check(InputStream, File staging, long maxBytes)` streams the ZIP into `filesDir/restore-staging/` (`.part`, then rename) and hashes each entry as it goes.
- It **refuses** the file when any of these hold:
  - an entry name is not exactly `manifest.json`, `reels.json` or `shots.json` (this blocks zip-slip, directories and anything extra);
  - an entry appears twice;
  - an entry exceeds `maxBytes` (free space minus the reserve, and never more than 1 GB);
  - the manifest is missing or unparseable, or `format` is not `reelshelf-backup`;
  - `format_version > 1` ("made by a newer Reel Shelf: update first");
  - a listed file is missing, or its `bytes` or `sha256` differ (this is what catches a partial or truncated download; ZIP CRC alone is weaker);
  - `reels.json` is absent;
  - `schema_version` is newer than this app supports (R4);
  - the content fails `LibraryFile`'s own validity rules. The private `valid(File)` becomes a static `LibraryFile.isValid(File, Shape)` used by both places: whole object, nothing after it, no NUL, `RELS`/`SHOTS` shape.
- A raw `reels.json` or the old `reel-notes-*.json` export is refused with a sentence explaining why (owner decision D4).
- The result is a preview `{token, created_at, app_version, reels, titles, has_shots, bytes}` plus the current counts. Only the restore check parses the library, once per file: the same cost as today's `load()`, which already parses through `valid(main)`.

**B. Confirm screen** (`#/restore`): "Replace your library (1,204 reels, 88 titles) with the backup from 3 Nov 2026 (1,150 reels, 80 titles)? Your current library is kept on the phone, not deleted." There is a checkbox, **on** by default (D2): "Save a backup of the current library first". It runs the backup steps above and is the user's undo.

**C. Install** (`RN.restoreBackup(id, token)`): run the job and night checks again, then call a new `LibraryFile.replaceWith(File staged)` (synchronized) for reels, then for shots:
- If `main` exists, rename it to `reels.json.before-restore-STAMP` (unique, using the same naming loop as `quarantine`). **It is never deleted or overwritten.**
- Rename the staged file onto `main`. Both are in `filesDir`, so the rename is atomic.
- Leave `.bak` untouched. Set `trusted=true`, `locked=false`, `state=OK`, `notice="restored"`, and `revision++`.
- If the second rename fails, move the set-aside file back and report the error.
- This works while the library is locked, so restoring is also a recovery path from an unreadable library.
- The revision bump means any other page, including a stray nightly page, has its next `store` refused as stale (Task 2a). The bridge does **not** adopt the new revision.
- If the backup has no `shots.json`, the current one stays (it can be rebuilt from the pictures).
- If reels succeed but shots fail, report exactly that.

**D. After:** the page calls `location.reload()`. Settings, library, `Shots` and `openLibrary()` load fresh. **The share queue is untouched** because it lives in prefs and items stay until `ackShared`, so anything shared but not yet filed is filed into the restored library. `verify-results.json` is left alone: `Catalog.verify` ignores ids it cannot find (catalog.js:197-199). The toast names the set-aside file. `restore-staging/` is cleared on cancel, after install, and at the next `chooseBackup`.

## UI and privacy
- A new Settings section, "Backup and restore", with the buttons "Back up now" and "Restore from a backup", plus a "Restore from a backup" button on `lockedScreen`.
- The text must say: "The backup contains all your reels, notes, watchlist, quotes and products. Anyone who gets the file can read them. It does not contain your settings, API keys, AI models, pictures or videos."
- After a restore: "Pictures and videos are not in backups; reels whose video is no longer on this phone keep their notes."
- The existing "Save JSON" button becomes "Export notes (JSON, cannot be restored)".
- The manual Overnight run's step 5 should make a real backup instead (D1).

## Failure modes
| Case | Behaviour |
|---|---|
| Low storage (backup or restore) | Refused before writing; the half-written entry is deleted; the library is untouched |
| Picker returns nothing | "No file chosen", no change |
| Backup from a newer app (`format_version` or `schema_version`) | Refused: "Update Reel Shelf first" |
| Corrupt, partial or truncated file, or hash mismatch | Refused, naming the file that failed; staging is cleared |
| Crash during C | Either the old main is still in place, or it is safe as `before-restore-*` and the new main is complete (renames only). `read()` falls back to `.bak` if main is missing |
| Job or nightly run active | Refused: "Stop the running work first" |

## Verified in code (origin/ccr-d0c0b070-bdpssy)
- `AndroidManifest.xml:24` `allowBackup="false"`, `:25` `largeHeap="true"`
- `build.gradle:11-14` minSdk 26, versionCode 18, versionName 1.3.11
- `LibraryFile.java`:
  - 47-49: the RELS and SHOTS shapes
  - 154-191: `read()` and backup restore
  - 194-206: private `valid`
  - 214-246: `write`, including the revision check and the `main`→`bak` rename
  - 271-277: the `quarantine` naming
  - 290-300: `startNew`
  - 306-317: `unreadableFile` and `copyUnreadableTo`
  - 85-86: the revision lives in memory only
- `LocalBridge.java`:
  - 112-126: `load` and `store` with `reelsRev`
  - 164-177: `libraryStartNew`, which adopts the revision
  - 190-207: `saveUnreadable`
  - 214-244: `saveToDownloads`, including the hard-coded message at 225 and 237, and the getExternalFilesDir fallback below API 29
  - 250-271: `peekShared` and `ackShared`, kept in prefs
  - 274-299: settings in prefs `local_settings`
  - 337-369: `saveFile`
  - 609-630: `pickModel` (ACTION_OPEN_DOCUMENT `*/*` through `pickModelFile`)
  - 1068-1092: `loadShots`/`storeShots`
- `MainActivity.java:109-119` `pickModelFile`; `NightRun.java:179` Headless `pickModelFile` returns null
- `notes.js:713-725` the lossy `exportRows`/`exportJson`; `local.js:637-641` the Overnight "backup" step; `local.js:1265` the Save JSON button; `local.js:74-88` `loadDb` keeps unknown keys
- `catalog.js:4` the watchlist is stored inside reels.json; `catalog.js:197-199` `verify` ignores unknown ids
- `VerifyJob.java:136-138` reads reels.json under the `LibraryFile.reels(dir)` monitor
- `WorkService.java:69` `isRunning()`

**Not on the default branch** (read from the branches): `NightGuard`/`WorkService.nightActive()` (stabilize/task-2b, unmerged), and `SharedItems.staging` `share-staging` and `RESERVE_BYTES=100 MB` (stabilize/task-4, unmerged).

**Not verified:** peak memory of org.json parsing a 60 MB file on a phone (never measured); `Files.createLink` on every phone's filesDir filesystem (the fallback covers it); how fast DEFLATE runs on a phone.

## Risks
- **Restore is the only path that intentionally replaces the library.** Mitigations: two steps, full validation, the set-aside file, the optional pre-backup, and a revision bump.
- `before-restore-*`, `.bad-*` and `backup-work` leftovers use space invisibly. Follow-up S4-4 lists them.
- The backup file leaks all notes if shared (the UI says so).
- Without Task 2b merged, a nightly run could start between A and C. **S4-3 depends on 2b.**
- Restoring a backup older than 2a/R4 is fine (additive), but it brings back reels the user deleted afterwards. That is expected; the confirm text says "replace".

## PR split (each one passes `uv run pytest tests/test_phone_app.py tests/test_library_safety.py tests/test_stale_writes.py` and the CI `testReleaseUnitTest`)
1. **S4-1 core, no UI.**
   - Files: `LibraryBackup.java` (new); `LibraryFile.java` (`isValid` static, `snapshotTo`, `replaceWith`); `LibraryBackupTest.java` (new); `LibraryFileTest.java`.
   - JUnit:
     - round trip byte-identical, for reels and shots;
     - manifest fields and hashes;
     - refusals: truncated at several offsets, hash mismatch, extra or `../` entry, duplicate entry, missing reels.json, format 2, newer schema, bad shape, trailing junk, NUL, oversize;
     - `replaceWith`: the old file is kept as `before-restore-*` byte-identical, `.bak` is untouched, the revision advances, an old-revision write is refused, it works while locked and unlocks;
     - the snapshot is unchanged by a later `write`;
     - a failed replace leaves main as it was.
   - **Opus review.**
2. **S4-2 Back up now.**
   - Files: `LocalBridge.java` (`backupLibrary`, parameterised `saveToDownloads` message); `local.js` (Settings section, privacy text, relabelled Save JSON, Overnight step if D1); `build.gradle`, `CHANGELOG.md`, `TESTING.md`; `tests/test_backup_restore.py` (new, fake `RN.backupLibrary`).
   - Harness tests: the button sends counts; the success and failure text; the privacy sentence is shown; locked shows "Save the unreadable file" instead.
3. **S4-3 Restore.** Depends on Task 2b and on R4-2's schema rule.
   - Files: `LocalBridge.java` (`chooseBackup`, `restoreBackup`, `cancelRestore`); `local.js` (`#/restore` screen, `lockedScreen` button, reload); `tests/test_backup_restore.py`.
   - Harness tests:
     - a cancelled picker changes nothing;
     - each refusal message appears and `restoreBackup` is never called;
     - the confirm screen shows both counts;
     - the pre-backup checkbox calls `backupLibrary` first;
     - after a restore the page shows the restored reels;
     - a pending shared link is filed into the restored library and acked once;
     - restore is refused while a run is going;
     - the locked screen offers restore.
   - **Opus review.**
4. **S4-4 (optional) "Files set aside":** list `.bad-*` and `before-restore-*` with sizes, offer "Save to Downloads" and "Delete" (with confirmation). Files: `LocalBridge.java`, `local.js`.

## Device checks (owner; AI ran only cloud tests)
1. Back up a real library. Note its size and the time taken, and open the ZIP in Files.
2. Restore it on the same phone. Check the reel and title counts and open a few notes.
3. Copy the ZIP off the phone, uninstall, reinstall the same signed APK, and restore. Choose it via Drive too. **The library is deleted on uninstall: confirm the copy first.**
4. Share a reel, then restore before opening the library; the reel must appear after the restore.
5. Try a restore while Start is running: it must be refused.
6. Try a backup with less than 100 MB free.
7. Report the Android version used (a different message appears on Android 8 and 9).

## Owner decisions (recommended default)
- **D1** Make the manual Overnight run's step 5 a real backup? **Yes**, and never delete old backups automatically.
- **D2** Pre-backup before a restore? **On by default.**
- **D3** On Android 8 and 9: **warn** that the file is removed on uninstall (rather than build a save-as picker).
- **D4** Accept a bare `reels.json` as a restore source? **No** in v1.
- **D5** Include settings without API keys? **No** in v1.
- **D6** Encrypt with a password? **No**: a lost password is a lost library. Document the privacy risk instead.
- **D7** Build S4-4? **Yes**, after S4-3.

**Opus review:** S4-1 and S4-3, plus every change to `LibraryFile`.
