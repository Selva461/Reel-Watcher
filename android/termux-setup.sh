#!/data/data/com.termux/files/usr/bin/bash
# Reel Shelf on an Android phone, no PC needed. Everything installed here is free.
# Run inside Termux (from F-Droid or GitHub, not the Play Store): the Reel Shelf app copies the command for you.
set -u
REPO="${REEL_SHELF_REPO:-https://github.com/Selva461/Reel-Watcher.git}"
BRANCH="${REEL_SHELF_BRANCH:-ccr-d0c0b070-bdpssy}"
APP="$HOME/Reel-Watcher"
LOG="$HOME/reel-shelf-setup.log"
STATE="$HOME/.reel-shelf-setup.json"
TOTAL=7
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
say() { printf '\n\033[1;33m== %s\033[0m\n' "$1"; }
# step N "label": shown in the terminal and on the Reel Shelf app's progress screen
step() { say "$1/$TOTAL $2"; printf '{"step": %s, "total": %s, "label": "%s", "done": %s}\n' "$1" "$TOTAL" "$2" "${3:-false}" > "$STATE"; }
fail() { printf '{"step": 0, "total": %s, "label": "%s", "error": true}\n' "$TOTAL" "$1" > "$STATE"; echo "$1"; exit 1; }

step 1 "Storage access (tap Allow so the app can read your screenshots)"
termux-setup-storage || true
sleep 2

step 2 "Installing tools (python, ffmpeg, tesseract)"
# `yes` answers the "keep or replace config file?" questions that otherwise stop the upgrade
yes | pkg upgrade -y
pkg install -y python || fail "Could not install Python. Check the internet connection, then run the setup again."
pkill -f "setup-status.py" 2>/dev/null
[ -f "$APP/android/setup-status.py" ] && (python "$APP/android/setup-status.py" >/dev/null 2>&1 &)
step 2 "Installing tools (python, ffmpeg, tesseract)"
pkg install -y git ffmpeg tesseract python-numpy python-pillow cmake clang make termux-api || \
  fail "Some tools failed to install. Run: pkg upgrade, then run the setup again."

step 3 "Getting Reel Shelf"
if [ -d "$APP/.git" ]; then git -C "$APP" fetch origin "$BRANCH" && git -C "$APP" checkout "$BRANCH" && git -C "$APP" pull --ff-only origin "$BRANCH"
else git clone -b "$BRANCH" "$REPO" "$APP"; fi
pip install --upgrade yt-dlp segno
# --no-deps: the PC-only parts (faster-whisper, RapidOCR) have no Android builds; the phone uses whisper.cpp and Tesseract
pip install --no-deps -e "$APP"

step 4 "Speech-to-text (whisper.cpp, can take 10 minutes)"
if ! command -v whisper-cli >/dev/null 2>&1; then pkg install -y whisper-cpp >/dev/null 2>&1 || true; fi
if ! command -v whisper-cli >/dev/null 2>&1; then
  echo "Building whisper.cpp from source (about 5-10 minutes, once)..."
  [ -d "$HOME/whisper.cpp" ] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$HOME/whisper.cpp"
  cmake -S "$HOME/whisper.cpp" -B "$HOME/whisper.cpp/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF >/dev/null
  cmake --build "$HOME/whisper.cpp/build" -j 4 --target whisper-cli
  ln -sf "$HOME/whisper.cpp/build/bin/whisper-cli" "$PREFIX/bin/whisper-cli"
fi
command -v whisper-cli >/dev/null 2>&1 && echo "whisper.cpp ready" || echo "whisper.cpp missing: reels will be read without speech"

step 5 "AI vision model (about 3 GB download)"
if ! command -v ollama >/dev/null 2>&1; then pkg install -y ollama || true; fi
if command -v ollama >/dev/null 2>&1; then
  pgrep -x ollama >/dev/null || (ollama serve >/dev/null 2>&1 &)
  sleep 5
  ollama pull "${REEL_WATCHER_VLM:-qwen2.5vl:3b}" || echo "Model download failed; run 'ollama pull qwen2.5vl:3b' later on Wi-Fi."
else
  echo "Ollama not available on this phone: screenshots still work (text + free scene search), AI guesses are off."
fi

step 6 "Connecting the Reel Shelf app"
mkdir -p "$HOME/.shortcuts" "$HOME/.termux"
install -m 755 "$APP/android/reel-shelf-start.sh" "$HOME/.shortcuts/Reel Shelf"
install -m 755 "$APP/android/reel-shelf-start.sh" "$PREFIX/bin/reel-shelf"
install -m 755 "$APP/android/reel-shelf-stop.sh" "$PREFIX/bin/reel-shelf-stop"
grep -q "^allow-external-apps" "$HOME/.termux/termux.properties" 2>/dev/null || echo "allow-external-apps = true" >> "$HOME/.termux/termux.properties"
termux-reload-settings 2>/dev/null || true
# Opening Termux starts Reel Shelf, so the app works even when Android will not let it start Termux itself
MARK="# reel-shelf autostart"
grep -q "$MARK" "$HOME/.bashrc" 2>/dev/null || cat >> "$HOME/.bashrc" <<'RC'
# reel-shelf autostart
[ -x "$PREFIX/bin/reel-shelf" ] && ! pgrep -f "reel-watcher app" >/dev/null && reel-shelf --back
RC

step 7 "Starting Reel Shelf" true
reel-shelf --back
sleep 5
pkill -f "setup-status.py" 2>/dev/null
say "Done"
echo "Reel Shelf is running. If the Reel Shelf app did not open, open it now."
echo "Later, opening Termux starts it again. Stop it with: reel-shelf-stop"
echo "Important: Android Settings > Apps > Termux > Battery > Unrestricted, so scans keep running in the background."
