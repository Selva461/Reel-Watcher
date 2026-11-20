"""`reel-watcher app`: the Reel Shelf app. A small local web server (standard library only) that serves the phone UI
and a JSON API, and runs the background engine.

  Phone only:  run it on the phone, open http://localhost:8765 and "Add to Home Screen".
  With a PC:   run it on the PC with --lan; the phone opens the printed address (or scans the QR code).
               LAN mode requires the secret token from that address, so other devices on the Wi-Fi cannot use it.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import identify, ig_export, lookups, scanner, worker
from .library import Library

WEB = Path(__file__).with_name("webapp")
QUICK_JOB = "Quick identify"
REPO_DIR = Path(__file__).resolve().parents[2]  # the git checkout the app runs from (installed in place)
LANG_CODES = {"English": "en", "Hindi": "hi", "Tamil": "ta", "Telugu": "te", "Malayalam": "ml", "Kannada": "kn", "Japanese": "ja",
              "Korean": "ko", "Spanish": "es", "French": "fr", "German": "de", "Chinese": "zh", "Portuguese": "pt", "Arabic": "ar"}
CONF_RANK = "MIN(CASE f.confidence WHEN 'confirmed' THEN 0 WHEN 'matched' THEN 1 ELSE 2 END)"
MAX_UPLOAD = 60 * 1024 * 1024
# pages may only run their own script; posters and covers come from the title databases over https
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class App:
    """All API behaviour, independent of HTTP so it is easy to test."""

    def __init__(self, lib: Library, engine: worker.Engine | None = None):
        self.lib = lib
        self.engine = engine
        self.settings_path = lib.dir / "settings.json"
        self.repo = REPO_DIR if (REPO_DIR / ".git").exists() else None
        from . import debuglog
        debuglog.setup(lib.dir)
        self.restart = None  # set by main(): replaces this process with a fresh one after an update

    # ------------------------------------------------------------ version and self-update

    def _git(self, *args, timeout: float = 20) -> str:
        import subprocess
        r = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise ApiError(502, "Update failed: " + ((r.stderr or r.stdout).strip().splitlines() or ["git error"])[-1][:200])
        return r.stdout.strip()

    def version(self) -> dict:
        out = {"version": "unknown", "date": "", "can_update": bool(self.repo and self.restart), "warnings": [],
               "update_available": bool(getattr(self, "_behind", 0)), "auto_update": bool(self.settings().get("auto_update", True))}
        from . import security
        out["warnings"] = security.outdated() + (list(dict.fromkeys(self.engine.warnings))[-5:] if self.engine else [])
        if self.repo:
            try:
                out["version"], out["date"] = self._git("log", "-1", "--format=%h|%cd", "--date=format:%d %b %Y %H:%M").split("|")
            except (ApiError, OSError, ValueError):
                pass
        return out

    # ------------------------------------------------------------ debug reports (pasted to whoever helps you)

    def _header_lines(self) -> list[str]:
        import platform
        v = self.version()
        st = self.settings()
        return [f"version: {v['version']} ({v['date']}) | python {platform.python_version()} | {platform.system()} {platform.machine()}"
                f" | termux: {'yes' if os.environ.get('TERMUX_VERSION') or 'com.termux' in str(Path.home()) else 'no'}",
                f"settings: online={st['online']} ai={st['ai']} region={st['region']}",
                f"warnings: {'; '.join(v['warnings']) or 'none'}"]

    def item_debug(self, iid: int) -> dict:
        from . import debuglog
        it = self.item(iid)
        m = it["meta"]
        lines = [f"Reel Shelf debug report: item {iid}", *self._header_lines(),
                 f"item: kind={it['kind']} status={it['status']} attempts={it.get('attempts')} stage={it.get('stage') or '-'}",
                 f"error: {it.get('error') or '-'}", f"collections: {', '.join(it.get('collections') or [])}",
                 f"file: {Path(str(it['source'])).name if it['kind'] == 'image' else it['source']}"]
        if m.get("ocr") is not None:
            lines.append(f"text read ({len(m['ocr'].split())} words): {m['ocr'][:700]}")
        for k in ("caption", "transcript", "reel_language", "author"):
            if m.get(k):
                lines.append(f"{k}: {str(m[k])[:400]}")
        lines.append("steps:")
        for k, v in (m.get("steps") or {}).items():
            lines.append(f"  {'OK ' if v.get('ok') else 'ERR' if v.get('ok') is False else ' - '} {k}: {v.get('detail')}")
        for r in m.get("web") or []:
            w = r.get("work") or {}
            lines.append(f"web: query={r.get('query')!r} clue={r.get('clue')!r} -> " +
                         (f"{w.get('name')} ({w.get('year')}, {w.get('type')}) via {w.get('site')}, {w.get('agree')} sites, "
                          f"other years={w.get('same_name_other_years')}" if w else "nothing") + f" | notes: {r.get('notes')}")
        for svc, res in (m.get("scene") or {}).items():
            lines.append(f"picture {svc}: {json.dumps(res, ensure_ascii=False, default=str)[:300]}")
        lines.append("decision:")
        for name, d in (m.get("proof") or {}).items():
            lines.append(f"  {name}: {d['verdict']} ({d['reason']})")
            for p in d["proof"]:
                lines.append(f"     {'counts' if p.get('counts') else 'no    '} {p['kind']}: {p.get('detail', '')[:150]}" + (f" [{p['why']}]" if p.get("why") else ""))
        lines.append("finds:")
        for f in it["finds"]:
            lines.append(f"  {f.get('name') or f.get('name_raw') or f.get('quote', '')[:40]} | {f['confidence']} | {f['source']} | {f['evidence']}")
        lines.append("events:")
        lines += [f"  {json.dumps(e, ensure_ascii=False, default=str)[:400]}" for e in debuglog.recent(40, item=iid)]
        return {"text": "\n".join(lines)}

    def app_debug(self) -> dict:
        from . import debuglog
        lines = ["Reel Shelf debug report: app", *self._header_lines()]
        rows = self.lib.q("SELECT kind, status, COUNT(*) n FROM items GROUP BY kind, status ORDER BY kind, status")
        lines.append("items: " + ", ".join(f"{r['kind']}/{r['status']}={r['n']}" for r in rows))
        for j in self.lib.q("SELECT id, name, kind, state FROM jobs ORDER BY id DESC LIMIT 8"):
            lines.append(f"job {j['id']}: {j['name']} [{j['kind']}] {j['state']} {self.lib.counts(job_id=j['id'])}")
        if self.engine:
            lines.append(f"working now: {len(self.engine.current)} | threads alive: {sum(t.is_alive() for t in self.engine.threads)}")
        lines.append("recent problems:")
        for r in self.lib.q("SELECT id, kind, status, error, meta FROM items WHERE status IN ('failed','skipped') OR error!='' "
                            "ORDER BY updated_at DESC LIMIT 12"):
            bad = [k for k, v in (r["meta"].get("steps") or {}).items() if v.get("ok") is False]
            lines.append(f"  item {r['id']} {r['kind']} {r['status']}: {r['error'] or '-'}" + (f" | failed steps: {', '.join(bad)}" if bad else ""))
        chk = self.check_status()
        if chk.get("rows"):
            lines.append("last self-check: " + "; ".join(f"{'PASS' if x['ok'] else 'FAIL'} {x['name']}" + ("" if x["ok"] else f" ({x['detail'][:80]})")
                                                       for x in chk["rows"]))
        lines.append("events:")
        ev = debuglog.recent(400)
        errors = [e for e in ev if e.get("event") == "error"][-15:]
        lines += [f"  {json.dumps(e, ensure_ascii=False, default=str)[:600]}" for e in errors]
        lines += [f"  {json.dumps(e, ensure_ascii=False, default=str)[:300]}" for e in ev[-50:] if e not in errors]
        return {"text": "\n".join(lines)}

    def item_image(self, iid: int) -> Path:
        it = self.lib.item(iid)
        if not it or it["kind"] != "image":
            raise ApiError(404, "No picture for this item")
        p = Path(str(it["source"]))
        if not p.is_file() or p.suffix.lower() not in scanner.IMAGE_EXT:
            raise ApiError(404, "The picture file is gone (moved or deleted)")
        return p

    def start_check(self) -> dict:
        from . import checks
        st = getattr(self, "_check", None)
        if st and st.get("running"):
            return st
        self._check = {"running": True, "current": "", "rows": [], "started": time.time()}

        def progress(name, rows):
            self._check.update(current=name, rows=list(rows))

        def run():
            try:
                checks.run_checks(self.lib.dir, progress)
            finally:
                self._check["running"] = False
        threading.Thread(target=run, daemon=True, name="self-check").start()
        return self._check

    def check_status(self) -> dict:
        return getattr(self, "_check", None) or {"running": False, "current": "", "rows": []}

    PIPELINE = 3  # bump when identification changes enough that old answers should be checked again (3: picture posts)

    def recheck_after_upgrade(self) -> int:
        """Once per identification upgrade: screenshots that failed, were not found or only guessed, and reels that
        failed, are identified again with the new rules. Answers the user confirmed are kept."""
        from .debuglog import log_event
        mark = self.lib.dir / "pipeline_version"
        try:
            done = int(mark.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            done = 0
        if done >= self.PIPELINE:
            return 0
        rows = self.lib.q("SELECT id FROM items WHERE (kind='image' AND status IN ('failed','skipped','check')) "
                          "OR (kind='reel' AND status='failed')")
        n = 0
        for r in rows:
            if self.lib.one("SELECT id FROM finds WHERE item_id=? AND source='user' LIMIT 1", (r["id"],)):
                continue
            self.retry_item(r["id"])
            n += 1
        mark.write_text(str(self.PIPELINE), encoding="utf-8")
        log_event("recheck_after_upgrade", items=n)
        return n

    def check_for_update(self) -> int:
        """How many new commits are waiting on GitHub (0 when up to date or offline)."""
        if not self.repo:
            return 0
        try:
            self._git("fetch", "--quiet", timeout=90)
            self._behind = int(self._git("rev-list", "--count", "HEAD..@{u}") or 0)
        except (ApiError, OSError, ValueError):
            return getattr(self, "_behind", 0)
        return self._behind

    def auto_update_loop(self, first_wait: float = 60, every: float = 3 * 3600, stop=None) -> None:
        """Keep a long-running app current: check, wait until nothing is being processed, update and restart."""
        from .debuglog import log_event
        stop = stop or threading.Event()
        wait = first_wait
        while not stop.wait(wait):
            wait = every
            if not (self.repo and self.restart and self.settings().get("auto_update", True)):
                continue
            behind = self.check_for_update()
            log_event("update_check", behind=behind)
            if not behind:
                continue
            for _ in range(60):  # up to 30 minutes for the current work to finish
                busy = self.lib.one("SELECT COUNT(*) n FROM items WHERE status='working'")["n"]
                if not busy:
                    break
                if stop.wait(30):
                    return
            try:
                r = self.update()
                log_event("auto_update", **{k: v for k, v in r.items() if k != "updated"}, updated=r.get("updated"))
            except ApiError as e:
                log_event("auto_update", error=str(e))

    def update(self) -> dict:
        """Download the latest code (git pull) and restart into it. Library and settings are kept."""
        if not self.repo or not self.restart:
            raise ApiError(400, "This copy cannot update itself. Reinstall it with the setup command.")
        before = self._git("rev-parse", "--short", "HEAD")
        try:
            self._git("pull", "--ff-only", timeout=120)
        except OSError as e:
            raise ApiError(502, f"Update failed: {e}") from e
        after = self._git("rev-parse", "--short", "HEAD")
        if after == before:
            return {"updated": False, "version": after}
        self._behind = 0
        self.restart()
        return {"updated": True, "from": before, "version": after}

    # ------------------------------------------------------------ settings

    def settings(self) -> dict:
        s = {"online": True, "quote_style": "bold", "region": "IN", "ai": False, "auto_update": True}
        try:
            s.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        return s

    def save_settings(self, body: dict) -> dict:
        s = self.settings()
        s.update({k: v for k, v in body.items() if k in ("online", "quote_style", "region", "ai", "auto_update")})
        s["online"], s["ai"] = bool(s.get("online")), bool(s.get("ai"))
        s["region"] = re.sub(r"[^A-Z]", "", str(s.get("region") or "IN").upper())[:2] or "IN"
        self.settings_path.write_text(json.dumps(s), encoding="utf-8")
        if self.engine:
            self.engine.online = bool(s["online"])
            self.engine.region = s["region"]
            self.engine.ai = bool(s["ai"])
        return s

    # ------------------------------------------------------------ home and collections

    def home(self) -> dict:
        cols = self.collections()
        recent = self.lib.q(
            "SELECT t.id, t.name, t.type, t.year, t.language, f.source, f.detail, f.confidence, i.kind item_kind, "
            "json_extract(i.meta,'$.thumb') thumb FROM finds f JOIN titles t ON t.id=f.title_id JOIN items i ON i.id=f.item_id "
            "WHERE f.kind='title' ORDER BY f.id DESC LIMIT 5")
        return {"collections": cols, "jobs": self.jobs()["jobs"], "recent": recent, "check": self.check_count()}

    def collections(self) -> list[dict]:
        out = []
        for c in self.lib.collections():
            kind = identify.collection_kind(c["name"])
            counts = self.lib.counts(collection=c["name"])
            out.append({"name": c["name"], "kind": "quote" if kind == "quote" else kind, "items": c["items"],
                        "titles": c["titles"], "quotes": c["quotes"], "idle": counts.get("idle", 0),
                        "done": sum(counts.get(k, 0) for k in ("done", "check", "other", "duplicate", "skipped")),
                        "working": counts.get("waiting", 0) + counts.get("working", 0) + counts.get("waiting_quota", 0)})
        return out

    def read_collection(self, name: str, retry: bool = False) -> dict:
        job, n = self.lib.queue_collection(name, retry_failed=retry)
        return {"job": job, "queued": n}

    def import_export(self, path: Path) -> dict:
        try:
            counts = ig_export.import_into(self.lib, path)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as e:
            too_big = "larger than" in str(e)
            raise ApiError(400, str(e) if too_big else "Could not read that file as an Instagram export. Choose the ZIP from "
                                "'Download your information' (JSON format).") from e
        if not counts:
            shape = ig_export.describe(path)
            raise ApiError(400, "No saved posts found. Choose the ZIP from Instagram's 'Download your information' (JSON format)."
                           + (f" The file looks like this (field names only, send a screenshot to get it supported): {shape[:600]}" if shape else ""))
        return {"collections": counts}

    # ------------------------------------------------------------ search

    def search(self, p: dict) -> dict:
        where, args = ["f.kind='title'"], []

        def multi(key):
            v = p.get(key)
            vals = v if isinstance(v, list) else [x for x in str(v or "").split(",") if x]
            return [x.strip() for x in vals if x.strip()]
        if p.get("q"):
            where.append("(t.name LIKE ? OR t.genres LIKE ? OR json_extract(i.meta,'$.author') LIKE ? OR f.name_raw LIKE ?)")
            like = f"%{p['q']}%"
            args += [like] * 4
        for key, col in (("type", "t.type"), ("language", "t.language"), ("confidence", "f.confidence")):
            vals = multi(key)
            if vals:
                where.append(f"{col} IN ({','.join('?' * len(vals))})")
                args += vals
        if multi("collection"):
            vals = multi("collection")
            where.append(f"f.item_id IN (SELECT item_id FROM item_collections WHERE collection IN ({','.join('?' * len(vals))}))")
            args += vals
        if multi("genre"):
            where.append("(" + " OR ".join("t.genres LIKE ?" for _ in multi("genre")) + ")")
            args += [f"%{g}%" for g in multi("genre")]
        if multi("reel_language"):
            codes = [LANG_CODES.get(x, x) for x in multi("reel_language")]
            where.append(f"json_extract(i.meta,'$.reel_language') IN ({','.join('?' * len(codes))})")
            args += codes
        src = multi("found_from")
        if src:
            ors = []
            if "Reel" in src:
                ors.append("(i.kind='reel' AND f.source!='comment')")
            if "Screenshot" in src:
                ors.append("i.kind='image'")
            if "Comment" in src:
                ors.append("f.source='comment'")
            if ors:
                where.append("(" + " OR ".join(ors) + ")")
        st = multi("status")
        if st:
            ors = [f"t.watch='{s}'" for s in ("to_watch", "watching", "watched") if s in st]
            if "favorites" in st:
                ors.append("t.favorite=1")
            where.append("(" + " OR ".join(ors) + ")" if ors else "1=0")
        for key, op in (("year_from", ">="), ("year_to", "<=")):
            if str(p.get(key) or "").isdigit():
                where.append(f"(t.year IS NULL OR t.year {op} ?)")
                args.append(int(p[key]))
        order = {"recent": "last_found DESC", "most": "n_reels DESC, last_found DESC", "az": "t.name COLLATE NOCASE",
                 "newest": "t.year IS NULL, t.year DESC"}.get(p.get("sort") or "recent", "last_found DESC")
        rows = self.lib.q(
            f"SELECT t.id, t.name, t.type, t.year, t.language, t.genres, t.watch, t.favorite, t.cover, "
            f"COUNT(DISTINCT f.item_id) n_reels, MAX(f.id) last_found, {CONF_RANK} conf_rank, "
            "GROUP_CONCAT(DISTINCT f.source) sources, GROUP_CONCAT(DISTINCT i.kind) kinds, MAX(json_extract(i.meta,'$.thumb')) thumb "
            f"FROM finds f JOIN titles t ON t.id=f.title_id JOIN items i ON i.id=f.item_id WHERE {' AND '.join(where)} "
            f"GROUP BY t.id ORDER BY {order} LIMIT 500", args)
        for r in rows:
            r["confidence"] = ["confirmed", "matched", "check"][r.pop("conf_rank") or 0]
            r["sources"] = (r["sources"] or "").split(",")
            r["kinds"] = (r["kinds"] or "").split(",")
        return {"results": rows, "count": len(rows)}

    def facets(self) -> dict:
        langs = [r["language"] for r in self.lib.q("SELECT DISTINCT language FROM titles WHERE language!='' ORDER BY language")]
        types = [r["type"] for r in self.lib.q("SELECT DISTINCT type FROM titles ORDER BY type")]
        genres = sorted({g for r in self.lib.q("SELECT genres FROM titles") for g in r["genres"]})
        reel_langs = [r["l"] for r in self.lib.q("SELECT DISTINCT json_extract(meta,'$.reel_language') l FROM items WHERE l IS NOT NULL")]
        code_name = {v: k for k, v in LANG_CODES.items()}
        return {"languages": langs, "types": types, "genres": genres[:40],
                "reel_languages": [code_name.get(c, c) for c in reel_langs], "collections": [c["name"] for c in self.lib.collections()]}

    # ------------------------------------------------------------ titles and finds

    def title(self, tid: int) -> dict:
        t = self.lib.title(tid)
        if not t:
            raise ApiError(404, "Title not found")
        for f in t["finds"]:
            it = self.lib.item(f["item_id"])
            f["collections"] = it["collections"]
            f["thumb"] = f["item_meta"].get("thumb", "")
            f["author"] = f["item_meta"].get("author")
            f["url"] = it["source"] if it["kind"] == "reel" else ""
            f.pop("item_meta", None)
        return t

    def patch_title(self, tid: int, body: dict) -> dict:
        if body.get("watch") and body["watch"] not in ("to_watch", "watching", "watched"):
            raise ApiError(400, "watch must be to_watch, watching or watched")
        if "favorite" in body:
            body["favorite"] = 1 if body["favorite"] else 0
        self.lib.update_title(tid, **body)
        return self.title(tid)

    def refresh_title(self, tid: int) -> dict:
        if not self.lib.one("SELECT id FROM titles WHERE id=?", (tid,)):
            raise ApiError(404, "Title not found")
        if not self.settings()["online"]:
            raise ApiError(400, "Turn on online lookups in Settings to fetch details")
        eng = self.engine or worker.Engine(self.lib)
        eng.region = self.settings()["region"]
        eng.ensure_details(tid, force=True)
        return self.title(tid)

    def switch_find(self, fid: int, ext_key: str) -> dict:
        """The user picked one of the alternatives ("not this Monster, the 2004 one")."""
        f = self.lib.find(fid)
        if not f:
            raise ApiError(404, "Not found")
        alt = next((a for a in f["alts"] if a.get("ext_key") == ext_key), None)
        if not alt:
            raise ApiError(400, "Pick one of the suggestions")
        cur = self.lib.one("SELECT ext_key, name, type, year, language FROM titles WHERE id=?", (f["title_id"],)) if f["title_id"] else None
        tid = self.lib.upsert_title(alt["ext_key"], alt["name"], type=alt.get("type") or "other", year=alt.get("year"), language=alt.get("language") or "")
        alts = [a for a in f["alts"] if a.get("ext_key") != ext_key]
        if cur:
            alts.insert(0, {k: cur[k] for k in ("ext_key", "name", "type", "year", "language")})
        self.lib.update_find(fid, title_id=tid, alts=json.dumps(alts, ensure_ascii=False))
        if self.engine and self.settings()["online"]:
            self.engine.ensure_details(tid)
        return self.confirm_find(fid)

    def check_list(self) -> dict:
        rows = self.lib.q(
            "SELECT f.id, f.item_id, f.title_id, f.name_raw, f.source, f.evidence, f.detail, f.alts, t.name, t.type, t.year, i.kind item_kind, "
            "json_extract(i.meta,'$.thumb') thumb, i.status item_status FROM finds f JOIN items i ON i.id=f.item_id "
            "LEFT JOIN titles t ON t.id=f.title_id WHERE f.kind='title' AND f.confidence='check' ORDER BY f.item_id DESC, f.id")
        return {"finds": rows}

    def check_count(self) -> int:
        return (self.lib.one("SELECT COUNT(DISTINCT item_id) n FROM finds WHERE confidence='check'") or {}).get("n", 0)

    def item(self, iid: int) -> dict:
        it = self.lib.item(iid)
        if not it:
            raise ApiError(404, "Item not found")
        it["finds"] = self.lib.q("SELECT f.*, t.name, t.type, t.year, t.language, t.genres, t.extra FROM finds f "
                                 "LEFT JOIN titles t ON t.id=f.title_id WHERE f.item_id=? ORDER BY "
                                 "CASE f.confidence WHEN 'confirmed' THEN 0 WHEN 'matched' THEN 1 ELSE 2 END, f.score DESC, f.id", (iid,))
        it["meta"] = {k: v for k, v in it["meta"].items() if k not in ("quote_words",)}
        return it

    def confirm_find(self, fid: int) -> dict:
        f = self.lib.find(fid)
        if not f:
            raise ApiError(404, "Not found")
        # choosing one answer for an item removes the other guesses for it
        self.lib.x("DELETE FROM finds WHERE item_id=? AND id!=? AND kind='title' AND confidence='check'", (f["item_id"], fid))
        self.lib.update_find(fid, confidence="confirmed")
        self.lib.update_item(f["item_id"], status="done")
        return self.item(f["item_id"])

    def title_for_name(self, name: str, kind: str = "") -> int:
        """A name the user typed: the database entry when there is one, else what a web search finds, else the name as typed."""
        kind = kind if kind in worker.TITLE_KINDS else ""
        if self.settings()["online"]:
            hit = None
            try:
                hit = lookups.resolve_name(name, kind)
            except Exception:  # noqa: BLE001  offline or a service down: fall through to the web, then the plain name
                hit = None
            if hit:
                return self.lib.upsert_title(hit["ext_key"], hit["name"], type=hit["type"], year=hit.get("year"), language=hit.get("language") or "",
                                             genres=hit.get("genres") or [], cover=hit.get("cover") or "", extra=hit.get("extra") or {})
            try:
                work, _ = lookups.web_identify(identify.search_query("", [{"name": name, "score": 9, "type": kind}], kind),
                                               name_hint=name, kind_hint=kind)
            except Exception:  # noqa: BLE001
                work = None
            if work and lookups.similarity(work["name"], name) >= 0.85 and self.engine:
                return self.engine.save_web_work(work)
        return self.lib.upsert_title("name:" + lookups.norm(name), name, type=kind or "other")

    def rename_find(self, fid: int, name: str, kind: str = "") -> dict:
        f = self.lib.find(fid)
        name, kind = str(name or "").strip()[:200], str(kind or "")
        if not f:
            raise ApiError(404, "Not found")
        if not name:
            raise ApiError(400, "Type a name")
        tid = self.title_for_name(name, kind)
        self.lib.update_find(fid, title_id=tid, name_raw=name, source="user", confidence="confirmed")
        return self.confirm_find(fid)

    def name_item(self, iid: int, name: str, kind: str = "") -> dict:
        """The user types the name for a screenshot or reel that has no guess at all."""
        if not self.lib.item(iid):
            raise ApiError(404, "Item not found")
        name, kind = str(name or "").strip()[:200], str(kind or "")
        if not name:
            raise ApiError(400, "Type a name")
        fid = self.lib.add_find(iid, "title", title_id=self.title_for_name(name, kind), name_raw=name, source="user",
                                confidence="confirmed", score=1.0)
        return self.confirm_find(fid)

    def retry_item(self, iid: int) -> dict:
        """Run identification again (after fixing the internet connection, an update, or enabling lookups).
        Text already read is kept; the user's own answers are kept."""
        it = self.lib.item(iid)
        if not it:
            raise ApiError(404, "Item not found")
        meta = {k: v for k, v in it["meta"].items() if k not in ("steps", "text_checked", "web", "ai", "scene")}
        self.lib.x("DELETE FROM finds WHERE item_id=? AND source!='user'", (iid,))
        self.lib.update_item(iid, meta=meta, status="waiting", stage="", error="", next_try_at=0, job_id=self.quick_job())
        return self.item(iid)

    def remove_find(self, fid: int) -> dict:
        f = self.lib.find(fid)
        if not f:
            raise ApiError(404, "Not found")
        self.lib.x("DELETE FROM finds WHERE id=?", (fid,))
        left = self.lib.one("SELECT COUNT(*) n FROM finds WHERE item_id=?", (f["item_id"],))["n"]
        if not left:
            self.lib.update_item(f["item_id"], status="skipped", error="removed by you")
        return {"ok": True}

    # ------------------------------------------------------------ quotes

    def quotes(self, collection: str | None = None, favorites: bool = False) -> dict:
        sql = ("SELECT f.id, f.item_id, f.quote, f.media, f.detail, f.source, json_extract(i.meta,'$.thumb') thumb, "
               "json_extract(i.meta,'$.author') author, json_extract(i.meta,'$.favorite') favorite, i.source url FROM finds f "
               "JOIN items i ON i.id=f.item_id WHERE f.kind='quote'")
        args: list = []
        if collection:
            sql += " AND f.item_id IN (SELECT item_id FROM item_collections WHERE collection=?)"
            args.append(collection)
        if favorites:
            sql += " AND json_extract(i.meta,'$.favorite')=1"
        return {"quotes": self.lib.q(sql + " ORDER BY f.id DESC", args)}

    def quote_favorite(self, fid: int, on: bool) -> dict:
        f = self.lib.find(fid)
        if not f:
            raise ApiError(404, "Not found")
        self.lib.merge_meta(f["item_id"], favorite=1 if on else 0)
        return {"favorite": on}

    def render(self, fid: int, style: str, fmt: str) -> dict:
        if style not in ("bold", "clean", "typewriter") or fmt not in ("gif", "mp4"):
            raise ApiError(400, "style must be bold, clean or typewriter; format gif or mp4")
        if not self.engine:
            raise ApiError(503, "Engine not running")
        try:
            return {"media": self.engine.render_quote(fid, style, fmt)}
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            raise ApiError(400, str(e)) from e

    # ------------------------------------------------------------ identify one thing

    def quick_job(self) -> int:
        j = self.lib.one("SELECT id FROM jobs WHERE name=? ORDER BY id DESC LIMIT 1", (QUICK_JOB,))
        if j:
            self.lib.set_job_state(j["id"], "running")
            return j["id"]
        return self.lib.add_job(QUICK_JOB, "quick")

    def identify_image(self, data: bytes, filename: str, collection: str = "Screenshots") -> dict:
        ext = Path(filename or "x.jpg").suffix.lower()
        if ext not in scanner.IMAGE_EXT:
            raise ApiError(400, "Choose a picture (JPG, PNG or WEBP)")
        up = self.lib.dir / "uploads"
        up.mkdir(exist_ok=True)
        import hashlib
        dest = up / (hashlib.sha1(data).hexdigest()[:20] + ext)
        dest.write_bytes(data)
        key = scanner.file_key(dest)
        iid, created = self.lib.add_item(key, "image", str(dest), [collection or "Screenshots"], job_id=self.quick_job())
        return {"item": iid, "new": created}

    def identify_reel(self, url: str, collection: str = "") -> dict:
        from . import media
        url, collection = str(url or "").strip(), str(collection or "").strip()
        code = media.id_from_url(url)
        if not code:
            raise ApiError(400, "Paste an Instagram reel or post link")
        canonical = f"https://www.instagram.com/reel/{code[3:]}/"  # never store or download the pasted address itself
        iid, created = self.lib.add_item(f"reel:{code[3:]}", "reel", canonical, [collection[:80] or ig_export.UNSORTED],
                                         job_id=self.quick_job())
        if not created and self.lib.item(iid)["status"] in ("idle", "failed"):
            self.lib.update_item(iid, status="waiting", job_id=self.quick_job())
        return {"item": iid, "new": created}

    # ------------------------------------------------------------ folders and jobs

    def roots(self) -> list[dict]:
        cands = [Path("/sdcard"), Path("/storage/emulated/0"), Path.home() / "storage" / "shared", Path.home() / "Pictures",
                 Path.home() / "Downloads", Path.home()]
        if sys.platform == "win32":
            cands += [Path(f"{d}:\\") for d in "CDEFG"]
        cands += [Path(x) for x in os.environ.get("REEL_SHELF_ROOTS", "").split(os.pathsep) if x.strip()]  # extra folders, e.g. a second drive
        seen, out = set(), []
        for c in cands:
            try:
                if c.is_dir() and c.resolve() not in seen:
                    seen.add(c.resolve())
                    out.append({"name": str(c), "path": str(c)})
            except OSError:
                continue
        return out

    def _allowed_folder(self, p: Path) -> bool:
        """The folder picker and folder scans stay inside the storage roots (phone storage, home folder, PC drives)."""
        try:
            rp = p.resolve()
        except (OSError, RuntimeError):
            return False
        for r in self.roots():
            root = Path(r["path"]).resolve()
            if rp == root or root in rp.parents:
                return True
        return False

    def fs(self, path: str | None) -> dict:
        if not path:
            return {"path": "", "parent": None, "dirs": self.roots(), "images": 0}
        p = Path(str(path)).expanduser()
        if not self._allowed_folder(p):
            raise ApiError(403, "Only folders in your storage can be opened")
        if not p.is_dir():
            raise ApiError(404, "Folder not found")
        dirs, images = [], 0
        try:
            entries = sorted(p.iterdir(), key=lambda x: x.name.lower())
        except OSError as e:
            raise ApiError(403, f"Cannot open this folder: {e}") from e
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir():
                    dirs.append({"name": e.name, "path": str(e)})
                elif e.suffix.lower() in scanner.IMAGE_EXT:
                    images += 1
            except OSError:
                continue
        return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs[:300], "images": images}

    def start_folders(self, body: dict) -> dict:
        raw = body.get("folders")
        folders = [str(f) for f in (raw if isinstance(raw, list) else []) if isinstance(f, str) and f.strip()]
        if any(not self._allowed_folder(Path(f).expanduser()) for f in folders):
            raise ApiError(403, "Only folders in your storage can be scanned")
        folders = [f for f in folders if Path(f).expanduser().is_dir()]
        if not folders:
            raise ApiError(400, "Pick at least one folder")
        collection = str(body.get("collection") or "Screenshots").strip()[:80] or "Screenshots"
        job = self.lib.add_job(body.get("name") or "Scan " + ", ".join(Path(f).name for f in folders), "folder",
                               {"folders": folders, "collection": collection, "watch": bool(body.get("watch", True)),
                                "skip_dupes": bool(body.get("skip_dupes", True)), "scanning": True})

        def scan():
            try:
                scanner.scan_folders(self.lib, folders, job, collection, bool(body.get("skip_dupes", True)))
            finally:
                params = self.lib.job(job)["params"]
                params["scanning"] = False
                self.lib.x("UPDATE jobs SET params=? WHERE id=?", (json.dumps(params), job))
        threading.Thread(target=scan, daemon=True, name=f"scan-{job}").start()
        return {"job": job}

    def jobs(self) -> dict:
        out = []
        for j in self.lib.jobs():
            c = j["counts"]
            if not c.get("total") and not j["params"].get("scanning"):
                continue
            left = c.get("waiting", 0) + c.get("working", 0) + c.get("waiting_quota", 0)
            out.append({"id": j["id"], "name": j["name"], "kind": j["kind"], "state": j["state"], "counts": c,
                        "done": c["total"] - left - c.get("idle", 0), "total": c["total"] - c.get("idle", 0), "left": left,
                        "scanning": bool(j["params"].get("scanning")), "finished": left == 0 and not j["params"].get("scanning")})
        stages = []
        if self.engine:
            for th, src in list(self.engine.current.items()):
                it = self.lib.one("SELECT id, stage FROM items WHERE source=? AND status='working'", (src,))
                if it:
                    stages.append({"worker": th, "item": it["id"], "stage": it["stage"]})
        return {"jobs": out, "active": [j for j in out if not j["finished"]], "stages": stages,
                "warnings": list(self.engine.warnings[-3:]) if self.engine else [], "engine": bool(self.engine)}

    def job_action(self, job_id: str, action: str) -> dict:
        if action not in ("pause", "resume"):
            raise ApiError(400, "action must be pause or resume")
        state = "paused" if action == "pause" else "running"
        ids = [j["id"] for j in self.lib.q("SELECT id FROM jobs")] if job_id == "all" else [int(job_id)]
        for i in ids:
            self.lib.set_job_state(i, state)
        return self.jobs()

    def export_csv(self, collection: str | None) -> str:
        res = self.search({"collection": collection} if collection else {})["results"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Title", "Type", "Year", "Language", "Genres", "Status", "Favorite", "Reels", "Confidence"])
        def cell(v):  # a title like "=HYPERLINK(...)" must not become a formula in Excel or Sheets
            v = "" if v is None else str(v)
            return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
        for r in res:
            w.writerow([cell(x) for x in (r["name"], r["type"], r["year"] or "", r["language"], "; ".join(r["genres"]), r["watch"],
                                          "yes" if r["favorite"] else "", r["n_reels"], r["confidence"])])
        return buf.getvalue()


# ---------------------------------------------------------------- HTTP layer

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


@route("GET", "/api/home")
def _home(app, m, q, body):
    return app.home()


@route("GET", "/api/version")
def _version(app, m, q, body):
    return app.version()


@route("GET", r"/api/items/(?P<id>\d+)/debug")
def _item_debug(app, m, q, body):
    return app.item_debug(int(m["id"]))


@route("GET", "/api/debug")
def _app_debug(app, m, q, body):
    return app.app_debug()


@route("POST", "/api/selfcheck")
def _selfcheck(app, m, q, body):
    return app.start_check()


@route("GET", "/api/selfcheck")
def _selfcheck_status(app, m, q, body):
    return app.check_status()


@route("POST", "/api/update")
def _update(app, m, q, body):
    return app.update()


@route("GET", "/api/collections")
def _cols(app, m, q, body):
    return {"collections": app.collections()}


@route("POST", "/api/collections/(?P<name>[^/]+)/read")
def _read(app, m, q, body):
    return app.read_collection(urllib.parse.unquote(m["name"]), bool((body or {}).get("retry")))


@route("GET", "/api/search")
def _search(app, m, q, body):
    return app.search(q)


@route("GET", "/api/facets")
def _facets(app, m, q, body):
    return app.facets()


@route("GET", r"/api/titles/(?P<id>\d+)")
def _title(app, m, q, body):
    return app.title(int(m["id"]))


@route("PATCH", r"/api/titles/(?P<id>\d+)")
def _ptitle(app, m, q, body):
    return app.patch_title(int(m["id"]), body or {})


@route("POST", r"/api/titles/(?P<id>\d+)/refresh")
def _refresh(app, m, q, body):
    return app.refresh_title(int(m["id"]))


@route("POST", r"/api/finds/(?P<id>\d+)/switch")
def _switch(app, m, q, body):
    return app.switch_find(int(m["id"]), (body or {}).get("ext_key", ""))


@route("GET", "/api/check")
def _check(app, m, q, body):
    return app.check_list()


@route("GET", r"/api/items/(?P<id>\d+)")
def _item(app, m, q, body):
    return app.item(int(m["id"]))


@route("POST", r"/api/finds/(?P<id>\d+)/confirm")
def _confirm(app, m, q, body):
    return app.confirm_find(int(m["id"]))


@route("POST", r"/api/items/(?P<id>\d+)/name")
def _name_item(app, m, q, body):
    return app.name_item(int(m["id"]), (body or {}).get("name", ""), (body or {}).get("type", ""))


@route("POST", r"/api/items/(?P<id>\d+)/retry")
def _retry_item(app, m, q, body):
    return app.retry_item(int(m["id"]))


@route("POST", r"/api/finds/(?P<id>\d+)/rename")
def _rename(app, m, q, body):
    return app.rename_find(int(m["id"]), (body or {}).get("name", ""), (body or {}).get("type", ""))


@route("DELETE", r"/api/finds/(?P<id>\d+)")
def _remove(app, m, q, body):
    return app.remove_find(int(m["id"]))


@route("GET", "/api/quotes")
def _quotes(app, m, q, body):
    return app.quotes(q.get("collection"), q.get("favorites") == "1")


@route("POST", r"/api/quotes/(?P<id>\d+)/favorite")
def _qfav(app, m, q, body):
    return app.quote_favorite(int(m["id"]), bool((body or {}).get("on", True)))


@route("POST", r"/api/quotes/(?P<id>\d+)/render")
def _render(app, m, q, body):
    return app.render(int(m["id"]), (body or {}).get("style", "bold"), (body or {}).get("format", "gif"))


@route("POST", "/api/identify/reel")
def _idreel(app, m, q, body):
    return app.identify_reel((body or {}).get("url", ""), (body or {}).get("collection", ""))


@route("GET", "/api/fs")
def _fs(app, m, q, body):
    return app.fs(q.get("path"))


@route("POST", "/api/folders")
def _folders(app, m, q, body):
    return app.start_folders(body or {})


@route("GET", "/api/jobs")
def _jobs(app, m, q, body):
    return app.jobs()


@route("POST", r"/api/jobs/(?P<id>all|\d+)/(?P<action>pause|resume)")
def _jobact(app, m, q, body):
    return app.job_action(m["id"], m["action"])


@route("GET", "/api/settings")
def _settings(app, m, q, body):
    return app.settings()


@route("POST", "/api/settings")
def _psettings(app, m, q, body):
    return app.save_settings(body or {})


class Handler(BaseHTTPRequestHandler):
    server_version = "ReelShelf/0.2"
    app: App = None  # type: ignore[assignment]
    token: str | None = None

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj, extra=None):
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _authorized(self, q: dict) -> tuple[bool, dict]:
        if not self.token:
            return True, {}
        if secrets.compare_digest(str(q.get("t") or ""), self.token):
            return True, {"Set-Cookie": f"rs_token={self.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"}
        c = SimpleCookie(self.headers.get("Cookie") or "")
        if "rs_token" in c and secrets.compare_digest(c["rs_token"].value, self.token):
            return True, {}
        if secrets.compare_digest(self.headers.get("X-Token", ""), self.token):
            return True, {}
        return False, {}

    def _host_ok(self) -> bool:
        """Without an access code only this device may connect, by name: a web page that points its own domain at
        127.0.0.1 (DNS rebinding) would otherwise be able to read the library."""
        if self.token:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        name = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.rsplit(":", 1)[0]
        return name in ("localhost", "127.0.0.1", "::1")

    def _same_origin(self, method: str) -> bool:
        """Changes may only come from Reel Shelf's own pages, not from another web site (cross-site request forgery).
        Browsers send Origin on cross-site requests and need permission for JSON or file bodies, which is never given."""
        if method in ("GET", "HEAD"):
            return True
        origin = self.headers.get("Origin")
        if origin and origin != "null" and urllib.parse.urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
            return False
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return ctype in ("application/json", "application/octet-stream")

    def _handle(self, method: str):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        if not self._host_ok():
            return self._send(421, b"Open Reel Shelf at http://localhost:8765", "text/plain; charset=utf-8")
        ok, extra = self._authorized(q)
        if not ok:
            return self._send(401, b"Open the address shown on your PC (it contains the access code).", "text/plain; charset=utf-8")
        path = u.path
        if path.startswith("/api/") and not self._same_origin(method):
            return self._json(403, {"error": "Blocked: this request did not come from the Reel Shelf app."}, extra)
        if self.token and "t" in q and method == "GET" and not path.startswith(("/api/", "/media/")):
            # access code accepted: keep it out of the address bar and history (the cookie carries it now)
            return self._send(303, b"", "text/plain", {**extra, "Location": path or "/"})
        try:
            if path.startswith("/api/"):
                return self._api(method, path, q, extra)
            if method not in ("GET", "HEAD"):
                return self._json(405, {"error": "method not allowed"})
            if path.startswith("/media/"):
                return self._file(self.app.lib.dir / "media", path[len("/media/"):], extra)
            return self._file(WEB, "index.html" if path in ("/", "") else path.lstrip("/"), extra)
        except ApiError as e:
            return self._json(e.status, {"error": str(e)}, extra)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()  # full details go to the log (Termux: ~/reel-shelf.log)
            from .debuglog import log_error
            log_error("http", e, method=method, path=path)
            return self._json(500, {"error": f"Reel Shelf hit a problem ({type(e).__name__}: {str(e)[:120]}). "
                                             "Try again; if it repeats, update the app in Settings."}, extra)

    def _file(self, root: Path, rel: str, extra):
        rel = urllib.parse.unquote(rel)
        target = (root / rel).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/manifest+json"):
            ctype += "; charset=utf-8"
        return self._send(200, target.read_bytes(), ctype, extra)

    def _body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError as e:
            raise ApiError(400, "Bad Content-Length") from e
        if n < 0:
            raise ApiError(400, "Bad Content-Length")
        if n > MAX_UPLOAD:
            raise ApiError(413, "File too large")
        return self.rfile.read(n) if n else b""

    def _api(self, method, path, q, extra):
        if method == "POST" and path == "/api/import":
            raw = self._body()
            up = self.app.lib.dir / "uploads"
            up.mkdir(exist_ok=True)
            name = Path(urllib.parse.unquote(self.headers.get("X-Filename") or "export.zip")).name
            if raw[:2] == b"PK" or name.lower().endswith(".zip"):
                dest = up / ("export_" + re.sub(r"[^A-Za-z0-9._-]", "_", name))
                dest.write_bytes(raw)
                return self._json(200, self.app.import_export(dest), extra)
            # loose export files (e.g. saved to Google Drive): keep them together so both files are read as one export
            kind = ig_export.export_file_name(name, raw.decode("utf-8", errors="replace"))
            if kind is None:
                raise ApiError(400, f"{name} is not one of the files Reel Shelf needs. Choose saved_collections.json and saved_posts.json.")
            loose = up / "instagram"
            loose.mkdir(exist_ok=True)
            (loose / kind).write_bytes(raw)
            return self._json(200, self.app.import_export(loose), extra)
        mi = re.fullmatch(r"/api/items/(\d+)/image", path)
        if method == "GET" and mi:
            p = self.app.item_image(int(mi.group(1)))
            ctype = mimetypes.guess_type(p.name)[0] or "image/jpeg"
            return self._send(200, p.read_bytes(), ctype, extra)
        if method == "POST" and path == "/api/identify/image":
            raw = self._body()
            name = urllib.parse.unquote(self.headers.get("X-Filename") or "image.jpg")
            return self._json(200, self.app.identify_image(raw, name, q.get("collection", "Screenshots")), extra)
        if method == "GET" and path == "/api/export.csv":
            data = self.app.export_csv(q.get("collection")).encode("utf-8-sig")
            return self._send(200, data, "text/csv; charset=utf-8",
                              {**extra, "Content-Disposition": 'attachment; filename="reel-shelf.csv"'})
        body = None
        if method in ("POST", "PATCH", "DELETE"):
            raw = self._body()
            try:
                body = json.loads(raw or b"{}")
            except ValueError as e:
                raise ApiError(400, "Body must be JSON") from e
            if not isinstance(body, dict):
                raise ApiError(400, "Body must be a JSON object")
        for meth, rx, fn in ROUTES:
            m = rx.match(path)
            if m and meth == method:
                return self._json(200, fn(self.app, m, q, body), extra)
        raise ApiError(404, "Unknown API path")

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")


def make_server(app: App, host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app, "token": token})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def print_qr(url: str) -> None:
    try:
        import segno
        segno.make(url, error="m").terminal(compact=True)
    except Exception:  # noqa: BLE001  QR is a convenience; the address is printed anyway
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reel-watcher app", description="Run the Reel Shelf app (phone UI + background engine).")
    ap.add_argument("--data", help="where the library lives (default ~/ReelShelf, env REEL_SHELF_DATA)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("REEL_SHELF_PORT", "8765")))
    ap.add_argument("--lan", action="store_true", help="let your phone connect over Wi-Fi (protected by an access code)")
    ap.add_argument("--no-engine", action="store_true", help="only show results, do not process anything")
    ap.add_argument("--no-ai", action="store_true", help="do not load the AI vision model (OCR, lookups and scene search still run)")
    ap.add_argument("--model-size", choices=["phone", "small", "large"])
    ap.add_argument("--model", help="exact Ollama vision model tag")
    ap.add_argument("--open", action="store_true", help="open the app in your browser")
    ap.add_argument("--demo", action="store_true", help="try the app with sample data (kept in ~/ReelShelf-demo)")
    a = ap.parse_args(argv)
    from . import model as _model
    _model.configure(a.model_size, a.model)
    if a.demo:
        from . import demo
        lib = demo.build(a.data or Path.home() / "ReelShelf-demo")
    else:
        lib = Library(a.data)
    engine = None
    if not a.no_engine:
        engine = worker.Engine(lib, vision_factory=None if a.no_ai else _model.Vision)
    app = App(lib, engine)
    app.recheck_after_upgrade()
    if engine:
        engine.online = bool(app.settings()["online"])
        engine.region = app.settings()["region"]
        engine.ai = bool(app.settings()["ai"])
        engine.start()
    def restart():
        def later():
            time.sleep(1.0)  # let the answer reach the phone first
            if engine:
                engine.stop(3)
            os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])  # half-done items are re-queued on start
        threading.Thread(target=later, daemon=True).start()
    app.restart = restart
    threading.Thread(target=app.auto_update_loop, daemon=True, name="auto-update").start()
    token = secrets.token_urlsafe(12) if a.lan else None
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    srv = make_server(app, host, a.port, token)
    local = f"http://localhost:{a.port}/"
    print(f"Reel Shelf is running: {local}")
    if a.lan:
        url = f"http://{lan_ip()}:{a.port}/?t={token}"
        print(f"On your phone (same Wi-Fi), open:\n  {url}")
        print_qr(url)
    print("Leave this window open. Press Ctrl+C to stop.")
    if a.open:
        webbrowser.open(local if not a.lan else f"{local}?t={token}")
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        if engine:
            engine.stop(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
