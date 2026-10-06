#!/data/data/com.termux/files/usr/bin/bash
# Start Reel Shelf in the background on the phone and open it.
termux-wake-lock 2>/dev/null || true          # keep scanning while the screen is off
if command -v ollama >/dev/null 2>&1 && ! pgrep -x ollama >/dev/null; then (ollama serve >/dev/null 2>&1 &); sleep 2; fi
export REEL_WATCHER_MODEL="${REEL_WATCHER_MODEL:-phone}"
if ! pgrep -f "reel-watcher app" >/dev/null; then
  nohup reel-watcher app > "$HOME/reel-shelf.log" 2>&1 &
  sleep 3
fi
case "${1:-}" in
  --no-open) ;;
  # back to the Reel Shelf app if it is installed, else the browser
  --back) echo "Reel Shelf is running."
          am start -n app.reelshelf/.MainActivity >/dev/null 2>&1 || termux-open-url "http://localhost:8765/" 2>/dev/null || true ;;
  *) termux-open-url "http://localhost:8765/" 2>/dev/null || echo "Open http://localhost:8765 in your browser" ;;
esac
