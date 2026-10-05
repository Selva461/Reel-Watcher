# reel-watcher (Windows edition)

A Windows port of [jakeb144/reel-watcher](https://github.com/jakeb144/reel-watcher) by Jacob Bruce
([Instagram](https://www.instagram.com/itsjakebruce/)). The original runs only on Apple Silicon Macs (MLX + Apple Vision);
this version swaps those parts for tools that run on a normal Windows 10/11 PC:

| Job | Original (Mac) | This version (Windows) |
|---|---|---|
| Vision model | MLX (`mlx-vlm`) | [Ollama](https://ollama.com) running locally |
| Speech to text | `mlx-whisper` | `faster-whisper` (CPU by default, NVIDIA GPU optional) |
| On-screen text (OCR) | Apple Vision | RapidOCR (ONNX, CPU) |

Everything else (Apify download, frame sampling, contact sheet, giveaway detection, output JSON) is the same.

You save reels on Instagram and never go back to them. reel-watcher has an AI model on your own PC watch them
for you and write down what each one is: the hook, the format, the on-screen text, the transcript, the editing
tricks, any "comment WORD and I'll send you X" giveaway, and a one-line verdict on why it works. You end up with
one searchable JSON file per reel. Everything except the media download runs on your machine.

## What you need

- Windows 10 or 11, 64-bit.
- RAM decides the model. `--model-size auto` (default) picks `small` below 32 GB and `large` otherwise.

  | PC RAM | Setting | Vision model (Ollama) | Whisper | First download |
  |---|---|---|---|---|
  | 16 GB | `small` | `qwen2.5vl:7b` | `small` | about 7 GB |
  | 32 GB or more | `large` | `qwen3-vl:30b` | `large-v3-turbo` | about 21 GB |

  A GPU is not required, but an NVIDIA card with 8 GB+ VRAM makes Ollama much faster (Ollama uses it automatically).
  On CPU only, expect a few minutes per reel. Force a size with `--model-size small|large`, or pick any Ollama
  vision model with `--model <tag>` (e.g. `--model llava:7b`).
- Free disk: about 10 GB (small) or 25 GB (large).
- Four free tools: Git, uv (Python manager), FFmpeg, Ollama. `setup.ps1` installs them for you.

## Step-by-step: run it on your PC

Open **PowerShell** (Start menu, type "PowerShell", press Enter) and run these one block at a time.

**1. Get the code**

```powershell
winget install --id Git.Git -e        # skip if you already have git
# close and reopen PowerShell after installing git, then:
cd $HOME
git clone https://github.com/selva461/Reel-Watcher.git
cd Reel-Watcher
git checkout ccr-d0c0b070-bdpssy      # the branch with the Windows version (until it is merged)
```

(No git? On GitHub click Code > Download ZIP, unzip it, and `cd` into the folder.)

**2. Install everything (one time)**

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

This installs uv, FFmpeg and Ollama with `winget` if missing, installs the Python packages (`uv sync`), runs
the tests, and downloads the vision model. Close and reopen PowerShell afterwards so the new commands are on PATH,
then `cd $HOME\Reel-Watcher` again. Make sure Ollama is running (llama icon in the system tray; start "Ollama"
from the Start menu if not).

Prefer to do it by hand? `winget install astral-sh.uv`, `winget install Gyan.FFmpeg`, `winget install Ollama.Ollama`,
reopen PowerShell, then `uv sync` and `ollama pull qwen2.5vl:7b`.

**3. Try it on any video you own (free, no internet needed after setup)**

```powershell
uv run reel-watcher study --local "C:\Users\$env:USERNAME\Videos\some-clip.mp4" --out-root .\out
notepad .\out\study\some-clip.json
```

**4. Get the list of your saved reels** (see "Getting your saved reels" below), then:

```powershell
uv run reel-watcher export "C:\path\to\saved_posts.json" -o urls.tsv
```

**5. Download and analyze them via Apify (paid, about $0.002 per reel)**

Create an account at [apify.com](https://apify.com), copy your API token from Settings > API & Integrations.
Set it for the current PowerShell window only (do not put it in a file in this folder):

```powershell
$env:APIFY_TOKEN = "paste-your-token-here"
uv run reel-watcher study --input urls.tsv --out-root .\out                    # dry run: lists what it would fetch, costs nothing
uv run reel-watcher study --input urls.tsv --out-root .\out --run --limit 5    # real run on 5 reels
```

Check the results in `out\study\`, then run again without `--limit` for the rest. Finished reels are skipped,
failed ones are logged to `out\study\_failed.jsonl` and retried only with `--retry-failed`.

## What it does per reel

1. Fetches the video (or carousel slides) through Apify, the only network step.
2. Cuts the video into key frames (hook frames plus one frame after each scene cut) with FFmpeg.
3. Reads on-screen text with RapidOCR.
4. Merges near-duplicate frames, then asks the local vision model (Ollama) about all unique frames at once,
   using one labeled contact sheet (this is the speed trick).
5. Transcribes speech with word timing (faster-whisper).
6. Detects giveaways: "comment X", "DM me X", "link in bio", and what you get.
7. Writes `study\<code>.json` and a small hook image. With `--archive DIR` it also keeps the video and every analyzed frame.

## Cost

- Apify: about $0.002 per reel with the `apify/instagram-scraper` actor. Every batch is sent with a spending cap
  (`maxTotalChargeUsd`, default $2, set with `--apify-batch-cap-usd`) and the actual cost of each run is written to
  `apify_cost.jsonl`. Check current Apify pricing yourself.
- All analysis (OCR, vision model, whisper) is local and free.
- Without `APIFY_TOKEN` nothing is downloaded and nothing is charged. Dry run is the default.

## Getting your saved reels

Use Instagram's own data download, the safest route because it never touches your login.

1. Instagram (app or web) > Settings > Accounts Center > Your information and permissions >
   Download your information > Download or transfer information > your Instagram account >
   Some of your information > tick **Saved** > Export to device > format **JSON**.
2. Wait for the email, download and unzip. Look for `your_instagram_activity\saved\saved_posts.json`.
3. Convert it: `uv run reel-watcher export path\to\saved_posts.json -o urls.tsv`

HTML exports work too. Any text file with one URL per line (optionally `url<TAB>collection`) also works,
see `examples\urls.tsv`.

## Common options

| Option | Meaning |
|---|---|
| `--run` | Actually fetch and analyze (default is a dry run) |
| `--limit N` | Stop after N new reels |
| `--local A.mp4 B.mp4` | Analyze local files, no network |
| `--archive DIR` | Keep video, frames and manifest per reel in `DIR\<code>\` |
| `--collections a,b` and `--only-priority` | Do reels from matching collections first (or only) |
| `--model-size small\|large` | Model preset (default auto by RAM) |
| `--model TAG` | Exact Ollama vision model tag, overrides the preset |
| `--fast` | Fewer frames and tokens |
| `--detailed` | One model call per frame (slower, used automatically if the contact-sheet call fails) |
| `--rollup` | Rebuild `study_index.jsonl` from `study\*.json` |

Environment variables (set in PowerShell with `$env:NAME = "value"`):

| Variable | Meaning |
|---|---|
| `APIFY_TOKEN` | Required for `--run` |
| `REEL_WATCHER_MODEL` | `small` or `large` |
| `REEL_WATCHER_VLM` | Ollama vision model tag |
| `REEL_WATCHER_WHISPER` | faster-whisper model: `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo` |
| `REEL_WATCHER_WHISPER_DEVICE` | `cpu` (default) or `cuda` (NVIDIA GPU; needs CUDA 12 cuBLAS and cuDNN 9, e.g. `uv pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`) |
| `REEL_WATCHER_NUM_CTX` | Ollama context window (default 16384; lower it if you run out of memory) |
| `OLLAMA_HOST` | Ollama address (default `http://localhost:11434`) |
| `REEL_WATCHER_CONTEXT` | One phrase describing you, e.g. "a freelance video editor", so the verdict speaks to your goals |
| `REEL_WATCHER_WORKFLOW_RE` | Regex of collection names whose reels also get a `workflow` field |

## Troubleshooting

- **`uv`, `ffmpeg` or `ollama` is not recognized**: close and reopen PowerShell after installing (PATH refresh).
- **"Ollama is not reachable"**: start Ollama from the Start menu; check `ollama list` works.
- **Very slow / out of memory**: use `--model-size small --fast`, or lower `$env:REEL_WATCHER_NUM_CTX = "8192"`.
- **`setup.ps1` cannot be loaded because running scripts is disabled**: use the exact command in step 2
  (`powershell -ExecutionPolicy Bypass -File .\setup.ps1`).
- **Python version errors**: the project pins Python 3.12 (`.python-version`); uv downloads it automatically.

## Output: one study (`out\study\<code>.json`)

```json
{
  "code": "PLACEHOLDER",
  "url": "https://www.instagram.com/reel/PLACEHOLDER/",
  "kind": "reel",
  "collections": ["Example collection"],
  "post": {"caption": "...", "author": "creator", "likes": 0, "views": 0, "comments": 0,
           "post_date": "2026-01-01", "duration_s": 24.0, "music_info": null},
  "facts": {"duration_s": 24.0, "resolution": "720x1280", "fps": 30.0, "cuts": 9, "cuts_per_10s": 3.8,
            "cut_times": [1.2, 3.0], "broll_share_est": 0.4,
            "audio": {"has_audio": true, "speech_share": 0.8, "music_or_sfx_likely": false}},
  "hook_frame_text": ["text seen in the first 3 seconds"],
  "analysis": {
    "hook": {"spoken": "", "on_screen": "", "visual": "", "type": "bold claim"},
    "format": "talking head",
    "cta": {"spoken": "", "on_screen": "", "comment_word": "", "link_or_follow": ""},
    "structure_beats": [{"t": 0.0, "beat": "hook", "what": ""}],
    "why_it_works": "one line",
    "takeaway": {"relevant": false, "area": "", "insight": "", "action": ""}
  },
  "giveaway": {"offered": true, "keyword": "GUIDE", "what_they_get": "free guide", "channel": "comment",
               "evidence": [{"quote": "comment GUIDE below", "where": "transcript"}]},
  "transcript": {"language": "en", "text": "...", "words": [{"w": "hello", "s": 0.1, "e": 0.4}]},
  "frames": [{"t": 1.0, "file": "frames/f_000100.jpg", "shot_type": "talking head", "visual": {}}],
  "keyframe": "PLACEHOLDER.jpg", "analyzed_at": "2026-01-01T00:00:00", "wall_s": 41.2
}
```

The full field list is the same as the original project. Also written: `study_index.jsonl` (one summary line per
reel) and `apify_cost.jsonl`. Model output is not guaranteed to be correct: treat `analysis` as a draft.

## Optional: advice library

`uv run reel-watcher advice --in library.json --out advice-library.html` renders a static page of principles grouped
by topic. Have your AI assistant build `library.json` from your `study\*.json` using `prompts\build_advice_library.md`;
the format is shown in `examples\advice_library.json`.

## Ethics and terms

- Only analyze reels you saved yourself, for your own learning and research.
- Respect creators. Credit them, do not copy their work, and do not redistribute their videos, frames or transcripts.
- Scraping can conflict with Instagram's Terms of Use. You are responsible for how you use Apify and for complying
  with the platform's terms and the law where you live. This tool does not log in to your account or use your cookies.
- Model output can hallucinate, including names and quotes. Do not publish it as fact about a person.

## Development

```powershell
uv run pytest
```

See `AGENTS.md` for the code map. MIT licensed, see `LICENSE` (original work by Jacob Bruce).
