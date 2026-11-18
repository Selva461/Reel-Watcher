# P4: memory of a big library (design, not approved)

Base: `origin/ccr-d0c0b070-bdpssy` at 4de00d1 (Reel Shelf 1.3.11, versionCode 18). Branches read where named: `performance/p3-watchlist-index` (contains P2) and `stabilize/s4-3-restore` (contains S4-1, S4-2, R4-2 and 2b). Planning only: no code was changed. All numbers were measured on 2026-11-18 on the cloud computer (desktop Chromium and HotSpot JDK 21), **never on a phone**.

## Problem
The library is one JSON text (`reels.json`). Java reads it whole and parses it to a tree to decide it is valid. The page receives the whole text, parses it, and builds a search index over it. Section 6 of the continuation file said a 256 MB heap ran out at 60 MB, and that the tree is the cause. This design measures where the memory actually goes before changing anything.

## Verified in code (file:line, what was read)
- **Java read.** `LibraryFile.valid` (LibraryFile.java:194-206) does four things at once: `Files.readAllBytes` (all bytes), `new String(..., UTF_8)` (a second copy), a whole `JSONTokener` tree, then a shape check. It returns the String, which `LocalBridge.load` passes to the page (LocalBridge.java:113-118). It catches `Exception` only, so an `OutOfMemoryError` is not treated as "damaged". That is correct and must stay. On the S4-3 branch the same work is `LibraryFile.inspect` (LibraryFile.java:257-270 there), used by `read`, `replaceWith` (line 452-457) and the backup check.
- **Java save.** `store(String)` gets a whole String from the page, and `write` calls `getBytes` (LibraryFile.java:223), so two copies exist at once.
- **Watchlist check.** `VerifyJob.run` keeps `readJson(reels.json)`, a whole tree, for the entire network-paced run (VerifyJob.java:58-64, 135-138). It only ever reads `db.media` (VerifyJob.java:85, 342, 358).
- **Backup and restore (S4 branch).** Making a backup parses nothing: it hard-links and streams the file (LibraryBackup.java:31 there). "Back up now" then reads the result back with `LibraryBackup.check`, which parses it once and catches `OutOfMemoryError` (LocalBridge.java:416-417 there). A restore parses the staged file in `check` (LocalBridge.java:491), again in `replaceWith`, and the page parses it a third time on reload. These parses run one after another, never at the same time.
- **Night run.** It loads the same page in a hidden WebView (NightRun.java:111-146), so it pays the same page costs. Whether the night route builds the search index: **NEEDS VERIFICATION**.
- **Page.** `loadDb` does `sync("load")`, then `JSON.parse` (local.js:73-87). `saveDb` does `JSON.stringify(db)` (local.js:98). `Notes.index` builds per-reel term maps (notes.js:489 here; 493-501 on P3).
- **Manifest.** `android:largeHeap="true"` (AndroidManifest.xml:25). The real per-app limit depends on the phone (`ActivityManager.getLargeMemoryClass()`): **NEEDS VERIFICATION** (device check 1).

## Measurements (exact method)
**Library.** `GEN_JS` from tests/test_phone_topics.py, unchanged, written by Node as `JSON.stringify({reels, inbox: []})`. That gives 1,000 / 5,000 / 20,000 reels = 4.6 / 23.0 / 91.9 MB on disk, ASCII only, about 4.8 KB per reel. A second copy has one "✓" added per caption (non-Latin-1, as emoji or accents would be). Real reels may be bigger (transcripts up to 40,000 characters) or smaller. No real data was used.

**Java** (scratch `Parse.java`, org.json **20250517 from the Gradle cache**: the JUnit test dependency, not Android's built-in org.json, which is a different implementation). Smallest `-Xmx` at which each mode completes, by binary search with `-XX:+UseSerialGC`, HotSpot JDK 21.0.12:
| Mode | 1,000 | 5,000 | 20,000 | 5,000 non-ASCII | 20,000 non-ASCII |
|---|---|---|---|---|---|
| `tree` = today's `valid` (bytes, String, tree; String kept) | 15 MB | 71 MB | 277 MB | 173 MB | 689 MB |
| `verify` = `VerifyJob.readJson` (tree kept) | 15 | 71 | 277 | 173 | 689 |
| `stream` = streaming check, no tree, then bytes and String | 15 | 71 | 277 | 173 | 689 |
| `scan` = streaming check only, no String | 4 | 4 | 4 | 4 | 4 |
Time for one parse at 20,000 ASCII (one run each): `tree` 3.5 s, `stream` 2.0 s, `scan` 1.9 s. Retained after `System.gc()` at 20,000 ASCII: String 94 MB, `verify` tree 156 MB.

**Finding.** Removing the tree did **not** lower the minimum heap at all. On HotSpot the peak is the file bytes plus the decoded String, both alive at once as large arrays in the old generation. The non-ASCII String takes 2 bytes per character. Only a path that never makes a String (`scan`) drops to a constant. ART's collector and string compression differ from HotSpot, so the phone's numbers will differ: **NEEDS VERIFICATION**.

**Page** (scratch `measure_page.py`: the real page and `FAKE_RN`, desktop Chromium from the test setup; heap is CDP `Runtime.getHeapUsage`. "Kept" is measured after `HeapProfiler.collectGarbage` and includes the library string that the harness holds, about 1x the file):
| Phase (default branch / P3 branch) | 1,000 | 5,000 | 20,000 |
|---|---|---|---|
| text string held | 6.9 MB | 25 MB | 94 MB |
| `loadDb` time; added and kept | 10 ms; +4.8 MB | 43 ms; +24 MB | 119 ms; +96 MB |
| `Notes.index` time, default | 366 ms | 1,638 ms | 6,449 ms |
| kept after index (reels plus index), default / P3 | +21 / +17 MB | +100 / +82 MB | +398 / +326 MB |
| `saveDb` transient (one more full string) | +4.6 MB | +23 MB | +92 MB |
| library screen; one search on P3 | 20 ms; 15 ms | 24 ms; 34 ms | 36 ms; 100 ms |
Parsed reels cost about 1x the file. **The search index is the biggest consumer in the whole app**: about 2.5x the file on P3 and 3.3x on the default branch. The generated vocabulary of 40,000 words may make it larger than English text would.

## Options
1. **Stream the whole load** (chunked text to the page, an incremental parse): changes the bridge and the page model. Large risk for a gain at sizes nobody is known to have.
2. **Scan instead of tree in `valid`/`inspect`**, still returning the String: measured no lower peak on HotSpot. It saves about 40% of the parse time, and the tree as garbage. A strict scanner must give exactly the old verdicts. A scratch prototype of about 100 lines (`Diff.java`, seed 4) disagreed with org.json on 46 of 3,000 mutated files (44 it accepted that org.json refused, for example duplicate keys; 2 the other way). The risk is real and the gain is small.
3. **Targeted (recommended).** Use `scan` only where no text is needed, where the gain is total. Give `VerifyJob` only `media`. Add a clear out-of-memory guard. Document the limit.
4. **Do nothing.** Acceptable for typical libraries: 1,000 reels needed 15 MB in Java and about 25 MB of page heap here.

## The change (option 3; no file format change, no result change)
- **P4-1 `LibraryFile.scan(File, Shape)`** is a streaming check: whole object, nothing after it, no NUL, strict JSON, duplicate keys refused at every level, depth limit 512, `reels` (or `seen`/`reels` for shots) of the right kind. It answers yes, or "not sure". **"Not sure" always falls back to `inspect`**, so a verdict changes only if `scan` says yes where `inspect` would say no. The tests forbid that. Used in: the staged file in `LibraryBackup.check`, `replaceWith`, and the read-back after "Back up now". `read()` keeps `inspect`, since the page needs the String anyway (D-P4-1).
- **P4-2 `VerifyJob`** extracts only the top-level `media` array: the scanner finds its character range, and `JSONTokener` parses that slice alone. When the scan is not sure, it uses `readJson` as today. Same candidates, same results.
- **P4-3 guard.** `LocalBridge.load` and `store` catch `OutOfMemoryError`. They return "" with a new `libraryInfo` state `too_big`, and **never touch, rename or set aside any file**. The page shows "Your library is too big for this phone's memory to open. Nothing was changed." and saves nothing (the `dbLocked` path). The S4 backup streams the file without parsing it, so the backup still works. Whether ART lets the app continue after such an error is NEEDS VERIFICATION. If it does not, the guard falls back to today's crash, which is still safe.
- **P4-4 docs.** TESTING.md and the continuation file record the measured sizes and the device limits once they are measured.

**What it does NOT fix.** The page still holds the text, the parsed reels and the index; `store` still makes two copies; the night page costs the same. The biggest item, the search index, is P2's design: a follow-up could keep term ids instead of strings (a separate task, not P4).

## Failure modes
| Case | Behaviour |
|---|---|
| `scan` wrongly says "not sure" | `inspect` decides, exactly as today (only slower) |
| `scan` wrongly says yes | Forbidden by the differential test; that is the one dangerous direction |
| Out of memory while reading | Nothing renamed or restored; state `too_big`; never "damaged" (an `Error` is never turned into "invalid") |
| Out of memory in `VerifyJob` | Same as today (the job ends); with P4-2 much less likely |

## Tests and deliberate breaks
JUnit `LibraryScanTest`: generated libraries of 1,000 and 5,000 reels (Java port of `GEN_JS` or the Node output as a test resource), plus 10,000 seeded mutations (cut, insert one of `\0 } ] , " ' x :`, duplicate key, delete a span, trailing text, deep nesting, BOM, a lone surrogate). For each case: `scan` yes implies `inspect` accepts. Every final verdict (`scan`, then fallback) equals `inspect`. `VerifyJob.pending` and `needDetails` give the same answers with the media-only path. An `OutOfMemoryError` thrown by a test seam in `load` leaves every file byte-identical. Breaks to catch: accept duplicate keys; skip the NUL check; accept a trailing comma; remove the fallback; treat an `Error` as invalid. Page harness: `libraryInfo` `too_big` shows the message and saves nothing.

## Safe rollout
No kill switch: the fallback is the old code path. Each PR runs the differential on the generated libraries in CI. Device check 2 compares the verdicts on the owner's real library on the phone, without uploading it.

## PR split (stacked on S4-3; each passes `uv run pytest tests/test_phone_app.py tests/test_backup_restore.py` and CI `testReleaseUnitTest`)
1. **P4-1** `scan` and its use in the backup and restore checks. 2. **P4-2** media-only `VerifyJob`. 3. **P4-3** out-of-memory guard and page state. 4. **P4-4** docs (no release).

## Device checks (owner)
1. Run `adb shell getprop dalvik.vm.heapsize` (the large-heap limit) and `dalvik.vm.heapgrowthlimit`, and note both.
2. With your own library: "Back up now" and restore still work, and the counts are the same (P4-1).
3. Measure app memory (`adb shell dumpsys meminfo app.reelshelf`) after opening the library and after one search: Java heap and WebView renderer, with your library size.
4. Optional: import a generated 5,000-reel library on a spare phone, open it, search, back up.

## Owner decisions (recommended default)
- **D-P4-1** Also use `scan` in `read()` for speed: no (recommended; same peak measured, the risk is not worth 0.3 s at 5,000 reels), or yes.
- **D-P4-2** Do P4 now or after a device heap check: after device checks 1 and 3 (recommended). The measurements show no problem at 1,000 to 5,000 reels on desktop.
- **D-P4-3** Size warning: show "large library" in Settings above 50 MB on disk (recommended, text only), or nothing.

## Risks
- The scanner is new parsing code next to user data. The fallback and the one-direction test contain the risk, and it is used only where the gain is total.
- Desktop numbers can mislead: ART, the Android WebView and real reel text all differ.
- The search index may hit limits before Java does; that is outside P4.
