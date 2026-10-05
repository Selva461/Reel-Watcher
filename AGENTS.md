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
uv run reel-watcher study --input urls.tsv --out-root .\out --run --limit 3
```

## Rules

- Never spend money without the user's explicit OK. `--run` calls Apify (about $0.002 per reel). Always
  show the dry run and the count first, start with `--limit 3`, keep the per-batch cap.
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
| `study.py` | The pipeline: Apify fetch, frame sampling, RapidOCR, dedupe, contact-sheet VLM call, faster-whisper, giveaway detection, archive, JSON writing, `main()` |
| `model.py` | Ollama vision model and whisper names (env overridable), RAM detection, `Vision.ask`, `parse_json` |
| `media.py` | ffprobe/ffmpeg helpers, scene cuts, Instagram URL parsing, preflight |
| `ig_export.py` | Instagram data-export (saved_posts JSON/HTML) to URL list |
| `advice_library.py` | Optional renderer: advice library JSON to one static HTML page |

Tests live in `tests/`; they use no network and no models (Ollama, OCR and whisper are faked).

## Extend

- New field in the verdict: edit `SYNTH_PROMPT` in `study.py`, then the schema block in `README.md`.
- Different model: set `REEL_WATCHER_VLM` to any Ollama vision model tag.
- New input source: add a parser that yields Instagram URLs, write a TSV (`url<TAB>collection`).
- Add a test for every pure function you change (`dedupe_frames`, `parse_giveaway`, `map_tiles`, parsers).
- Do not publish or push anything without the owner's approval.
