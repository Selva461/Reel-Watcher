#!/data/data/com.termux/files/usr/bin/bash
# Reel Shelf on an Android phone, no PC needed. Everything installed here is free.
# Run inside Termux (from F-Droid):  curl -fsSL <raw url of this file> | bash
set -u
REPO="${REEL_SHELF_REPO:-https://github.com/selva461/Reel-Watcher.git}"
BRANCH="${REEL_SHELF_BRANCH:-ccr-d0c0b070-bdpssy}"
APP="$HOME/Reel-Watcher"
say() { printf '\n\033[1;33m== %s\033[0m\n' "$1"; }

say "1/7 Storage access (tap Allow so the app can read your screenshots)"
termux-setup-storage || true
sleep 2

say "2/7 Installing tools (python, ffmpeg, tesseract, build tools)"
pkg update -y
pkg install -y python git ffmpeg tesseract python-numpy python-pillow cmake clang make termux-api || {
  echo "Some packages failed. Run: pkg update && pkg upgrade, then run this script again."; exit 1; }

say "3/7 Getting Reel Shelf"
if [ -d "$APP/.git" ]; then git -C "$APP" fetch origin "$BRANCH" && git -C "$APP" checkout "$BRANCH" && git -C "$APP" pull --ff-only origin "$BRANCH"
else git clone -b "$BRANCH" "$REPO" "$APP"; fi
pip install --upgrade yt-dlp segno
# --no-deps: the PC-only parts (faster-whisper, RapidOCR) have no Android builds; the phone uses whisper.cpp and Tesseract
pip install --no-deps -e "$APP"

say "4/7 Speech-to-text (whisper.cpp)"
if ! command -v whisper-cli >/dev/null 2>&1; then pkg install -y whisper-cpp >/dev/null 2>&1 || true; fi
if ! command -v whisper-cli >/dev/null 2>&1; then
  echo "Building whisper.cpp from source (about 5-10 minutes, once)..."
  [ -d "$HOME/whisper.cpp" ] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$HOME/whisper.cpp"
  cmake -S "$HOME/whisper.cpp" -B "$HOME/whisper.cpp/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF >/dev/null
  cmake --build "$HOME/whisper.cpp/build" -j 4 --target whisper-cli
  ln -sf "$HOME/whisper.cpp/build/bin/whisper-cli" "$PREFIX/bin/whisper-cli"
fi
command -v whisper-cli >/dev/null 2>&1 && echo "whisper.cpp ready" || echo "whisper.cpp missing: reels will be read without speech"

say "5/7 AI vision model (Ollama, about 3 GB, once)"
if ! command -v ollama >/dev/null 2>&1; then pkg install -y ollama || true; fi
if command -v ollama >/dev/null 2>&1; then
  pgrep -x ollama >/dev/null || (ollama serve >/dev/null 2>&1 &)
  sleep 5
  ollama pull "${REEL_WATCHER_VLM:-qwen2.5vl:3b}" || echo "Model download failed; run 'ollama pull qwen2.5vl:3b' later on Wi-Fi."
else
  echo "Ollama not available on this phone: screenshots still work (text + free scene search), AI guesses are off."
fi

say "6/7 Launcher and app connection"
mkdir -p "$HOME/.shortcuts" "$HOME/.termux"
install -m 755 "$APP/android/reel-shelf-start.sh" "$HOME/.shortcuts/Reel Shelf"
install -m 755 "$APP/android/reel-shelf-start.sh" "$PREFIX/bin/reel-shelf"
install -m 755 "$APP/android/reel-shelf-stop.sh" "$PREFIX/bin/reel-shelf-stop"
grep -q "^allow-external-apps" "$HOME/.termux/termux.properties" 2>/dev/null || echo "allow-external-apps = true" >> "$HOME/.termux/termux.properties"
termux-reload-settings 2>/dev/null || true

say "7/7 Done"
echo "Start it any time with:  reel-shelf"
echo "Then open http://localhost:8765 in Chrome and choose 'Add to Home screen' (or install the Reel Shelf APK)."
echo "Important: Android Settings > Apps > Termux > Battery > Unrestricted, so scans keep running in the background."
