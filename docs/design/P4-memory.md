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
2. **Scan instead of tree in `valid`/`inspect`**, still returning the String: measured no lower peak on HotSpot. It saves about 40% of the parse time, and the tree as garbage. A strict scanner must give exactly the old verdicts. A scratch prototype of about 100 lines (`Diff.java`, seed 4) disagreed with org.json 20250517 on 46 of 3,000 mutated files (44 it accepted that org.json refused, for example duplicate keys; 2 the other way). On the phone `inspect` runs Android's built-in org.json, a different implementation that was not compared at all. The risk is real and the gain is small.
3. **Targeted (recommended).** Use `scan` only where no text is needed, where the gain is total. Give `VerifyJob` only `media`. Add a clear out-of-memory guard. Document the limit.
4. **Do nothing.** Acceptable for typical libraries: 1,000 reels needed 15 MB in Java and about 25 MB of page heap here.

## The change (option 3; no file format change, no result change)
- **P4-1 `LibraryFile.scan(File, Shape, String schemaKey)`** is a streaming check. It requires: one whole object, nothing after it, no NUL, and `reels` (or `seen`/`reels` for shots) of the right kind. It answers yes **only inside a conservative subset** and "not sure" for everything else. "Not sure" covers: any duplicate key at any level, nesting deeper than 512, any number that is not plainly a finite double, any escape or character it does not fully decode, a BOM, a lone surrogate, and anything else it does not fully understand.
  - **"Not sure" always falls back to `inspect`.** The fallback protects only one direction: a wrong "not sure" costs time, but a wrong "yes" is not caught by anything. The subset exists so that "yes" is only given where both org.json versions are expected to accept.
  - **The tests compare against org.json 20250517, not Android's parser.** On the phone `inspect` runs Android's built-in org.json, a different implementation. A strict-JSON "yes" that Android's parser refuses is therefore possible. One candidate is `1e999` as an object value, which would become a non-finite Double that `JSONObject.put` rejects (**NEEDS VERIFICATION**). Device check 5 covers this.
  - **Schema.** On the S4-3 branch, `inspect` returns `Good(text, shapeOk, schema)`. `LibraryBackup.check` (LibraryBackup.java:314-316 there) and `replaceWith` (LibraryFile.java:456-457 there, `newer(g.schema)`) use that value to refuse a library saved by a NEWER app. So `scan`'s "yes" must also return the raw value of `schemaKey` (`schema_version` for reels), read the same way (a number of any size, and the same `LibraryFile.isNewer` meaning). `check` and `replaceWith` keep **both** newer-schema checks unchanged: the file's own value and the manifest's. Otherwise an older app could install a newer-schema library and later save over it.
  - **Used in:** the staged file in `LibraryBackup.check`, `replaceWith`, and the read-back after "Back up now". `read()` keeps `inspect`, since the page needs the String anyway (D-P4-1).
- **P4-2 `VerifyJob`** extracts only the top-level `media` array: the scanner finds its character range, and `JSONTokener` parses that slice alone. When the scan is not sure, it uses `readJson` as today. Same candidates, same results.
- **P4-3 guard, inside `LibraryFile`.** A guard at the bridge alone is not enough. `LibraryFile` starts with `locked = false` and `trusted = false` (LibraryFile.java:78-80). An `OutOfMemoryError` escaping `read()` would leave it that way. A later `store` would then be allowed by `write()`, which calls `quarantine(main)` (line 228) on an untrusted file. That sets the real library aside and puts the page's empty one in its place.
  - So `LibraryFile.read` and `load` catch `OutOfMemoryError` themselves. They set `locked = true`, `trusted = false` and a new state `TOO_BIG`, and return "". From then on Java refuses every save on its own, whatever the page does, and nothing is renamed, restored or set aside.
  - `TOO_BIG` is kept apart from `UNREADABLE`, so "Start a new library" (`startNew`) is not offered for it. `LocalBridge.load` and `store` also catch the error and report the `libraryInfo` state `too_big`. The page shows "Your library is too big for this phone's memory to open. Nothing was changed." and saves nothing (the `dbLocked` path). The S4 backup streams the file without parsing it, so the backup still works. Whether ART lets the app continue after such an error is NEEDS VERIFICATION. If it does not, the guard falls back to today's crash, which is still safe.
- **P4-4 docs.** TESTING.md and the continuation file record the measured sizes and the device limits once they are measured.

**What it does NOT fix.** The page still holds the text, the parsed reels and the index; `store` still makes two copies; the night page costs the same. The biggest item, the search index, is P2's design: a follow-up could keep term ids instead of strings (a separate task, not P4).

## Failure modes
| Case | Behaviour |
|---|---|
| `scan` wrongly says "not sure" | `inspect` decides, exactly as today (only slower) |
| `scan` wrongly says yes | The one dangerous direction, not caught by the fallback; kept small by the conservative subset, tested against org.json 20250517 in CI and against Android's parser only by device check 5 |
| Backup with a newer `schema_version` | Refused through the scan path exactly as today (the schema value comes from `scan`; both checks stay) |
| Out of memory while reading | `LibraryFile` locks itself (`TOO_BIG`); every later save is refused in Java; nothing renamed or restored; never "damaged" (an `Error` is never turned into "invalid") |
| Out of memory in `VerifyJob` | Same as today (the job ends); with P4-2 much less likely |

## Tests and deliberate breaks
JUnit `LibraryScanTest`: generated libraries of 1,000 and 5,000 reels (Java port of `GEN_JS` or the Node output as a test resource), plus 10,000 seeded mutations (cut, insert one of `\0 } ] , " ' x :`, duplicate key, delete a span, trailing text, deep nesting, BOM, a lone surrogate). For each case: `scan` yes implies `inspect` (org.json 20250517) accepts, and the schema value `scan` returns equals `inspect`'s. Every final verdict (`scan`, then fallback) equals `inspect`. Numbers such as `1e999`, `-0`, `1E400` and 400-digit integers give "not sure". The tests named below are required as well:
- **Newer schema.** A staged backup whose `reels.json` has `schema_version` 99, or a 30-digit number, is refused through the scan path by `LibraryBackup.check` (`NEWER_SCHEMA`) and by `replaceWith`, and nothing is installed.
- **Out of memory.** After an `OutOfMemoryError` thrown at a test seam inside `read()`: `state()` is `TOO_BIG`, `locked()` is true, `write()` returns false, and `reels.json` and `reels.json.bak` are byte-identical with no `.bad-*` file.
- **Verify.** `VerifyJob.pending` and `needDetails` give the same answers with the media-only path.

Breaks to catch: accept duplicate keys; skip the NUL check; accept a trailing comma; remove the fallback; treat an `Error` as invalid; drop the schema value from `scan`; leave `locked` false after an out-of-memory error. Page harness: `libraryInfo` `too_big` shows the message and saves nothing.

## Safe rollout
No kill switch: the fallback is the old code path. Each PR runs the differential on the generated libraries in CI. Device check 2 compares the verdicts on the owner's real library on the phone, without uploading it.

## PR split (stacked on S4-3; each passes `uv run pytest tests/test_phone_app.py tests/test_backup_restore.py` and CI `testReleaseUnitTest`)
1. **P4-1** `scan` and its use in the backup and restore checks. 2. **P4-2** media-only `VerifyJob`. 3. **P4-3** out-of-memory guard and page state. 4. **P4-4** docs (no release).

## Device checks (owner)
1. Run `adb shell getprop dalvik.vm.heapsize` (the large-heap limit) and `dalvik.vm.heapgrowthlimit`, and note both.
2. With your own library: "Back up now" and restore still work, and the counts are the same (P4-1).
3. Measure app memory (`adb shell dumpsys meminfo app.reelshelf`) after opening the library and after one search: Java heap and WebView renderer, with your library size.
4. Optional: import a generated 5,000-reel library on a spare phone, open it, search, back up.
5. Restore verdicts against Android's own org.json (P4-1), on a spare phone or with "save a backup first" on. Restore one real backup: it must restore. Then restore crafted backups with lenient JSON (single quotes, a value `1e999`, a duplicate key), with the manifest hashes made to match: each must give the same verdict as the 1.3.x app before P4.

## Owner decisions (recommended default)
- **D-P4-1** Also use `scan` in `read()` for speed: no (recommended; same peak measured, the risk is not worth 0.3 s at 5,000 reels), or yes.
- **D-P4-2** Do P4 now or after a device heap check: after device checks 1 and 3 (recommended). The measurements show no problem at 1,000 to 5,000 reels on desktop.
- **D-P4-3** Size warning: show "large library" in Settings above 50 MB on disk (recommended, text only), or nothing.

## Risks
- The scanner is new parsing code next to user data. The fallback and the one-direction test contain the risk, and it is used only where the gain is total.
- Desktop numbers can mislead: ART, the Android WebView and real reel text all differ.
- The search index may hit limits before Java does; that is outside P4.
