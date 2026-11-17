# A2: model download integrity (design, not approved)

Base: `origin/ccr-d0c0b070-bdpssy` at f313e2d (Reel Shelf 1.3.11, versionCode 18). Planning only: no code was changed. Network data below was read on 2026-11-17 between 08:05 and 08:10 UTC.

## Problem
The app downloads up to 3.7 GB of AI model and 41 MB of speech model. Today nothing proves the bytes are the right ones. The URLs point at `resolve/main`, which moves: the Qwen file **has already changed twice upstream** (see the data table). A download paused before such a change and resumed after it would glue two different files together, and the app would call the result "Ready". A server that sends no `Content-Length` lets a cut-short file become the final model. The speech model's size is known in code but never compared.

## Verified in code (origin/ccr-d0c0b070-bdpssy)
**What the app downloads.**
- On-phone AI model: three URLs in the page, `MODELS` (local.js:120-130), all `https://huggingface.co/litert-community/.../resolve/main/<file>.litertlm`. Java has its own copy of the Qwen one, `LocalModel.DEFAULT_URL` (LocalModel.java:33-34), used when the page sends no URL (LocalBridge.java:566).
- Speech model: `SpeechModel.URL` = `https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip` (SpeechModel.java:22-23). `SpeechModel.SIZE = 41_205_931L` (SpeechModel.java:24) is only shown to the page (`speechInfo`, LocalBridge.java:763). It is never compared.
- ML Kit text recognition: the model is bundled in the APK (build.gradle:50-52). No download.
- Posters: only a URL string is stored (catalog.js:179, 208). The WebView shows it (`img-src https:` in index.html:7). Nothing is saved to disk. Out of scope.
- PC edition: `whisper_cpp_model()` downloads `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin` (study.py:776-800) to `~/.cache/reel-shelf/` via `.part` then `replace`. No pin, no size, no hash. Ollama pulls go through Ollama itself (model.py:133). faster-whisper downloads through its own library (study.py:755). See "Out of scope".

**Who decides the URL.** The page passes the URL: `phone("downloadModel", m.url, m.file)` (local.js:614 for the night run, 1246 for Settings). Java only checks the prefix `https://huggingface.co/` (LocalBridge.java:567-569). So any file anywhere on huggingface.co can be fetched under any `.litertlm` name.

**Redirects.** `LocalModel.open` follows up to 6 redirects by hand (LocalModel.java:135-155). Each hop must be `https` (line 148), but **any host** is accepted. Hugging Face answers `302` to `us.aws.cdn.hf.co/xet-bridge-us/...` today (observed with `curl -sI`).

**Resume.** `download()` (LocalModel.java:88-127) appends to `<name>.part` with `Range: bytes=N-`. `200` restarts from zero (line 99). `416` with a partial file is treated as "already complete" and renamed to the final name **with no check at all** (lines 94-97). The total is `have + Content-Length` (line 102). The final size check runs only when that total is known: `if (total > 0 && part.length() != total)` (line 125). With chunked transfer the check is skipped.

**Where files land.** AI model: `filesDir/models/<name>.part`, then `finish()` deletes the old final file and renames (LocalModel.java:129-132). Same folder, so the rename is atomic, but the delete before it is not (a crash between them loses the old model; harmless, it was being replaced). Speech: `cacheDir/vosk-model-small-en-us-0.15.zip(.part)` (LocalBridge.java:779), unpacked **straight into** `filesDir/speech/` (SpeechModel.java:37-63), then the zip is deleted in `finally` (line 792). Unpack has a zip-slip guard (line 45) and a 400 MB cap (line 57).

**What is checked today.** Free space before writing, when the total is known: needs `(total - have) + 200 MB` (LocalModel.java:103). Size, only when the total is known. Nothing else: no hash, no magic bytes, no content type.

**How the page learns "ready".** `modelInfo` returns `ready: f.isFile()` and `partial: part.length()` (LocalBridge.java:540-561). `speechInfo` returns `ready` when `speech/<NAME>/am` or `conf` is a folder (SpeechModel.java:31-34). So a speech unpack killed halfway can report "Ready".

**Picking a file by hand.** `pickModel` (LocalBridge.java:609-652) uses `act.pickModelFile` (ACTION_OPEN_DOCUMENT, `*/*`, MainActivity.java:109-120), requires a `.litertlm` name, copies to `<name>.part`, then deletes the old file and renames. No check. A picked file named like a catalog file replaces the downloaded one.

**Cut short, disk full, app killed.** Pause and backgrounding call `stopAll()`, which sets `stop`; the loop throws `InterruptedIOException("paused")` (LocalModel.java:113). The `.part` stays and the page shows "Paused" and "Continue download" (local.js:1197, 1201). A write error (disk full) throws `IOException`; the `.part` stays. A killed app leaves the `.part`; the final file never appears. `deleteModel` removes both (LocalBridge.java:597-605). Note: the speech download does not set `downloading`, so a model and a speech download can run at once and share the one `stop` flag.

## Integrity data (obtained 2026-11-17, public metadata, no login)
Method: `GET https://huggingface.co/api/models/<repo>/revision/main?blobs=true` (commit, per-file `lfs.sha256`, size), cross-checked with `curl -sI <resolve URL>` (`x-repo-commit`, `x-linked-etag`, `x-linked-size`, all equal). History: `GET /api/models/<repo>/commits/main?limit=200`, then `POST /api/models/<repo>/paths-info/<commit>` for each commit.

| Id | Pinned URL (`https://huggingface.co/litert-community/...`) | Bytes | sha256 |
|---|---|---|---|
| qwen | `Qwen2.5-1.5B-Instruct/resolve/60257f9f1d00ca1f24cc5ce3b829b4139be1ca2b/Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm` | 1597922856 | c4a9b7289365ab80fe599b844b77ad253eb3c53fb0e5d963d699146a6f01255e |
| gemma4 | `gemma-4-E2B-it-litert-lm/resolve/2d74ac41a33d7da82f39f7d5720a04c68514a103/gemma-4-E2B-it.litertlm` | 2588147712 | 181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c |
| gemma4e4 | `gemma-4-E4B-it-litert-lm/resolve/f254b5ba6e36f7d89cc7892e268e9877bc20f0a0/gemma-4-E4B-it.litertlm` | 3659530240 | 0b2a8980ce155fd97673d8e820b4d29d9c7d99b8fa6806f425d969b145bd52e0 |
| speech | `https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip` (no revision scheme) | 41205931 | 30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498 |

- The three AI hashes come from Hugging Face metadata, not from a download (1.6 to 3.7 GB). The LFS oid is the sha256 of the file, so a later session can confirm once with a real download: `curl -L -o f <pinned URL> && sha256sum f`. Marked: **from metadata, one real download still NEEDS VERIFICATION**.
- Speech: downloaded into the scratchpad and hashed here. Size equals `SpeechModel.SIZE` and `Content-Length`. MD5 `09ab50ccd62b674cbaa231b825f9c1cb` equals the `md5` that alphacephei publishes in `https://alphacephei.com/vosk/models/model-list.json`. The zip starts with `PK\x03\x04`, holds 20 entries, 70898967 bytes unpacked. Server: `Last-Modified: Tue, 08 Dec 2020`, `ETag "5fcf9e43-274c0ab"`.
- **Upstream history** (why pinning matters). Qwen q8: `2ac49902...` 1598603264 bytes (2025-08-28), then `faa60663...` 1597931520 bytes (2025-11-25), then the current hash since commit `5e6e7a58` (2026-10-11, "Update LlmMetadata for litert-lm 0.18.0"). Gemma 4 E2B: `ab7838cd...` 2583085056 bytes (2026-04-01 to 04-29), current since 2026-05-04. Gemma 4 E4B: `f335f2bf...` 3654467584 bytes (2026-04-01 to 04-24), current since 2026-05-04. The app added these URLs on 2026-11-04 and 2026-11-05 (`git log -S`), after every change, so phones on 1.3.x should hold the current hashes.
- The newest commits (2026-11-10 and 11-11) only touched READMEs; the pinned commits are simply the newest. Any commit since the dates above gives the same bytes.

## Rules
1. **One table, in Java.** New pure-Java `ModelCatalog` (no Android types): `{id, file, url, bytes, sha256}` for the four rows above. Java is where the download is enforced, so the trust anchor must live there; a Java constant is testable with plain JUnit and needs no AssetManager. The page keeps `MODELS` for names, notes and display size only; its `url` field is removed. `LocalModel.DEFAULT_URL` is removed (the catalog replaces it).
2. **Java picks the URL.** `downloadModel(id, url, name)` keeps its signature for compatibility but ignores `url`. It looks `name` up in the catalog. Unknown name: "Only the models listed in Settings can be downloaded. Use 'Pick a model file' for others."
3. **Pinned URLs only.** Every catalog URL on huggingface.co contains `/resolve/<40 hex>/`. Never `/main/`.
4. **Redirect hosts.** Each hop must be `https` and its host must be `huggingface.co`, or end in `.huggingface.co` or `.hf.co`. The speech model allows exactly `alphacephei.com` and no redirect. This adds no host; it only narrows what is accepted today.
5. **Size before hash.** Before writing: the response total (`206`: the total from `Content-Range`; `200`: `Content-Length`) must equal the catalog size, or the answer is refused without touching the `.part`. Free space is checked against `bytes - have + 200 MB` from the catalog, so it works without `Content-Length`. While writing: stop with an error if the file would grow past the catalog size. After: the `.part` must be exactly the catalog size.
6. **Hash while writing.** The loop reads through a `DigestInputStream` (SHA-256), so the file is hashed as it is written. No second pass for a fresh download.
7. **Resume: keep it.** Pause is a real feature (the app stops all work in the background), and losing 2 GB of progress is worse than a short re-read. On resume, the existing `.part` prefix is fed through the same `MessageDigest` once (a read of up to 3.7 GB: see the estimate below), then the download continues. This is safe now because a pinned URL never changes its bytes. A `.part` longer than the catalog size is deleted and the download restarts. `416` no longer means "complete": the `.part` must have the exact size and its hash must match.
8. **Atomic install.** Only when size and hash match: rename `.part` onto the final name (same folder). On mismatch: delete **only our own `.part`**, never the final file, and say "The download was damaged or changed on the way (check failed). Nothing was installed. Tap Download to try again."
9. **Speech model.** The zip gets the same size and hash check. It is then unpacked into `filesDir/speech/.unpack-<stamp>/`, and that folder is renamed to `speech/<NAME>` only after unpack finishes. Leftover `.unpack-*` folders are our own and are removed at the next download. The zip goes to `filesDir/models/` instead of `cacheDir`, so Android cannot clear a half-done resume. `downloadSpeech` sets the shared `downloading` flag, so the two downloads never run at once.
10. **Existing models from 1.3.x.** `ready` keeps its meaning (the file exists), so nothing that works today stops working. A new field `verified`: `"yes"`, `"no"`, `"unknown"`, `"checking"` or `"own"`. The first time the Settings screen shows a model with no result, Java hashes it once in the background on the `work` executor, only while the app is open, and stops on `stopAll()`. The result goes in a sidecar `<file>.check` (`{"sha256","bytes","mtime","result"}`), reused while size and modified time are unchanged. A model that does not match is **never deleted**. Settings shows: "This model file is not the published one. It may be damaged. Download again (2.6 GB) / Keep using it." Notes keep working with it (D1).
11. **Hashing time (estimate, not measured).** SHA-256 in Android's Conscrypt runs at roughly 1 GB/s or more on phones with ARMv8 SHA instructions, about 150 to 300 MB/s without them. Flash reads run at roughly 1 to 2 GB/s (UFS) or 250 to 300 MB/s (eMMC). So 1.6 GB takes about 2 to 10 s and 3.7 GB about 4 to 25 s; worst case on an old phone about one minute. Small next to a 3.7 GB download.
12. **Picked by hand.** Allowed, no hash needed. The copy loop in `pickModel` also reads through a `DigestInputStream` (free, no second pass). If the hash equals a catalog row, `verified: "yes"`; otherwise `"own"`, shown as "Your own file, not verified". A picked file never takes a catalog name unless its hash matches that row; otherwise it is saved as `<name> (own).litertlm` so it cannot pass as the published model.
13. **No new permission, no new host, no key.** `INTERNET` is already there. The User-Agent stays `ReelShelf-Android`.

## Updating the table (release step)
When upstream publishes a better file: read the commit and per-file `lfs.sha256` and size from `/api/models/<repo>/revision/main?blobs=true`; do one real download and `sha256sum`; update the `ModelCatalog` row and the page `MODELS` display size in one PR; add a CHANGELOG line ("Qwen model updated to commit X"). Phones keep their old file: the previous hash moves into that row's `accepted` array, so an earlier good file still shows "yes" and is never pushed to re-download (D3). For Vosk, use `model-list.json` (size and md5) plus a local sha256.

## Failure modes
| Case | Behaviour |
|---|---|
| Upstream changes `main` | Nothing changes for us: the pinned commit still serves the old bytes |
| Truncated download, connection cut | `.part` kept, "Paused" or "The download stopped early. Tap Download to continue." Never installed |
| Server sends no `Content-Length` | Size is taken from the catalog, so a short file is never installed |
| Captive portal sends HTML with `200` | Size differs from the catalog: refused before writing; if it somehow matched, the hash fails |
| One flipped byte, wrong file, mixed resume | Hash fails, our `.part` deleted, clear message, final file untouched |
| Redirect to another host or to `http` | Refused, message names the host; nothing written |
| Disk full | Refused before the request when the catalog size does not fit; a write error keeps the `.part` and says "Phone storage is full" |
| App killed mid-download or mid-unpack | `.part` or `.unpack-*` stays; never shown as "Ready"; resume or clean up next time |
| Existing model does not match | Kept, labelled, re-download offered; never deleted silently |

## Threats
Covered: a changed upstream file (pinning); a truncated or over-long download; a captive portal or proxy error page; a compromised or wrong CDN mirror or a man in the middle with a trusted certificate (hash); a page or script asking Java for an arbitrary URL (catalog lookup). Not covered: a compromised upstream **at the pinned commit before we recorded the hash** (we trust what Hugging Face and alphacephei published on 2026-11-17); a compromised APK; a malicious file the user picks by hand (it is labelled, not blocked); the safety of the model runtime itself.

**Privacy note.** A download tells huggingface.co and its CDN (or alphacephei.com) the phone's IP address, the time, the User-Agent `ReelShelf-Android`, which model and, through the pinned commit, roughly which app version. No account, no cookie, no library data, nothing about reels. A `Range` header shows that a download was resumed. Verifying an existing file is fully offline.

## Tests
**JUnit** (`ModelVerifierTest`, `ModelCatalogTest`; pure Java, local HTTP via `com.sun.net.httpserver` from the JDK, no new dependency): good file installs; one flipped byte refused and `.part` deleted, final file untouched; truncated (stream closed early) keeps `.part`, not installed; longer than expected stopped; no `Content-Length` still checked; `200` with an HTML page refused before writing; redirect to another host refused; redirect to `http` refused; resume `206` with correct `Content-Range` installs; resume where the server answers `200` restarts; `416` with a wrong `.part` deleted and restarted; `.part` longer than catalog deleted; disk-space precheck uses catalog size; unknown name refused; `pickModel` hash match gives `"yes"`, otherwise `"own"` and never a catalog name; sidecar reused while size and mtime hold, recomputed when they change; speech unpack leaves no `speech/<NAME>` when killed mid-unpack.
**Table honesty** (`ModelCatalogTest` plus a Python test): every huggingface.co URL matches `/resolve/[0-9a-f]{40}/` and never contains `/main/`; every sha256 is 64 lowercase hex; every size is positive; every page `MODELS` file has a catalog row and its display size is within 1% of the catalog size; local.js contains no `resolve/main`.
**Page harness** (`tests/test_phone_app.py` stub): states "Checking the model", "Verified", "Not the published file" with both buttons, "Your own file, not verified"; a failed check shows the message and keeps "Download model"; the page no longer sends a URL.

## PR split (each passes `uv run pytest tests/test_phone_app.py` and the CI `testReleaseUnitTest`; versions: next free)
1. **A2-1 catalog and verified download.** `ModelCatalog`, verifier in `LocalModel.download` (rules 1 to 8), redirect host list, page `MODELS` without URLs, table-honesty tests. New downloads only.
2. **A2-2 speech model.** Rule 9: hash, zip in `filesDir`, unpack to a temp folder and rename, shared `downloading` flag.
3. **A2-3 existing and picked models.** Rules 10 and 12: background check, sidecar, `verified` field, page states, re-download offer.
4. **A2-4 (optional, PC).** Pin and hash the whisper.cpp ggml download in `study.py`, same idea, its own data table.

## Device checks (owner; AI ran only cloud tests)
1. Fresh install: download Qwen on Wi-Fi; Settings shows "Ready" and "Verified".
2. Airplane mode at about 40%, then back on, tap Continue: finishes and verifies; time the prefix re-read.
3. Debug build with one catalog hash changed: download fails with the clear message, no final file, `.part` gone.
4. Phone with a 1.3.11 model: update; the check runs once, shows "Verified", and does not run again on the next open.
5. Pick your own `.litertlm`: labelled "Your own file, not verified" and it still writes notes.
6. Speech model: download, then kill the app during unpack; reopen: not "Ready"; download again works.
7. Gemma 4 E4B (3.7 GB) on the slowest phone you have: note how long the one-time check takes.

## Risks
- Hugging Face moves its CDN to a host outside `.hf.co`: downloads fail with a clear host message until a release updates rule 4 (D4).
- The pinned commit is deleted or the repo is renamed: downloads fail until the table is updated. Hugging Face keeps old commits today.
- A wrong row in the table blocks every download of that model: the release step requires one real download.
- The background check reads several GB once: some battery and seconds, only while the app is open.

## Out of scope
PC edition downloads (A2-4 above; Ollama verifies its own layer digests, faster-whisper relies on its library). Model signatures from upstream (none are published). Posters.

## Owner decisions (recommended default)
- **D1 Existing model that fails the check:** keep it and allow use with a warning and a re-download button (recommended), or block notes until re-downloaded.
- **D2 Download that fails the check:** never installed, `.part` deleted (recommended); no "install anyway".
- **D3 Older good hashes:** keep an `accepted` array per row, **empty in A2-1** (no phone should hold a pre-2026-11-04 file), filled only when a later release moves a row to a new commit (recommended). The older upstream hashes, for reference if the owner wants them listed: Qwen `faa60663b333290c1496c499828b21d3e3254a788cacd8cce917ce0f761a2dc9` (1597931520 B) and `2ac49902133f729199bbd23ad6714df32b20585c786f2546d2293cc371f35278` (1598603264 B); E2B `ab7838cdfc8f77e54d8ca45eadceb20452d9f01e4bfade03e5dce27911b27e42` (2583085056 B); E4B `f335f2bfd1b758dc6476db16c0f41854bd6237e2658d604cbe566bcefd00a7bc` (3654467584 B). Whether litert-lm 0.19.0 still loads them is NEEDS VERIFICATION.
- **D4 Redirect hosts:** strict `huggingface.co`, `*.huggingface.co`, `*.hf.co` (recommended), or any `https` host and rely on the hash.
- **D5 Resume:** keep with a prefix re-read (recommended), or drop resume and always start over.
