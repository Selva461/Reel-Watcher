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
5. Apify: I will create an account and an API token myself. Tell me to run `$env:APIFY_TOKEN = "..."` in my own
   PowerShell window. Never ask me to paste the token into chat, and never write it to a file.
6. Show the dry run (`uv run reel-watcher study --input urls.tsv --out-root .\out`) and the estimated cost
   at about $0.002 per reel. Do NOT pass `--run` until I say yes to that specific cost.
   Then run `--run --limit 5` first, and show me the results before doing the rest.
7. Rules: never log in to Instagram for me, never use my browser cookies, never commit my data, and keep all
   analysis local.
