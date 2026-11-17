# 5a + 5b: a strict temp-file sweep, and removing shared videos after success (design, not approved)

Base: `origin/ccr-d0c0b070-bdpssy` (default, 1.3.11) plus Task 4 on `origin/stabilize/task-4-background-media-copy` at 8e3c275 (PR #37, **not merged**). "T4" below means that branch. `local.js` is identical on both; `LocalBridge.java` differs only at T4:980-984. Planning only: nothing was changed.

## Problem
- Shared pictures and videos are copied into `filesDir/shot-inbox` and `filesDir/video-inbox` and are never removed. A shared video stays for ever, even after its reel has notes.
- Temporary files survive a kill or force-stop: Task 4's `share-staging/copy-*.part`, the cache copies `reel-video*.mp4`, `reel-media/`, `reels.json.tmp`. Most are replaced or removed on the next use, but not all, and nothing reports their size.
- The owner's Task 1 decision, as recorded in PROJECT_CONTINUATION.md:161 (the section says "verbatim in spirit", so this is a paraphrase, not a quote of the owner): "delete shared videos only after successful extraction and saving (this is Task 5b: not yet implemented)". Section 7 calls it "owner decision D2 recorded". **I found no other record of the exact wording.** What "successful extraction" and "saving" mean is not defined anywhere: see D-5b-1.

## Inventory (what the app writes, verified on T4)
Kinds: **U** user data (never auto-delete), **R** re-creatable (models), **T** our own temporary data, **S** system-owned (never touch).

| Path | Created by | Read by | Removed today by | Kind |
|---|---|---|---|---|
| `files/reels.json`, `shots.json` | `LibraryFile.write` (LibraryFile.java:214-246 default) | `read()` 154-191, VerifyJob.java:136-138 | never | U |
| `files/*.json.bak` | `move(main,bak)` :227 | `read()` :163 | `dropBackup` :319-321 (Delete all) | U |
| `files/*.json.bad-STAMP[-n]` | `quarantine` :271-277 | nobody (S4-4 lists) | never | U |
| `files/*.json.before-restore-*` | S4 `replaceWith` (designed) | nobody | never | U |
| `files/*.json.tmp` | `write` :249-259 | nobody | `write` :236 on failure; truncated by the next save | T |
| `files/verify-results.json` (+`.tmp`) | VerifyJob.java:29, 67-73 | `take` :104 | rename; `.tmp` overwritten next time | T (KB) |
| `files/shot-inbox/shot_<24hex>.{jpg,png,webp}` | MediaCopy.java:181-183 via SharedItems.java:78-86 | `listIn` ScreenshotReader.java:213-227, `read`/`thumb` :301,377, review screen shots.js:238-244 | never | **U** |
| `files/video-inbox/video_<24hex>.mp4` | same, `video_` prefix | `listVideos` :209, `scanVideos` local.js:382-397, `readLocalVideo` LocalBridge.java:873-887 | never | **U** |
| legacy `shot_<ms>_<n>.*`, `video_<ms>_<n>.mp4` | 1.3.11 and older (default ScreenshotReader `addPictures`/`addVideos`, removed by T4) | same | never | U (may be half-written: old code wrote straight into the inbox) |
| `files/share-staging/copy-*.part` | MediaCopy.java:143 | nobody | MediaCopy :193 (finally); `MediaBatch.removeLeftovers` :165, 237-241 at the next batch, under the lock | T |
| `files/models/*.litertlm`, `*.litertlm.part` | LocalModel.java:50, 88-131; `pickModel` LocalBridge.java:621-649 | `generate`; `modelInfo` :540-561 shows `partial` | `deleteModel` :597-605 (user button) | R (`.part` is a resumable download) |
| `files/speech/vosk-model-small-en-us-0.15/` | SpeechModel.java:27-58 | `ReelVideo.vosk` | `deleteSpeech` LocalBridge.java:799-802 | R |
| `cache/vosk-...zip`, `.zip.part` | `downloadSpeech` :779-781 | `unpack` | zip :792; `.part` kept on pause to resume | R/T |
| `cache/reel-video.mp4` (<= 60 MB, ReelVideo.java:39) | ReelVideo.java:52-57 | `analyse` | finally :57 | T |
| `cache/reel-video-local.mp4` (<= 500 MB) | ReelVideo.java:67-83 | `analyse` | finally :83 | T |
| `cache/reel-media/frame0-3.jpg`, `sound.wav` (about 1 MB) | `saveMedia` ReelVideo.java:196-247 | `generate` LocalBridge.java:664-672 | `clearMedia` :678, and at the next `saveMedia` | T |
| `cache/` LiteRT engine files | LocalModel.java:234-238 (library-chosen names) | the engine | the engine | S |
| WebView data (`app_webview/`, `cache/WebView/`), ML Kit | the system | the system | the system | S |
| `external/Download/ReelShelf/*` (Android 8-9 only) | `saveToDownloads`/`saveFile` LocalBridge.java:232-240, 356-359 | the user | never (uninstall) | U |
| `files/backup-work/`, `files/restore-staging/*.part` | S4-2/S4-3 (designed; S4-1 `LibraryBackup.check`/`clear` on `stabilize/s4-1-backup-core` take the folder as a parameter) | S4 | S4 clears them after each use | T |

**SharedPreferences `reelshelf`** (LocalBridge.java:76): `shared_queue` (:39) holds **text only** `{id,text,at}` (SharedQueue.java `append`). **Shared pictures and videos never enter the queue**: ShareActivity sends them to `MediaBatch` (ShareActivity.java:66-67, 120-130) and they are found later by listing the inbox. `shot_folders`/`video_folders` (ScreenshotReader.java:41-43) hold `content://` tree grants, not app files. `local_settings.modelFile` names a file in `models/`. **References to inbox files live only in the library:** `reel.file` (local.js:390), `shots.json` `seen[key]` (shots.js:139,148), and `source.ref` of watchlist, quotes and products (shots.js:143-146, catalog.js:157).

**An unreferenced inbox file is not garbage.** A video in `video-inbox` without a reel is *pending*: `scanVideos` turns it into a reel at the next Start, nightly run or folder add (local.js:521, 619; home.js:341). A picture not yet in `seen` is pending for the next Process.

**Existing bug found:** deleting a reel (`#del`, local.js:868) leaves its `video-inbox` file, so the next `scanVideos` adds it back as a new reel. 5b fixes this only for released videos; see D-5b-6.

## Originals are never touched (verified)
- The manifest asks for no storage or media permission (no `READ_MEDIA_*`, `READ/WRITE_EXTERNAL_STORAGE`, `MANAGE_*` on T4).
- A share is read through `openAssetFileDescriptor(uri, "r")` (SharedItems.java:92-97) and written only into `filesDir` (MediaCopy.java:143, 181-183). No code calls `ContentResolver.delete`, `openOutputStream` or a delete request on a shared URI. The only `cr.delete` deletes the app's own half-written Downloads entry (LocalBridge.java:227).
- So every inbox file is **an app-private copy; the original stays where it was** (gallery, Instagram's Download folder). **But the copy can be the last copy** if the user deleted the original, or shared from an app that keeps only a temporary file. Removing it cannot be undone.

## 5a: the sweep (allowlist only)
A file is deleted only if **every** rule holds. Anything else is left and counted.
1. **Named place.** It is directly inside one of these folders (no recursion), and its name matches exactly:

| Folder | Name pattern | Min age | Extra guard |
|---|---|---|---|
| `files/share-staging/` | `copy-[0-9]+\.part` | none | only while holding `MediaBatch.ONE_AT_A_TIME` (`tryLock`, no wait; busy means skip) |
| `cache/` | `reel-video\.mp4`, `reel-video-local\.mp4` | 6 h | no `readReelVideo`/`readLocalVideo` in flight (a new static `ReelVideo.BUSY` counter) |
| `cache/reel-media/` | `frame[0-3]\.jpg`, `sound\.wav` | 6 h | same counter, and no `generate` with `media` in flight |
| `files/` | `reels\.json\.tmp`, `shots\.json\.tmp` | 1 h | only through a new synchronized `LibraryFile.dropTmp()`: state OK and not locked |
| `files/backup-work/`, `files/restore-staging/` | S4's own names (`reels.json`, `shots.json`, `manifest.json`, each optionally `.part`) | 24 h | only after S4 merges; not while S4's backup or restore is running |

2. **A regular file, not a link.** `Files.readAttributes(p, BasicFileAttributes.class, NOFOLLOW_LINKS)`: `isRegularFile()` and not `isSymbolicLink()`. A folder whose own path is a symlink is not entered.
3. **Old enough by its own clock.** `age = now - mtime`. A future mtime (the clock went backwards) gives a negative age: leave it.
4. **Unchanged since it was listed.** Just before deleting, stat it again (no follow); size and mtime must be the same. A file that appears after the listing is not in the list.
5. **Bounded.** At most 2,000 entries are read per folder (`DirectoryStream`, lazily); the rest wait for the next run. Any `IOException` or `SecurityException` on a folder: leave that whole folder.

**Never touched, by construction (not by a deny-list):** `reels.json`, `shots.json`, `.bak`, `.bad-*`, `before-restore-*`, `verify-results.json*`, `models/` (including `.part`: a resumable download that Settings shows), `speech/`, the vosk `.zip.part`, both inboxes (pending or referenced), legacy inbox names, Downloads, WebView and LiteRT files, and any unknown name.

**When and where.**
- Once per process, from `MainActivity.onCreate`, on its own single background thread, 20 s after start (after the page has loaded the library).
- It is skipped when `WorkService.isRunning()` or, once 2b is merged, `WorkService.nightActive()`. Not from the nightly page, not from `ShareActivity`.
- `MediaBatch` keeps its own cleanup at each batch (MediaBatch.java:165).
- On any doubt, it leaves the file.

**What is recorded.** `Log.i` with counts only (no file names). Prefs `last_sweep` = `{at, files, bytes, left_unknown}` for U1. No toast.

**Pure design (JUnit, like `MediaCopy`).**
- `TempSweep.plan(List<Entry> listed, long now, Busy busy)` returns, for each entry, `DELETE` or `KEEP(reason)`.
- `Entry` = `{folder, name, regular, symlink, mtime, size}`. `Busy` holds `stagingLocked`, `videoReads`, `libraryOk`, `s4Running`.
- The rules are a fixed table of `{folder, regex, minAgeMs, guard}`.
- `TempSweeper.run(Context, Clock)` is the thin Android part: it lists, re-stats, deletes and records the result.

## 5b: removing a shared video after success
**A video is released only when all of these hold. The page decides; Java checks again.**
1. `r.file` is a `file://` key whose canonical parent is `video-inbox` and whose name matches `video_[0-9a-f]{24}\.mp4` or the legacy `video_[0-9]+_[0-9]+\.mp4`. Videos in folders the user picked (`content://`) are **never** touched.
2. **Extraction is saved:** `r.video_tried > 0`, `r.content` matches `^video`, and `r.seconds > 0` or `r.onscreen` or `r.transcript`. `readFileVideo` sets these only when `readLocalVideo` resolved (local.js:400-408).
3. **Notes are saved:** `r.notes` is present and `r.status === "done"`. Under A1 (`stabilize/a1-retry-cap`, notes.js:200-204, local.js:601-602) that means no `tries`. A `failed` or parked reel (`tries >= RETRY_CAP`) **keeps its video**: the video is the retry's material.
4. **Speech was there:** a new additive field `r.video_speech = !!v.speechModel` is set in `readFileVideo`. If the video was read without the speech model, the video is kept so that "Read this reel properly" can add the spoken words later (D-5b-3).
5. **Delay:** `now - r.notes_at >= 7 days`, and `notes_at` is not in the future (D-5b-2).
6. Not `r.keep_video`, and the setting `removeSharedVideos` is on.
7. **The pass runs only on a freshly loaded library** (after `loadDb`, idle), with no `run`, `night`, `Verify.job` or `Shots` job, and only in the visible app. Anything it sees was therefore saved to disk.

**Why notes made without AI still count.** Once `video_tried` is set, a later AI pass never reads the video again. It uses the saved `onscreen`/`transcript` (local.js:536). The key frames exist only within the run that read the video (local.js:408, 502; LocalBridge.java:664-678). The video is needed again only by "Read this reel properly" (`#deep`, local.js:861) and by comments added to a reel whose notes were made without AI (local.js:726).

**Order (flag first, then file).**
- The page sets `r.video_released_at = now` and saves.
- Only if `store` was accepted does it call the new `RN.releaseSharedVideos(id, keysJson)`, on the `ocr` executor: the same queue as `readLocalVideo`, so it can never cut a read short.
- Java checks rule 1 again. It holds `MediaBatch.ONE_AT_A_TIME` (`tryLock`; if busy, nothing is done this time), so a share of the same content cannot be told "already there" for a file that is going away. It refuses links and non-regular files, deletes, and answers `{deleted, bytes, missing}`.
- A crash in between leaves the flag set and the file present. The next pass deletes it, unless the file is **newer than** `video_released_at`: the user shared it again, so the flag is cleared and the file is kept.

**What the user sees.**
- Settings, a switch that is **on** by default: "Remove shared videos 7 days after their notes are written. Only Reel Shelf's own copy is removed; your gallery is not touched. Videos from folders you picked are never removed."
- Reel page, before removal: "Shared video kept until 24 Nov. [Keep this video]".
- Reel page, after removal: "The shared video was removed on 24 Nov to save space. The notes stay. To read it again, share the video again." `#deep` and the comments re-read no longer reset `video_tried` for a released reel; they say this instead, so A1 never counts a missing file as a failure.
- After a pass, one toast: "Freed 340 MB: 12 shared videos whose notes are written."

**Is this a destructive user-data operation? Yes.** The owner approved the principle in Task 1, but CLAUDE.md ("Never silently delete user data") and section 12 ("Owner approval is always required for: destructive user-data operations") require the **exact rules above** (delay, default on, what counts as success) to be approved before 5b is merged. It is a publishing PR, so the owner merges it anyway. S4 does **not** protect videos: backups hold no media. The dependency on S4 is about order: a user can back up the notes before the first build that removes anything.

**Pictures (`shot-inbox`) are not in 5b.** They feed the review screen (shots.js:230-256), Google Lens and the watchlist's screenshot sources, and the owner's decision names only videos (D-5b-5).

## Tests
**JUnit `TempSweepTest`:**
- each table row deletes a matching old file;
- a wrong name, a wrong folder or a sub-folder are kept;
- too young is kept, and exactly the minimum age is deleted;
- a future mtime is kept;
- a symlink to an old file, and a symlinked folder, are kept and the target is not deleted;
- staging locked keeps all `.part` files; a video read in flight keeps the cache files;
- a library not OK or locked keeps `.tmp`;
- a file whose size or mtime changed between listing and delete is kept; a file created after the listing is untouched;
- a folder of 50,000 files reads 2,000 and finishes quickly;
- an unreadable folder keeps everything;
- `reels.json`, `.bak`, `.bad-x`, `before-restore-x`, `models/x.part` and an unknown file are never deleted, even when old.

**JUnit `MediaBatchTest`:** the sweep's `tryLock` does not wait, and a running batch is not disturbed.

**JUnit `SharedVideoReleaseTest`** (the Java check):
- a key outside `video-inbox`, `../` in a key, a `content://` key, a symlink or a wrong pattern are refused;
- the legacy name is accepted;
- a busy lock deletes nothing;
- a missing file is reported as `missing`.

**Page harness `tests/test_shared_video_release.py`** (fake `RN`, overridden `Date.now`):
- a done reel 8 days old is released and a 6-day-old one is not;
- failed, parked, `tries=1`, without notes, `video_speech=false`, `keep_video`, switch off, and a `content://` file are all kept;
- a stale-refused store means `releaseSharedVideos` is never called;
- the flag is set before the call;
- a re-shared newer file clears the flag;
- `#deep` on a released reel does not reset `video_tried` and does not count as a failure;
- no pass runs during a run or night;
- the toast and the reel-page texts.
- The R4 round-trip keeps `video_released_at`, `video_speech` and `keep_video`.

## PR split (versions: next free at merge time)
1. **5a-1** (needs #37 merged): `TempSweep.java`, `TempSweeper.java`, `TempSweepTest.java`; `MediaBatch` (package `trySweepStaging`); `ReelVideo.BUSY`; `LibraryFile.dropTmp`; `MainActivity` start hook; CHANGELOG and TESTING. Rows for S4 folders are added in S4-2/S4-3 or after them. **Opus review.**
2. **5b-1** (needs 5a-1, S4-2 merged, A1-1 merged, owner approval of D-5b-1..4): `LocalBridge.releaseSharedVideos`, `SharedVideoReleaseTest`; `local.js` (the pass, the fields, the reel-page texts, the `#deep`/comments guard, the Settings switch); `tests/test_shared_video_release.py`. **Opus review**, owner merges.
3. Optional **U1** later: a Storage screen that reads `last_sweep` and the inbox sizes.

## Device checks (owner)
- F1: force-stop during a large video share, reopen the app after 20 s: `share-staging` is empty.
- F2: kill during "Read this reel properly" on a long video, reopen 6 h later: the cache copy is gone.
- F3: with the date set 8 days ahead, a done shared reel loses its video, the gallery copy still plays, and the notes stay.
- F4: a video from a picked folder is never removed.
- F5: re-share a released video: it is kept, and Read properly works.

## Storage (order of magnitude)
- Temporary leftovers are bounded and small: one `.part` of at most 500 MB, at most 560 MB of cache copies, about 1 MB of `reel-media`, and one `.tmp` per library (30-60 MB at 10,000 reels).
- The inboxes are not bounded: up to 200 videos of 500 MB and 2,000 pictures of 30 MB **per share**. Realistically 5-40 MB per reel video, so 100 shared reels take 0.5-4 GB, and 0.3-3 MB per screenshot.
- Recommendation: 5a deletes only temporary data, silently. 5b removes only what the rules allow, and says so. A U1 "Storage" screen should *show* the inboxes, failed and parked videos, and `models/*.part`, with sizes and buttons the user chooses to press, instead of growing the automatic rules.

## Risks
- A wrong rule deletes the last copy of a video: rules 1-7, the 7-day delay, the switch and Java's second check.
- A clock jump forward makes leftovers look old: the locks and busy counters are the main guard; age is the second guard.
- `ReelVideo.BUSY` is process-wide, but two bridges (app and Headless) share one cache file name today. That is an existing race that 2b prevents; do not rely on it elsewhere.
- Legacy half-written inbox files from 1.3.11 and older stay; this design cannot tell them from good ones.

## Owner decisions (recommended default first)
- **D-5b-1 Success** = extraction saved and notes saved (any author), status done, no A1 failure. Alternatives: only AI or Meta notes; or ask the user per video.
- **D-5b-2 Delay** = 7 days after `notes_at`, then delete. Alternatives: at once; 30 days; a trash folder with Undo.
- **D-5b-3** Keep videos that were read without the speech model. Alternative: ignore speech.
- **D-5b-4** The switch is on by default (matches the Task 1 decision). Alternative: off until the user turns it on.
- **D-5b-5** Pictures are never removed automatically. Alternative: remove a picture after it has been read and reviewed.
- **D-5b-6** Fix the "deleted reel comes back" bug by asking "Also remove its shared video?" in `#del`. Alternative: leave the bug for later.
- **D-5a-1** Include `reels.json.tmp`/`shots.json.tmp` in the sweep. Alternative: leave them (the next save overwrites them).
