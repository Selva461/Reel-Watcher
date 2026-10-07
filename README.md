# Reel Shelf (reel-watcher, Windows + Android edition)

A Windows port of [jakeb144/reel-watcher](https://github.com/jakeb144/reel-watcher) by Jacob Bruce
([Instagram](https://www.instagram.com/itsjakebruce/)). The original runs only on Apple Silicon Macs (MLX + Apple Vision);
this version swaps those parts for tools that run on a normal Windows 10/11 PC:

| Job | Original (Mac) | This version (Windows) |
|---|---|---|
| Vision model | MLX (`mlx-vlm`) | [Ollama](https://ollama.com) running locally |
| Speech to text | `mlx-whisper` | `faster-whisper` (CPU by default, NVIDIA GPU optional) |
| On-screen text (OCR) | Apple Vision | RapidOCR (ONNX, CPU) |

It is also **100% free**: reels are downloaded with the open-source [yt-dlp](https://github.com/yt-dlp/yt-dlp)
instead of the paid Apify service (Apify is still available as an option, but you never need it).

Everything else (frame sampling, contact sheet, giveaway detection, output JSON) is the same.

You save reels on Instagram and never go back to them. reel-watcher has an AI model on your own PC watch them
for you and write down what each one is: the hook, the format, the on-screen text, the transcript, the editing
tricks, any "comment WORD and I'll send you X" giveaway, and a one-line verdict on why it works. You end up with
one searchable JSON file per reel. Everything except the media download runs on your machine, and nothing costs money:
no account, no API key, no credit card.

## Reel Shelf: the app

`reel-watcher app` is a phone-friendly app on top of the reel reader. Everything in it is free.

- **Collections, read one by one.** Import Instagram's data ZIP (or, if it went to Google Drive, its saved_collections.json and saved_posts.json); every collection (Movies, Series, Anime, Manga,
  Motivation, ...) shows up separately. Tap **Read this collection** to process it in the background.
- **Names, not just notes.** For title collections it lists every movie, series, anime, manga, book or game a reel
  mentions: from on-screen text, speech, the caption and the **comments** (creator's comments and repeated answers
  count most). Names are checked in AniList and Wikidata, so you get the official title, year, original language and genres.
- **Screenshots too.** Pick one screenshot, or **scan whole folders** (thousands of images) in the background.
  Text in the image is read first; images with no readable name use free scene search (trace.moe for anime,
  SauceNAO for manga). The AI's guess is shown right away, marked **Check this**, until something confirms it.
- **Motivation clips.** For motivation/quote collections it cuts the motivating line out of the reel as a GIF with
  word-by-word captions (Bold, Clean or Typewriter) or as a short video with sound. Save, share or copy the text.
- **Search with filters.** Title, creator or genre; title language, the language spoken in the reel, type, genre,
  status (to watch, watching, watched, favorites), found from (reel, screenshot, comment), confidence, collection, year, sort.
- **Background jobs.** Reels and screenshot folders are processed side by side, survive closing the app or a restart,
  and wait politely when a free service's daily limit is reached (they continue the next day by themselves).

### Run the app on your PC

```powershell
uv run reel-watcher app --open           # opens http://localhost:8765
uv run reel-watcher app --demo --open    # try it first with sample data
uv run reel-watcher app --lan            # also usable from your phone on the same Wi-Fi: scan the QR code it prints
```

### Run it on an Android phone, no PC needed

The easy way: the Reel Shelf app walks you through it and shows the setup progress.

1. On your phone open https://github.com/Selva461/Reel-Watcher/releases/tag/apk-latest , download `ReelShelf.apk`
   and install it (allow installing from your browser when Android asks).
2. Open Reel Shelf and follow the two steps it shows:
   - **Install Termux** from F-Droid (free). Not the Play Store version: that build is different and Reel Shelf cannot use it.
   - **Set up once**: tap *Copy setup command and open Termux*, then in Termux long-press, Paste, Enter.
     Come back to Reel Shelf to watch the progress; it opens by itself when it is ready (15-30 minutes, about 4 GB, use Wi-Fi).
3. Android Settings, Apps, Termux, Battery: **Unrestricted**, so scans keep running with the screen off.

Later, tap **Start Reel Shelf** in the app. If Android does not let the app start Termux, it opens Termux instead,
which starts Reel Shelf and brings you back. Opening Termux yourself does the same; `reel-shelf-stop` stops it.

Setup command, if you want to paste it yourself:

```bash
pkg install -y git && { git -C ~/Reel-Watcher pull -q --ff-only 2>/dev/null || git clone -b ccr-d0c0b070-bdpssy https://github.com/Selva461/Reel-Watcher.git ~/Reel-Watcher; } && bash ~/Reel-Watcher/android/termux-setup.sh
```

It installs Python, FFmpeg, Tesseract (text), whisper.cpp (speech) and a small AI vision model (`qwen2.5vl:3b`, about 3 GB).
A newer APK is signed differently, so uninstall the old Reel Shelf app before installing a new one (your library lives in Termux and is kept).

Without the APK you can also open http://localhost:8765 in Chrome and choose **Add to Home screen**.
On a phone, a reel takes longer than on a PC (a few minutes each); connect your PC with `--lan` for speed.

### How accurate names and details are found

Each name is checked against real databases before it is called **Confirmed**:

| Kind | Name check | Details shown |
|---|---|---|
| Anime | AniList, cross-checked with MyAnimeList (Jikan) | story, status, season, episodes, studio, AniList and MAL scores, official streaming links, sequels and the manga it is based on |
| Manga | AniList, cross-checked with MyAnimeList | story, status, chapters, volumes, author, where to read, the anime adaptation |
| Series | Wikidata (also searched in the reel's language, e.g. Tamil) | Wikipedia story, cast, TVmaze status, network, seasons, episodes, rating |
| Movies | Wikidata | Wikipedia story, director, cast, language, runtime, IMDb link |

Same name, different work ("Monster" 2004 vs 2023, "Vikram Vedha" 2017 vs 2022): the year in the reel, its
type, its language and popularity decide; if two are still too close the find is marked **Check this** and the
app offers **Could also be** buttons. Single everyday words ("Dark", "Up") need a strong clue before they are confirmed.

Real free limits the app respects (it paces itself and waits instead of failing):
AniList 30 to 90 requests a minute, Jikan 60 a minute, TVmaze 20 per 10 seconds, SauceNAO 4 per 30 seconds,
trace.moe **100 screenshot searches a month** (spread over the days left in the month; text in a screenshot is
always tried first because it costs nothing).

Optional free keys (no payment, just an account), set before starting the app:
- `SAUCENAO_API_KEY` from saucenao.com: about 200 screenshot searches a day instead of the anonymous allowance.
- `TMDB_API_KEY` from themoviedb.org (free for personal use): posters and the streaming services in your country.

### Check it against the real services yourself

```powershell
uv run reel-watcher selftest                                  # every free service, one request each
uv run reel-watcher selftest --image C:\path\to\screenshot.jpg  # also the screenshot search
uv run reel-watcher lookup "Vikram Vedha" --type movie --year 2017 --lang ta
uv run reel-watcher lookup "Vagabond" --type manga
uv run reel-watcher lookup --image C:\path\to\screenshot.jpg
```

Add `--json` and paste the output into an issue or a chat if something looks wrong.

## What you need

- Windows 10 or 11, 64-bit.
- RAM decides the model. `--model-size auto` (default) picks `phone` below 12 GB, `small` below 32 GB and `large` otherwise.

  | PC RAM | Setting | Vision model (Ollama) | Whisper | First download |
  |---|---|---|---|---|
  | 8 GB (and phones) | `phone` | `qwen2.5vl:3b` | `base` | about 3 GB |
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
git clone https://github.com/Selva461/Reel-Watcher.git
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

**5. Download and analyze them (free)**

```powershell
uv run reel-watcher study --input urls.tsv --out-root .\out                    # dry run: lists what it would download
uv run reel-watcher study --input urls.tsv --out-root .\out --run --limit 5    # real run on 5 reels
```

Check the results in `out\study\`, then run again without `--limit` for the rest. Finished reels are skipped,
failed ones are logged to `out\study\_failed.jsonl` and retried only with `--retry-failed`. You can leave it running
overnight.

**About free downloading.** yt-dlp downloads public reels without logging in. Instagram sometimes limits anonymous
downloads: if three reels in a row are refused, the run stops with a message. Those reels are *not* marked as failed, so
just wait an hour or two and run the same command again. It picks up where it stopped. If downloads keep failing,
update yt-dlp with `uv sync --upgrade-package yt-dlp`. Limits of the free route: private accounts and photo-only posts
(image carousels) can't be downloaded and are skipped. For a photo carousel, save the images yourself if you need them.

## What it does per reel

1. Downloads the video with yt-dlp (free), the only network step.
2. Cuts the video into key frames (hook frames plus one frame after each scene cut) with FFmpeg.
3. Reads on-screen text with RapidOCR.
4. Merges near-duplicate frames, then asks the local vision model (Ollama) about all unique frames at once,
   using one labeled contact sheet (this is the speed trick).
5. Transcribes speech with word timing (faster-whisper).
6. Detects giveaways: "comment X", "DM me X", "link in bio", and what you get.
7. Writes `study\<code>.json` and a small hook image. With `--archive DIR` it also keeps the video and every analyzed frame.

## Cost

**Free.** Every part is free and open source: yt-dlp (download), FFmpeg, Ollama and the Qwen vision models,
faster-whisper, RapidOCR. Nothing needs an account or a card. The only "cost" is your PC's electricity and disk space.

Optional and paid, never required: `--source apify` uses the Apify scraping service instead of yt-dlp (about $0.002
per reel; needs `APIFY_TOKEN`). It can also fetch photo carousels. Do not use it if you want to stay at zero cost.

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
| `--run` | Actually download and analyze (default is a dry run) |
| `--sleep N` | Seconds between downloads (default 4; raise it if Instagram refuses downloads) |
| `--source apify` | Optional paid downloader instead of the free yt-dlp (not needed) |
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
| `APIFY_TOKEN` | Only for the optional paid `--source apify` |
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
- **"Instagram is refusing anonymous downloads"**: wait an hour or two and run the same command again, or raise `--sleep`.
  Update yt-dlp with `uv sync --upgrade-package yt-dlp`.
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
reel). Model output is not guaranteed to be correct: treat `analysis` as a draft.

## Optional: advice library

`uv run reel-watcher advice --in library.json --out advice-library.html` renders a static page of principles grouped
by topic. Have your AI assistant build `library.json` from your `study\*.json` using `prompts\build_advice_library.md`;
the format is shown in `examples\advice_library.json`.

## Ethics and terms

- Only analyze reels you saved yourself, for your own learning and research.
- Respect creators. Credit them, do not copy their work, and do not redistribute their videos, frames or transcripts.
- Downloading can conflict with Instagram's Terms of Use. You are responsible for how you use yt-dlp and for complying
  with the platform's terms and the law where you live. This tool does not log in to your account or use your cookies.
- Model output can hallucinate, including names and quotes. Do not publish it as fact about a person.

## Development

```powershell
uv run pytest
```

See `AGENTS.md` for the code map. MIT licensed, see `LICENSE` (original work by Jacob Bruce).
