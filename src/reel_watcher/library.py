"""The Reel Shelf library: one SQLite file holding reels, screenshots, found titles, quotes and job state.

Everything the app shows comes from here, and every background job writes here, so a job that is
killed (app closed, phone restarted) resumes from the stored item statuses.

Item status lifecycle:
  idle (imported, not queued) -> waiting -> working -> done | check | other | duplicate | skipped | failed
  waiting_quota: a free online service hit its daily limit; retried after next_try_at
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,              -- reel | image
  source TEXT NOT NULL,            -- reel url or image file path
  job_id INTEGER,
  status TEXT NOT NULL DEFAULT 'waiting',
  stage TEXT DEFAULT '',
  error TEXT DEFAULT '',
  attempts INTEGER DEFAULT 0,
  next_try_at REAL DEFAULT 0,
  hash TEXT DEFAULT '',
  meta TEXT DEFAULT '{}',
  added_at REAL,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS item_collections (
  item_id INTEGER NOT NULL,
  collection TEXT NOT NULL,
  PRIMARY KEY (item_id, collection)
);
CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY,
  ext_key TEXT UNIQUE,             -- anilist:123 | wikidata:Q42 | name:<normalized> for unverified names
  name TEXT NOT NULL,
  type TEXT DEFAULT 'other',       -- movie | series | anime | manga | book | game | other
  year INTEGER,
  language TEXT DEFAULT '',
  genres TEXT DEFAULT '[]',
  cover TEXT DEFAULT '',
  extra TEXT DEFAULT '{}',
  watch TEXT DEFAULT 'to_watch',   -- to_watch | watching | watched
  favorite INTEGER DEFAULT 0,
  notes TEXT DEFAULT '',
  created_at REAL
);
CREATE TABLE IF NOT EXISTS finds (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  title_id INTEGER,
  kind TEXT NOT NULL,              -- title | quote
  name_raw TEXT DEFAULT '',
  quote TEXT DEFAULT '',
  source TEXT DEFAULT '',          -- text | speech | caption | comment | scene | ai | user
  evidence TEXT DEFAULT '',
  confidence TEXT DEFAULT 'check', -- confirmed | matched | check
  score REAL DEFAULT 0,
  detail TEXT DEFAULT '',
  media TEXT DEFAULT '',
  created_at REAL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,              -- reels | folder
  params TEXT DEFAULT '{}',
  state TEXT DEFAULT 'running',    -- running | paused | done
  created_at REAL
);
CREATE TABLE IF NOT EXISTS quota (
  service TEXT NOT NULL,
  day TEXT NOT NULL,
  used INTEGER DEFAULT 0,
  PRIMARY KEY (service, day)
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status, kind, next_try_at);
CREATE INDEX IF NOT EXISTS idx_items_hash ON items(hash);
CREATE INDEX IF NOT EXISTS idx_finds_item ON finds(item_id);
CREATE INDEX IF NOT EXISTS idx_finds_title ON finds(title_id);
"""

DONE_STATES = ("done", "check", "other", "duplicate", "skipped", "failed")


def default_data_dir() -> Path:
    return Path(os.environ.get("REEL_SHELF_DATA") or Path.home() / "ReelShelf")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("meta", "params", "extra"):
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k] or "{}")
    if "genres" in d and isinstance(d["genres"], str):
        d["genres"] = json.loads(d["genres"] or "[]")
    return d


class Library:
    """Thread-safe wrapper around one SQLite connection (WAL mode)."""

    def __init__(self, data_dir: Path | str | None = None):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "media").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.dir / "library.db"), check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ------------------------------------------------------------ low level

    def q(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [_row(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        with self.lock:
            return _row(self.db.execute(sql, args).fetchone())

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    def close(self) -> None:
        with self.lock:
            self.db.close()

    # ------------------------------------------------------------ jobs

    def add_job(self, name: str, kind: str, params: dict | None = None) -> int:
        return self.x("INSERT INTO jobs(name, kind, params, state, created_at) VALUES(?,?,?,?,?)",
                      (name, kind, json.dumps(params or {}), "running", time.time()))

    def job(self, job_id: int) -> dict | None:
        return self.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    def jobs(self) -> list[dict]:
        out = self.q("SELECT * FROM jobs ORDER BY id DESC")
        for j in out:
            j["counts"] = self.counts(job_id=j["id"])
        return out

    def set_job_state(self, job_id: int, state: str) -> None:
        self.x("UPDATE jobs SET state=? WHERE id=?", (state, job_id))

    # ------------------------------------------------------------ items

    def add_item(self, key: str, kind: str, source: str, collections: list[str] | None = None,
                 job_id: int | None = None, meta: dict | None = None, hash_: str = "", status: str = "waiting") -> tuple[int, bool]:
        """Insert or reuse an item. Returns (item id, created). Collections are merged into existing items."""
        now = time.time()
        with self.lock:
            r = self.db.execute("SELECT id FROM items WHERE key=?", (key,)).fetchone()
            created = r is None
            if created:
                cur = self.db.execute(
                    "INSERT INTO items(key, kind, source, job_id, status, hash, meta, added_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (key, kind, source, job_id, status, hash_, json.dumps(meta or {}), now, now))
                iid = cur.lastrowid
            else:
                iid = r["id"]
                if job_id is not None:
                    self.db.execute("UPDATE items SET job_id=COALESCE(job_id, ?) WHERE id=?", (job_id, iid))
            for c in collections or []:
                self.db.execute("INSERT OR IGNORE INTO item_collections(item_id, collection) VALUES(?,?)", (iid, c))
            self.db.commit()
        return iid, created

    def item(self, item_id: int) -> dict | None:
        it = self.one("SELECT * FROM items WHERE id=?", (item_id,))
        if it:
            it["collections"] = [r["collection"] for r in self.q("SELECT collection FROM item_collections WHERE item_id=? ORDER BY collection", (item_id,))]
        return it

    def update_item(self, item_id: int, **fields) -> None:
        if "meta" in fields and isinstance(fields["meta"], dict):
            fields["meta"] = json.dumps(fields["meta"], ensure_ascii=False)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE items SET {cols} WHERE id=?", (*fields.values(), item_id))

    def merge_meta(self, item_id: int, **meta) -> None:
        with self.lock:
            it = self.item(item_id)
            m = {**(it or {}).get("meta", {}), **meta}
            self.update_item(item_id, meta=m)

    def claim_next(self, kind: str, job_id: int | None = None) -> dict | None:
        """Atomically take the next waiting item of `kind` (respecting paused jobs and quota waits)."""
        now = time.time()
        with self.lock:
            sql = ("SELECT i.id FROM items i LEFT JOIN jobs j ON j.id=i.job_id WHERE i.kind=? "
                   "AND (i.status='waiting' OR (i.status='waiting_quota' AND i.next_try_at<=?)) "
                   "AND (j.id IS NULL OR j.state='running')")
            args: list = [kind, now]
            if job_id is not None:
                sql += " AND i.job_id=?"
                args.append(job_id)
            r = self.db.execute(sql + " ORDER BY i.id LIMIT 1", args).fetchone()
            if not r:
                return None
            self.db.execute("UPDATE items SET status='working', attempts=attempts+1, updated_at=? WHERE id=?", (now, r["id"]))
            self.db.commit()
        return self.item(r["id"])

    def queue_collection(self, collection: str, retry_failed: bool = False) -> tuple[int, int]:
        """Start reading a collection: its idle items (and failed ones if asked) join a new 'reels' job.
        Returns (job id, number of items queued)."""
        states = ("idle", "failed", "skipped") if retry_failed else ("idle",)
        with self.lock:
            job = self.add_job("Read " + collection, "reels", {"collection": collection})
            cur = self.db.execute(
                f"UPDATE items SET status='waiting', job_id=?, error='', updated_at=? WHERE status IN ({','.join('?' * len(states))}) "
                "AND id IN (SELECT item_id FROM item_collections WHERE collection=?)", (job, time.time(), *states, collection))
            self.db.commit()
            return job, cur.rowcount

    def reset_stuck(self) -> int:
        """Items left 'working' by a killed process go back to the queue (called on start)."""
        with self.lock:
            cur = self.db.execute("UPDATE items SET status='waiting', stage='' WHERE status='working'")
            self.db.commit()
            return cur.rowcount

    def counts(self, job_id: int | None = None, collection: str | None = None) -> dict:
        sql, args = "SELECT i.status, COUNT(*) n FROM items i", []
        if collection:
            sql += " JOIN item_collections c ON c.item_id=i.id AND c.collection=?"
            args.append(collection)
        if job_id is not None:
            sql += " WHERE i.job_id=?"
            args.append(job_id)
        out = {r["status"]: r["n"] for r in self.q(sql + " GROUP BY i.status", args)}
        out["total"] = sum(out.values())
        return out

    def collections(self) -> list[dict]:
        rows = self.q("SELECT c.collection name, COUNT(*) items, SUM(i.status IN ('done','check')) finished, "
                      "MIN(i.kind) kind FROM item_collections c JOIN items i ON i.id=c.item_id GROUP BY c.collection ORDER BY c.collection")
        for r in rows:
            r["titles"] = (self.one("SELECT COUNT(DISTINCT f.title_id) n FROM finds f JOIN item_collections c ON c.item_id=f.item_id "
                                    "WHERE c.collection=? AND f.kind='title' AND f.title_id IS NOT NULL", (r["name"],)) or {}).get("n", 0)
            r["quotes"] = (self.one("SELECT COUNT(*) n FROM finds f JOIN item_collections c ON c.item_id=f.item_id "
                                    "WHERE c.collection=? AND f.kind='quote'", (r["name"],)) or {}).get("n", 0)
        return rows

    # ------------------------------------------------------------ titles and finds

    def upsert_title(self, ext_key: str, name: str, **fields) -> int:
        with self.lock:
            r = self.db.execute("SELECT id FROM titles WHERE ext_key=?", (ext_key,)).fetchone()
            if r:
                tid = r["id"]
                upd = {k: v for k, v in fields.items() if v not in (None, "", [], {})}
                if upd:
                    for k in ("genres", "extra"):
                        if k in upd:
                            upd[k] = json.dumps(upd[k], ensure_ascii=False)
                    cols = ", ".join(f"{k}=?" for k in upd)
                    self.db.execute(f"UPDATE titles SET {cols} WHERE id=?", (*upd.values(), tid))
            else:
                f = {"type": "other", "year": None, "language": "", "genres": [], "cover": "", "extra": {}, **fields}
                cur = self.db.execute(
                    "INSERT INTO titles(ext_key, name, type, year, language, genres, cover, extra, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (ext_key, name, f["type"], f["year"], f["language"], json.dumps(f["genres"], ensure_ascii=False), f["cover"],
                     json.dumps(f["extra"], ensure_ascii=False), time.time()))
                tid = cur.lastrowid
            self.db.commit()
        return tid

    def title(self, title_id: int) -> dict | None:
        t = self.one("SELECT * FROM titles WHERE id=?", (title_id,))
        if t:
            t["finds"] = self.q("SELECT f.*, i.source item_source, i.kind item_kind, i.meta item_meta FROM finds f "
                                "JOIN items i ON i.id=f.item_id WHERE f.title_id=? ORDER BY f.id", (title_id,))
            for f in t["finds"]:
                f["item_meta"] = json.loads(f["item_meta"] or "{}")
        return t

    def update_title(self, title_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "type", "year", "language", "watch", "favorite", "notes")}
        if allowed:
            cols = ", ".join(f"{k}=?" for k in allowed)
            self.x(f"UPDATE titles SET {cols} WHERE id=?", (*allowed.values(), title_id))

    def add_find(self, item_id: int, kind: str, **fields) -> int:
        f = {"title_id": None, "name_raw": "", "quote": "", "source": "", "evidence": "", "confidence": "check",
             "score": 0.0, "detail": "", "media": "", **fields}
        return self.x("INSERT INTO finds(item_id, title_id, kind, name_raw, quote, source, evidence, confidence, score, detail, media, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (item_id, f["title_id"], kind, f["name_raw"], f["quote"], f["source"], f["evidence"][:500], f["confidence"],
                       f["score"], f["detail"], f["media"], time.time()))

    def clear_finds(self, item_id: int) -> None:
        self.x("DELETE FROM finds WHERE item_id=?", (item_id,))

    def find(self, find_id: int) -> dict | None:
        return self.one("SELECT * FROM finds WHERE id=?", (find_id,))

    def update_find(self, find_id: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE finds SET {cols} WHERE id=?", (*fields.values(), find_id))

    # ------------------------------------------------------------ quota (free services' daily limits)

    def quota_used(self, service: str, day: str | None = None) -> int:
        day = day or time.strftime("%Y-%m-%d")
        r = self.one("SELECT used FROM quota WHERE service=? AND day=?", (service, day))
        return r["used"] if r else 0

    def quota_take(self, service: str, limit: int, day: str | None = None) -> bool:
        """Reserve one call of `service` today; False when today's free limit is used up."""
        day = day or time.strftime("%Y-%m-%d")
        with self.lock:
            used = self.quota_used(service, day)
            if used >= limit:
                return False
            self.db.execute("INSERT INTO quota(service, day, used) VALUES(?,?,1) ON CONFLICT(service, day) DO UPDATE SET used=used+1",
                            (service, day))
            self.db.commit()
        return True

    def quota_exhaust(self, service: str, day: str | None = None, limit: int = 10**6) -> None:
        """The service said 'limit reached' before our own count did: mark today as used up."""
        day = day or time.strftime("%Y-%m-%d")
        self.x("INSERT INTO quota(service, day, used) VALUES(?,?,?) ON CONFLICT(service, day) DO UPDATE SET used=?",
               (service, day, limit, limit))
