"""Structured event log for debugging: one JSON line per event in <library>/logs/events.jsonl (rotated at 1 MB,
3 files kept) plus the last events in memory for debug reports. Events carry ids, steps, outcomes and errors, never
the contents of pictures or the user's files."""
from __future__ import annotations

import collections
import json
import logging
import logging.handlers
import threading
import time
import traceback
from pathlib import Path

_log = logging.getLogger("reel_shelf.events")
_log.propagate = False
RECENT: collections.deque = collections.deque(maxlen=400)
_lock = threading.Lock()
_path: Path | None = None


def setup(library_dir: Path) -> Path:
    """Write events under the library folder (called once when the app starts)."""
    global _path
    with _lock:
        d = Path(library_dir) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "events.jsonl"
        if _path != p:
            for h in list(_log.handlers):
                _log.removeHandler(h)
                h.close()
            h = logging.handlers.RotatingFileHandler(p, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(message)s"))
            _log.addHandler(h)
            _log.setLevel(logging.INFO)
            _path = p
    return p


def log_event(event: str, **fields) -> None:
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **{k: v for k, v in fields.items() if v is not None}}
    RECENT.append(rec)
    try:
        _log.info(json.dumps(rec, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001  logging must never break the app
        pass


def log_error(where: str, exc: BaseException, **fields) -> None:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    log_event("error", where=where, error=f"{type(exc).__name__}: {exc}"[:300], trace="".join(tb[-6:])[-1500:], **fields)


def recent(n: int = 150, item: int | None = None) -> list[dict]:
    rows = [r for r in list(RECENT) if item is None or r.get("item") == item]
    return rows[-n:]


def tail_file(n: int = 200) -> list[str]:
    if not _path or not _path.exists():
        return []
    with open(_path, encoding="utf-8", errors="replace") as f:
        return f.readlines()[-n:]
