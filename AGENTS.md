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

Tests live in `tests/`; they use no network and no models (Ollama, OCR and whisper are faked). `tests/test_app.py` drives the UI in Chromium at phone size.

## Extend

- New field in the verdict: edit `SYNTH_PROMPT` in `study.py`, then the schema block in `README.md`.
- Different model: set `REEL_WATCHER_VLM` to any Ollama vision model tag.
- New input source: add a parser that yields Instagram URLs, write a TSV (`url<TAB>collection`).
- Add a test for every pure function you change (`dedupe_frames`, `parse_giveaway`, `map_tiles`, parsers).
- Do not publish or push anything without the owner's approval.
