# Agent guide for reel-watcher (Windows edition)

reel-watcher analyzes a user's saved Instagram reels with local models on a Windows PC.
It is a port of github.com/jakeb144/reel-watcher (Apple Silicon only): MLX became Ollama, mlx-whisper became
faster-whisper, Apple Vision OCR became RapidOCR. Read `README.md` first for behavior, options and the output schema.

## Run (PowerShell)

```powershell
uv sync
uv run pytest                                                   # must pass before and after any change
uv run reel-watcher study --local clip.mp4 --out-root .\out     # no network, no cost (needs Ollama running)
uv run reel-watcher study --input urls.tsv --out-root .\out     # dry run (default)
uv run reel-watcher study --input urls.tsv --out-root .\out --run --limit 3    # free
```

## Rules

- The user wants everything free. The default downloader is yt-dlp (free). Never use `--source apify` (paid)
  or suggest a paid service unless the user explicitly asks. Show the dry run first and start with `--limit 3`.
- If yt-dlp is refused by Instagram, wait and rerun, raise `--sleep`, or update yt-dlp. Never log in or use cookies.
- `APIFY_TOKEN` is read from the environment only. Never write it to a file, a log, a URL or a commit.
- Never log in to Instagram, use browser cookies, or automate the Instagram UI. Reel URLs come from the
  user's official data export (`reel-watcher export`) or a plain URL list.
- Do not commit media, frames, transcripts or study output. No real reel data in tests or examples; use placeholders.
- Keep analysis local. Do not add a hosted-LLM or paid-API dependency.
- Always pass `encoding="utf-8"` when reading or writing text files (Windows defaults to a legacy code page).
- No em dash characters anywhere (a test enforces it in Python sources).

## Code map (`src/reel_watcher/`)

| File | Role |
|---|---|
| `cli.py` | `reel-watcher study|export|advice` dispatcher |
| `study.py` | The pipeline: yt-dlp download (default, free) or Apify (optional, paid), frame sampling, RapidOCR, dedupe, contact-sheet VLM call, faster-whisper, giveaway detection, archive, JSON writing, `main()` |
| `model.py` | Ollama vision model and whisper names (env overridable), RAM detection, `Vision.ask`, `parse_json` |
| `media.py` | ffprobe/ffmpeg helpers, scene cuts, Instagram URL parsing, preflight |
| `ig_export.py` | Instagram data-export (saved_posts JSON/HTML) to URL list |
| `advice_library.py` | Optional renderer: advice library JSON to one static HTML page |
| `library.py` | Reel Shelf SQLite library: items, collections, titles, finds, jobs, free-service quotas |
| `identify.py` | Title clues from text/speech/caption/comments, database checks, AI image guesses |
| `lookups.py` | Free services: AniList, Wikidata, trace.moe, SauceNAO (network faked in tests) |
| `scanner.py` | Folder scanning with duplicate detection |
| `worker.py` | Background engine: reels and screenshots in parallel, resumable |
| `gif.py` | Motivation clips: quote span, ASS captions, GIF/MP4 via ffmpeg |
| `server.py`, `webapp/` | `reel-watcher app`: JSON API + phone UI (plain JS, no build step) |
| `demo.py` | Sample library for `--demo` and UI tests |
| `android/` | Termux setup scripts and the Android APK shell (built by GitHub Actions) |
| `android/app-shell/app/src/main/assets/local/catalog.js` | Watchlist store: open category list (movie, series, K-drama, anime, manga, manhwa, webtoon...), language codes, dedupe, filters, verify API (`Catalog.add`, `Catalog.verify`, `Catalog.toVerify`). Schema notes in its header |
| `.../assets/local/home.js` | The two tabs and top bar (1.3.0): Library (`libraryScreen`, kind chips, status, filter sheet), Inbox (`inboxScreen`: Start, Try 5, Screenshots, Comments, Add, tonight, what needs you), mic (`RN.listen`, Android's own recognizer, no mic permission) |
| `.../assets/local/search.js` | One search for reels, quotes and titles. `Search.parse` turns everyday words into filters without AI (kind, genre, length, language, watched or not, years); `Search.run` applies them (BM25 for titles, `Lib.find` for reels). Lengths come from `runtime`/`episodes` saved by the online check. `Search.fromAi` reads the optional phone AI's JSON |
| `WebLookup.java` (+ `askScreen`/`webAsk` in `local.js`) | Opt-in "Look things up online": only the question goes to Wikipedia's API and DuckDuckGo Instant Answers (no key, not AI); results carry links, and the phone AI cites them as [W1]. JUnit test with a fake network |
| `.../assets/local/watch.js` | Title rows and title page (length, Open in Instagram), add/edit dialog, `Watch.addCandidate` |
| `.../assets/local/verify.js` + `TitleVerifier.java`, `TitleMatch.java`, `VerifyJob.java`, `NightlyCheck.java` | Online check of watchlist titles: TMDB (user's own key in Settings, never hardcoded), Wikidata, AniList, Jikan, MangaDex, then Wikipedia search (read through Wikidata items) when nothing scores `AUTO`; fuzzy matching without AI. No human review (1.3.3): the best match is picked (a close rival loses to the one more sources agree on) and its official title replaces the screenshot's; "verified" needs a second agreeing source or score >= `AUTO`, else "not_found" (retried in 30 days). `Verify.migrate` re-queues old "conflict" entries once (`db.verify_rules`); `VerifyJob.CACHE_VERSION` ignores older cached answers. Shots.process starts the check by itself after new titles. Process runs only with the app open; the nightly JobScheduler check (Wi-Fi + charging + idle) is off by default. Java writes `verify-results.json` only; the page applies it with `Catalog.verify`. Lengths: `TitleVerifier.details` (TMDB details, AniList, Jikan; Wikidata P2047), and `VerifyJob` fills titles checked before once (verdict "details"). JUnit tests in `app/src/test` (fake network; they run with plain javac + junit, no Android SDK) |
| `android/app-shell/app/src/main/assets/local/` | The built-in phone app (no Termux): `notes.js` (notes format, links, exports, export ZIP), `local.js` (screens), library search without AI (BM25, stems, synonyms, typos, related reels, quick notes) in `notes.js`; Instagram's export page opens in Chrome (`LocalBridge.openInstagram`), never inside the app, and the user picks the ZIP in Add (`Notes.readZip`, ZIP64 safe); `app.css` is a copy of `webapp/app.css` (a test keeps them equal) |
| `android/app-shell/.../WorkService.java` | Foreground service with a Stop notification, only while a user-started job runs (page reports jobs via `RN.workUpdate`/`workEnd`; `overnightRun()` in `local.js` chains them) |
| `android/app-shell/.../LocalBridge.java`, `LocalModel.java`, `ShareActivity.java` | `window.RN` bridge (storage file, caption fetch, saving files), on-phone model (LiteRT-LM, download with resume), share target that only saves |

Tests live in `tests/`; they use no network and no models (Ollama, OCR and whisper are faked). `tests/test_app.py` drives the UI in Chromium at phone size.

## Extend

- New field in the verdict: edit `SYNTH_PROMPT` in `study.py`, then the schema block in `README.md`.
- Different model: set `REEL_WATCHER_VLM` to any Ollama vision model tag.
- New input source: add a parser that yields Instagram URLs, write a TSV (`url<TAB>collection`).
- Add a test for every pure function you change (`dedupe_frames`, `parse_giveaway`, `map_tiles`, parsers).
- Do not publish or push anything without the owner's approval.
- Phone app: nothing starts on its own (no alarms or workers besides the opt-in NightlyCheck). A job the user starts may keep running after they leave the app only through `WorkService` (foreground service, progress notification with Stop, ended as soon as no job runs). With no job, `onStop` stops everything.
  Meta AI is used only by the user's own tap (share sheet), never called by the app. The model download host is huggingface.co only.
  Never automate Instagram (no scripted clicks, scrolling or scraping of a signed-in session): the user taps in Chrome themselves. No in-app Instagram login, no cookies, no Termux, no cleartext (Play Protect blocked 1.1.0 for these). Instagram pages are read logged out and paced (`igFetch` in local.js: 4-7 s apart, 429 backoff 2/10/30 min, then stop). Fetches: instagram.com, Instagram picture/video servers (cover OCR `readCoverText`; `ReelVideo.java` frames OCR + Vosk speech via `readReelVideo`, video deleted after), alphacephei.com (Vosk model, `SpeechModel.java`), youtube.com (watch page, youtubei/v1/player, timedtext), huggingface.co.
  Library features must work without AI first; AI is an optional extra.
- `tests/test_phone_app.py` drives the built-in phone app in Chromium with a fake `window.RN`.

## Release (phone app)

- Every change: `versionCode` +1 and a new `versionName` in `android/app-shell/app/build.gradle`, plus a `## <versionName>`
  section in `CHANGELOG.md`. Merging to `ccr-d0c0b070-bdpssy` builds once and publishes release `v<versionName>` and `apk-latest`.
- Updates install over the old app only when signed with the stable key: secrets `ANDROID_KEYSTORE_BASE64`
  (PKCS12, alias `reelshelf`) and `ANDROID_KEYSTORE_PASSWORD`. Never commit the keystore.
- To save Actions minutes, the APK is built only on the install branch; test locally with `uv run pytest tests/test_phone_app.py`.
