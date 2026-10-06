"""reel-watcher command line: study | export | advice."""
from __future__ import annotations

import sys

USAGE = """usage: reel-watcher <command> [options]

commands:
  export   convert an Instagram data export (saved_posts.json) into a URL list
  study    fetch (Apify) and analyze saved reels locally; --local analyzes mp4 files; dry run by default
  app      run the Reel Shelf app: phone UI, collections, search, screenshots, background jobs
  lookup   check a name or screenshot against the live free databases (what the app would pick, with details)
  selftest check that every free service is reachable from this device
  advice   render an advice library JSON to a static HTML page (optional)

Run `reel-watcher <command> --help` for options."""


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "study":
        from .study import main as run
    elif cmd == "export":
        from .ig_export import main as run
    elif cmd == "app":
        from .server import main as run
    elif cmd in ("lookup", "selftest"):
        from .verify import main as verify_main
        return verify_main([cmd, *rest])
    elif cmd == "advice":
        from .advice_library import main as run
    else:
        print(USAGE)
        return 2
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())
