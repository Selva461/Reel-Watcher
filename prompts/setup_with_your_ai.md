# Send this to your AI coding assistant

Copy everything below the line into Claude Code, Codex or a similar assistant that can run commands on your Windows PC.

---

Set up reel-watcher (Windows edition) on this PC and run it on a small sample. Work in the repo folder you were
opened in (clone it if needed). Follow `AGENTS.md` and `README.md`. Use PowerShell.

1. Check RAM with `(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB` and whether there is an NVIDIA GPU
   (`nvidia-smi`). Tell me which model size will be used (small below 32 GB).
2. Run `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. It installs uv, FFmpeg and Ollama with winget, runs
   `uv sync` and the tests, and pulls the vision model. Tell me before you start that the download is several GB.
   If a tool is "not recognized" after install, tell me to reopen PowerShell.
3. Smoke test with no cost: ask me for one mp4 I own, run
   `uv run reel-watcher study --local <file> --out-root .\out`, and summarize `out\study\<name>.json` in five lines.
4. Saved reels: explain how to download my Instagram data (README section "Getting your saved reels"),
   wait for me to put `saved_posts.json` somewhere, then run `uv run reel-watcher export <file> -o urls.tsv`
   and tell me how many reels it found.
5. Show the dry run (`uv run reel-watcher study --input urls.tsv --out-root .\out`). Everything must stay free:
   use the default yt-dlp downloader, never `--source apify` or any paid service. Run `--run --limit 5` first and show
   me the results before doing the rest. If Instagram refuses downloads, tell me to wait and rerun later.
6. Rules: never log in to Instagram for me, never use my browser cookies, never commit my data, and keep all
   analysis local.
