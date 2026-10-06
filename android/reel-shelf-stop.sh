#!/data/data/com.termux/files/usr/bin/bash
pkill -f "reel-watcher app" && echo "Reel Shelf stopped" || echo "Reel Shelf was not running"
termux-wake-unlock 2>/dev/null || true
