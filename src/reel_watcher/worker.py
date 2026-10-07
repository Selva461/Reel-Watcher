"""Background engine: reads reels and scans screenshots at the same time, resumable at any point.

Threads:
  - image workers (2 by default): OCR, name clues, database check, AI guess, scene search
  - reel worker (1): download (yt-dlp + comments), frames, OCR, speech, AI verdict, names or motivation clip
  - watcher: rescans watched folders every few minutes
The vision model and whisper are heavy, so they run one at a time (`heavy` lock) and the two job kinds take turns.
Downloads, OCR and online lookups run in parallel. All progress lives in the Library, so closing the app or
restarting the phone loses nothing: on start, half-done items go back to the queue.
"""
from __future__ import annotations

import re
import shutil
import threading
import time
import traceback
from pathlib import Path

from . import details, evidence, gif, identify, lookups, scanner
from .debuglog import log_error, log_event
from .library import Library

BLOCK_RE = re.compile(r"login|rate.?limit|429|401|checkpoint|not available", re.I)
QUOTE_STYLE_DEFAULT = "bold"


def tomorrow_ts() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 5, 0, 0, 0, -1))


def next_month_ts() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon + 1, 1, 0, 30, 0, 0, 0, -1))


def days_left_in_month() -> int:
    t = time.localtime()
    first_next = time.localtime(next_month_ts())
    return max(1, int((time.mktime((first_next.tm_year, first_next.tm_mon, 1, 0, 0, 0, 0, 0, -1)) - time.mktime(t)) // 86400) + 1)


RETRY_SOON = 120  # seconds to wait after a service asks us to slow down
MAX_ATTEMPTS = 4  # an item that crashed the app this many times is stopped with its reason
STALE_AFTER = 45 * 60  # a 'working' item nobody touched for this long is queued again
MAX_INSTAGRAM_WAITS = 6  # a reel Instagram refused this many times (about 6 hours) ends as failed


TITLE_KINDS = ("movie", "series", "anime", "manga", "book", "game")


def readable_download_error(err: str) -> str:
    """yt-dlp's messages, in plain words, with the original kept at the end for the debug report."""
    low = err.lower()
    if "private" in low or "login" in low or "log in" in low:
        msg = "This post is private or needs a login, so it cannot be read without logging in."
    elif re.search(r"not available|isn.t available|unavailable|\b404\b|does not exist|doesn.t exist|removed|deleted", low):
        msg = "This post is no longer available on Instagram."
    elif "no_media" in low or "no video" in low:
        msg = "This post has no video and its pictures could not be downloaded."
    else:
        msg = "The post could not be downloaded."
    return f"{msg} Tap Try again later. ({err[:160]})"


def scene_detail(svc: str, res: dict) -> str:
    """'Episode 3 · at 8:41' (anime) or 'Chapter 210' (manga) from a picture-search result."""
    if svc == "trace":
        at = res.get("at_s") or 0
        return " · ".join(x for x in (f"Episode {res['episode']}" if res.get("episode") else "",
                                      f"at {int(at // 60)}:{int(at % 60):02d}" if at else "") if x)
    part = res.get("part") or ""
    return (f"Chapter {part}" if (res.get("kind") or "manga") == "manga" else f"Episode {part}") if part else ""


def item_kind(item: dict) -> str:
    kinds = [identify.collection_kind(c) for c in item.get("collections") or []]
    return next((k for k in kinds if k != "generic"), "generic")


class Engine:
    def __init__(self, lib: Library, vision_factory=None, image_workers: int = 2, reel_workers: int = 1,
                 online: bool = True, idle_wait: float = 1.5, watch_every: float = 300):
        self.lib = lib
        self.vision_factory = vision_factory
        self.image_workers, self.reel_workers = image_workers, reel_workers
        self.online = online
        self.idle_wait, self.watch_every = idle_wait, watch_every
        self.heavy = threading.Lock()
        self.stop_ev = threading.Event()
        self.threads: list[threading.Thread] = []
        self._vision = None
        self._vision_tried = False
        self._vision_lock = threading.Lock()
        self.warnings: list[str] = []
        self.current: dict[str, str] = {}
        self.ai = False  # AI picture guesses: off unless the user turns them on (Settings); never counted as proof
        self.region = "IN"  # country for "where to watch" (TMDB, optional)
        self._trace_cap: tuple[str, int] | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self.lib.reset_stuck()
        self.stop_ev.clear()
        for n in range(self.image_workers):
            self._spawn(f"image-{n}", self._loop, "image", self.process_image)
        for n in range(self.reel_workers):
            self._spawn(f"reel-{n}", self._loop, "reel", self.process_reel)
        self._spawn("watcher", self._watch_loop)

    def _spawn(self, name, fn, *args):
        th = threading.Thread(target=fn, args=args, name=name, daemon=True)
        th.start()
        self.threads.append(th)

    def stop(self, timeout: float = 10) -> None:
        self.stop_ev.set()
        for th in self.threads:
            th.join(timeout)
        self.threads = []

    def run_until_idle(self, timeout: float = 60) -> None:
        """Tests and the CLI: process everything that is ready, then return."""
        end = time.time() + timeout
        while time.time() < end:
            busy = self.lib.one("SELECT COUNT(*) n FROM items i LEFT JOIN jobs j ON j.id=i.job_id WHERE (i.status='working' OR "
                                "((i.status='waiting' OR (i.status='waiting_quota' AND i.next_try_at<=?)) AND (j.id IS NULL OR j.state='running')))",
                                (time.time(),))["n"]
            if not busy:
                return
            time.sleep(0.05)
        raise TimeoutError("engine still busy")

    def vision(self):
        with self._vision_lock:
            if not self._vision_tried:
                self._vision_tried = True
                if self.vision_factory:
                    try:
                        self._vision = self.vision_factory()
                    except Exception as e:  # noqa: BLE001  e.g. Ollama not installed: keep going without AI
                        self.warnings.append(f"AI model unavailable: {e}"[:300])
            return self._vision

    def _loop(self, kind: str, fn) -> None:
        name = threading.current_thread().name
        while not self.stop_ev.is_set():
            item = self.lib.claim_next(kind)
            if item is None:
                self.current.pop(name, None)
                self.stop_ev.wait(self.idle_wait)
                continue
            iid = item["id"]
            if item.get("attempts", 0) > MAX_ATTEMPTS:  # it keeps crashing the app (e.g. Android killed it): stop
                self.lib.update_item(iid, status="failed", stage="", error=f"Stopped after {MAX_ATTEMPTS} tries"
                                     + (f". Last problem: {item['error']}" if item.get("error") else "") + ". Tap Try again.")
                log_event("end", item=iid, status="failed", reason="too many tries")
                continue
            self.current[name] = item["source"]
            t0 = time.time()
            log_event("start", item=iid, kind=item["kind"], attempt=item.get("attempts"))
            try:
                fn(item)
            except Exception as e:  # noqa: BLE001  one bad item never stops the job
                log_error("process", e, item=iid)
                traceback.print_exc()
                self.lib.update_item(iid, status="failed", stage="", error=f"Unexpected problem ({type(e).__name__}: {str(e)[:150]}). "
                                     "Tap Try again; if it happens again, copy the debug report.")
            finally:
                after = self.lib.one("SELECT status FROM items WHERE id=?", (iid,))
                if after and after["status"] == "working":  # a code path that forgot to set an end state
                    self.lib.update_item(iid, status="failed", stage="", error="Ended without a result. Tap Try again.")
                    log_event("end", item=iid, status="failed", reason="no end state")
                elif after and after["status"] in ("waiting_quota", "done", "check", "skipped", "other"):
                    self.lib.x("UPDATE items SET attempts=0 WHERE id=?", (iid,))  # only crash loops count as tries
                log_event("finished", item=iid, status=(after or {}).get("status"), seconds=round(time.time() - t0, 1))

    def _watch_loop(self) -> None:
        while not self.stop_ev.wait(min(self.watch_every, 60)):
            self.release_stale()
            if time.time() - getattr(self, "_last_rescan", 0) >= self.watch_every:
                self._last_rescan = time.time()
                self.rescan_watched()

    def release_stale(self, max_age: float = STALE_AFTER) -> int:
        """Watchdog: an item marked working that no worker is handling (and untouched for a long time) is queued again."""
        busy = set(self.current.values())
        n = 0
        for r in self.lib.q("SELECT id, source FROM items WHERE status='working' AND updated_at<?", (time.time() - max_age,)):
            if r["source"] not in busy:
                self.lib.update_item(r["id"], status="waiting", stage="")
                log_event("watchdog", item=r["id"], action="requeued")
                n += 1
        return n

    def rescan_watched(self) -> None:
        for j in self.lib.q("SELECT * FROM jobs WHERE kind='folder' AND state='running'"):
            p = j["params"]
            if p.get("watch"):
                scanner.scan_folders(self.lib, p.get("folders") or [], j["id"], p.get("collection") or "Screenshots", p.get("skip_dupes", True))

    # ------------------------------------------------------------ shared helpers

    def save_title(self, hit: dict) -> int:
        tid = self.lib.upsert_title(hit["ext_key"], hit["name"], type=hit.get("type") or "other", year=hit.get("year"),
                                    language=hit.get("language") or "", genres=hit.get("genres") or [],
                                    cover=hit.get("cover") or "", extra=hit.get("extra") or {})
        self.ensure_details(tid)
        return tid

    def ensure_details(self, tid: int, force: bool = False) -> dict:
        """Fetch full details once per title (synopsis, status, studio/director, where to watch, related works)."""
        t = self.lib.one("SELECT * FROM titles WHERE id=?", (tid,))
        if not t or not self.online or t["ext_key"].startswith("name:"):
            return {}
        if t["extra"].get("checked_at") and not force:
            return t["extra"]
        d = details.enrich(t, self.region)
        self.lib.merge_title_extra(tid, d, details.cover_from(d))
        return d

    def _service_allowed(self, svc: str) -> tuple[bool, float]:
        """trace.moe gives 100 free searches a MONTH: spread what is left over the remaining days.
        SauceNAO has a daily allowance. Returns (allowed now, when to retry if not)."""
        if svc == "trace":
            day = time.strftime("%Y-%m-%d")
            if lookups.DAILY_LIMITS.get("trace"):
                cap = lookups.DAILY_LIMITS["trace"]
            else:
                if not self._trace_cap or self._trace_cap[0] != day:
                    try:
                        left = lookups.trace_me()["left"]
                    except (lookups.ServiceError, lookups.RateLimited, KeyError, ValueError):
                        left = 3 * days_left_in_month()
                    self._trace_cap = (day, -1 if left <= 0 else max(1, left // days_left_in_month()))
                cap = self._trace_cap[1]
                if cap < 0:
                    return False, next_month_ts()
            return self.lib.quota_take("trace", cap), tomorrow_ts()
        return self.lib.quota_take(svc, lookups.DAILY_LIMITS[svc]), tomorrow_ts()

    def unverified_title(self, name: str, kind: str) -> int:
        t = kind if kind in ("movie", "series", "anime", "manga", "book", "game") else "other"
        return self.lib.upsert_title("name:" + lookups.norm(name), name, type=t)

    def resolve(self, name: str, kind_hint: str, **kw) -> dict | None:
        if not self.online:
            return None
        try:
            return lookups.resolve_name(name, kind_hint, **kw)
        except (lookups.ServiceError, lookups.RateLimited, OSError):
            return None

    def thumb(self, src: Path, item_id: int, prefix: str) -> str:
        from PIL import Image
        dest = self.lib.dir / "media" / f"{prefix}_{item_id}.jpg"
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((360, 640))
                im.save(dest, "JPEG", quality=80)
            return dest.name
        except Exception:  # noqa: BLE001
            return ""

    def add_ai_guesses(self, item_id: int, guesses: list[dict], kind: str, skip_keys: set | None = None) -> int:
        """Store the AI's guesses as 'check' finds (normalised through the databases when possible)."""
        n = 0
        for g in guesses:
            name = str(g.get("name")).strip()
            gkind = g.get("type") if g.get("type") in ("movie", "series", "anime", "manga", "book", "game") else kind
            hit = self.resolve(name, gkind if gkind != "generic" else "")
            if hit and skip_keys and hit["ext_key"] in skip_keys:
                continue
            tid = self.save_title(hit) if hit else self.unverified_title(name, gkind)
            self.lib.add_find(item_id, "title", title_id=tid, name_raw=name, source="ai", evidence=str(g.get("why") or g.get("evidence") or "")[:200],
                              confidence="check", score=0.3)
            n += 1
        return n

    # ------------------------------------------------------------ screenshots

    def process_image(self, item: dict) -> None:
        """Screenshot: read the text, check names in the databases, search the web, then match the picture
        (anime scenes, manga panels, movie frames). Each step runs on its own, records what happened in meta["steps"]
        and keeps its results in meta, so a pause for a free-service limit resumes where it stopped. The answer is
        decided by evidence.verdict: VERIFIED only when two independent sources agree, else POSSIBLE, else NOT FOUND.
        The AI model is only asked when the user turned "AI guesses" on, and its guesses never count as proof."""
        lib, iid = self.lib, item["id"]
        path = Path(item["source"])
        if not path.exists():
            lib.update_item(iid, status="failed", stage="", error="The picture file is gone (moved or deleted)")
            return
        meta = item["meta"]
        kind = item_kind(item)
        steps = meta.setdefault("steps", {})

        def note(step: str, ok, detail: str) -> None:
            steps[step] = {"ok": ok, "detail": str(detail)[:300]}
            lib.update_item(iid, meta=meta)
            log_event("step", item=iid, step=step, ok=ok, detail=str(detail)[:200])

        if "ocr" not in meta:
            from .study import ocr_image
            lib.update_item(iid, stage="reading text")
            try:
                meta["ocr"] = ocr_image(path)
                n = len(meta["ocr"].split())
                note("Read text", bool(n), f"{n} words" if n else "no text in the picture")
            except Exception as e:  # noqa: BLE001
                meta["ocr"] = ""
                note("Read text", False, f"text reader failed: {e}")
            meta["thumb"] = self.thumb(path, iid, "img")
            lib.update_item(iid, meta=meta)
        text = meta["ocr"]
        cands = identify.extract_candidates([("text", text)])
        if identify.looks_like_other(text) and not identify.page_clues(text):
            note("Read text", True, "looks like a chat, receipt or payment screen")
            self._end_image(iid, meta, end="other")
            return

        # names written on the screen, checked in the databases
        if "db" not in meta:
            lib.update_item(iid, stage="checking names")
            found = []
            if not self.online:
                note("Check names", None, "online lookups are off (Settings)")
            elif not cands:
                note("Check names", None, "no title-like text")
            else:
                try:
                    found = identify.resolve_candidates(cands, kind, resolver=self._resolver(), language=cands[0].get("language"))
                    note("Check names", True if found else None,
                         "; ".join(f"{t['name']}: {t['reason']}" for t in found[:3]) if found else
                         "not in the databases: " + ", ".join(c["name"] for c in cands[:3]))
                except Exception as e:  # noqa: BLE001
                    note("Check names", False, f"lookup failed: {e}")
            meta["db"] = [{k: v for k, v in t.items() if k != "extra"} for t in found]
            lib.update_item(iid, meta=meta)
        if self._verified(iid, meta, text):
            return

        # the web: which work is this name (new and regional titles the databases do not have yet)
        if "web" not in meta and self.online:
            lib.update_item(iid, stage="searching the web")
            done = {lookups.norm(t["raw"]) for t in meta["db"] if t["confidence"] == "confirmed"}
            clues = [c for c in cands if c["key"] not in done and c["score"] >= 1.0][:2]
            runs = []
            for c in clues or [None]:
                query = identify.search_query(text, [c] if c else [], kind)
                if not query:
                    continue
                try:
                    work, notes = lookups.web_identify(query, name_hint=c["name"] if c else "",
                                                       kind_hint=(c or {}).get("type") or (kind if kind in TITLE_KINDS else ""),
                                                       year=(c or {}).get("year"))
                except Exception as e:  # noqa: BLE001
                    work, notes = None, [f"web search failed: {e}"]
                runs.append({"clue": c["name"] if c else "", "where": c["sources"] if c else [], "year": (c or {}).get("year"),
                             "language": (c or {}).get("language"), "query": query, "work": work, "notes": notes[-4:]})
            meta["web"] = runs
            hits = [r for r in runs if r["work"]]
            errored = runs and not hits and all(any("failed" in n or "Error" in n or "HTTP" in n or ": <" in n for n in r["notes"]) for r in runs)
            note("Web search", True if hits else False if errored else None,
                 "; ".join(f"{r['work']['evidence']} ({r['work']['site']})" for r in hits) if hits else
                 ("; ".join(n for r in runs for n in r["notes"][-2:])[:300] or "nothing found") if runs else "not enough text to search with")
            if self._verified(iid, meta, text):
                return

        # the picture itself: free scene searches (not AI)
        if self.online:
            web_kinds = {(r.get("work") or {}).get("type") for r in meta.get("web") or []}
            # trace.moe only knows anime and gives 100 free searches a month: it is kept for anime pictures.
            # SauceNAO covers anime, manga, movies and shows, so it goes first when the kind is unknown.
            if kind in ("book", "game"):
                services = []
            elif kind in ("movie", "series", "manga") or web_kinds & {"movie", "series"}:
                services = ["sauce"]
            elif kind == "anime":
                services = ["trace", "sauce"]
            else:
                services = ["sauce", "trace"]
            scene = meta.setdefault("scene", {})
            data = None
            for svc in services:
                if svc in scene:
                    continue
                if svc == "trace" and kind != "anime" and (scene.get("sauce") or {}).get("kind") not in (None, "anime"):
                    continue  # SauceNAO already says it is a movie, show or manga
                allowed, retry_at = self._service_allowed(svc)
                label = "Anime scene search" if svc == "trace" else "Manga and movie scene search"
                if not allowed:
                    note(label, None, "free limit reached; continues automatically " + time.strftime("%d %b %H:%M", time.localtime(retry_at)))
                    self._end_image(iid, meta, text, waiting_until=retry_at)
                    return
                if data is None:
                    data = self._scene_bytes(path)
                lib.update_item(iid, stage="searching anime scenes" if svc == "trace" else "searching manga panels")
                try:
                    res = lookups.trace_moe(data) if svc == "trace" else lookups.saucenao(data)
                except lookups.QuotaExceeded:
                    lib.quota_exhaust(svc)
                    when = next_month_ts() if svc == "trace" else tomorrow_ts()
                    note(label, None, "free limit used up; continues automatically " + time.strftime("%d %b", time.localtime(when)))
                    self._end_image(iid, meta, text, waiting_until=when)
                    return
                except lookups.RateLimited:  # busy or too fast: a short pause, the search was not used up
                    self._end_image(iid, meta, text, waiting_until=time.time() + RETRY_SOON)
                    return
                except (lookups.ServiceError, OSError) as e:
                    res = None
                    scene[svc + "_error"] = str(e)[:120]
                scene[svc] = res or {}
                if scene.get(svc + "_error"):
                    note(label, False, scene[svc + "_error"])
                else:
                    note(label, True if res and res.get("name") else None, f"{res['name']} ({round(res.get('score', 0) * 100)}%)" if res and res.get("name") else "no match")
                if self._verified(iid, meta, text):
                    return

        if "ai" not in meta:
            if not self.ai:
                meta["ai"] = {"guesses": [], "ran": False}
            else:
                lib.update_item(iid, stage="AI looking at the picture")
                guesses, v = [], None
                try:
                    v = self.vision()
                    if v is None:
                        note("AI guesses", None, "AI model not available on this device" + (f" ({self.warnings[-1]})" if self.warnings else ""))
                    else:
                        with self.heavy:
                            is_media, guesses = identify.ai_image_guesses(v, str(path), text)
                        meta["ai_is_media"] = is_media
                        note("AI guesses", bool(guesses), ", ".join(g["name"] for g in guesses) + " (guesses, not proof)" if guesses else "no guess")
                except Exception as e:  # noqa: BLE001  e.g. the model ran out of memory: the other steps still count
                    note("AI guesses", False, f"AI model failed: {e}")
                meta["ai"] = {"guesses": guesses, "ran": v is not None, "is_media": meta.pop("ai_is_media", None)}
        self._end_image(iid, meta, text)

    # ------------------------------------------------------------ deciding the answer from the evidence

    def _collect(self, meta: dict, text: str) -> dict:
        """Every piece of evidence gathered so far, grouped per work (database id)."""
        works: dict[str, dict] = {}

        def add(hit: dict, raw: str, proof: list[dict], tid: int | None = None):
            w = works.setdefault(hit["ext_key"], {"hit": hit, "raw": raw, "proof": [], "tid": tid})
            for p in proof:
                if p not in w["proof"]:
                    w["proof"].append(p)
            w["tid"] = w["tid"] or tid
        cands = identify.extract_candidates([("text", text)])

        def on_screen(name: str) -> list[dict]:
            c = next((c for c in cands if evidence.exact(c["name"], name)), None)
            return [evidence.named(w, c["evidence"]) for w in c["sources"]] if c else []
        for t in meta.get("db") or []:
            add(t, t["raw"], t.get("proof") or [])
        for r in meta.get("web") or []:
            work = r.get("work")
            if not work:
                continue
            tid = r.get("tid")
            if not tid:
                tid = r["tid"] = self.save_web_work(work, r.get("language"))
            t = self.lib.one("SELECT ext_key, name, type, year FROM titles WHERE id=?", (tid,))
            if not t:
                continue
            proof = ([evidence.named(w, r["clue"]) for w in r["where"]] if r["clue"] and evidence.exact(r["clue"], work["name"]) else [])
            add(dict(t), r["clue"] or work["name"], proof + evidence.web(work, r["clue"], r.get("year")), tid)
        for svc, label in (("trace", "trace.moe"), ("sauce", "SauceNAO")):
            res = (meta.get("scene") or {}).get(svc)
            if not res or not res.get("name"):
                continue
            hit = self._scene_hit(svc, res)
            if hit:
                add(hit, res["name"], [evidence.picture(label, res)] + on_screen(hit["name"]))
                works[hit["ext_key"]].setdefault("detail", scene_detail(svc, res))
        for g in (meta.get("ai") or {}).get("guesses") or []:
            name = str(g.get("name") or "").strip()
            if name:
                gkind = g.get("type") if g.get("type") in TITLE_KINDS else ""
                hit = self.resolve(name, gkind) or {"ext_key": "name:" + lookups.norm(name), "name": name, "type": gkind or "other"}
                add(hit, name, [evidence.ai(name, str(g.get("why") or ""))])
        return works

    def _verified(self, iid: int, meta: dict, text: str) -> bool:
        """Stop early once one work is verified."""
        if any(evidence.verdict(w["proof"])[0] == "confirmed" for w in self._collect(meta, text).values()):
            self._end_image(iid, meta, text)
            return True
        return False

    def _end_image(self, iid: int, meta: dict, text: str = "", end: str = "", waiting_until: float | None = None) -> None:
        """Every screenshot ends here, in exactly one final state with its reason:
        done (verified), check (possible: confirm or pick), skipped (not found), other (not about a title),
        or waiting_quota (paused for a free limit, continues by itself at next_try_at)."""
        lib = self.lib
        works = {} if end == "other" else self._collect(meta, text)
        lib.x("DELETE FROM finds WHERE item_id=? AND source!='user'", (iid,))
        verified = possible = 0
        proof_log = {}
        for key, w in sorted(works.items(), key=lambda kv: -len([p for p in kv[1]["proof"] if p.get("counts")])):
            conf, reason = evidence.verdict(w["proof"])
            tid = w["tid"] or (self.save_title(w["hit"]) if not w["hit"]["ext_key"].startswith("name:") else
                               self.unverified_title(w["hit"]["name"], w["hit"].get("type") or ""))
            kinds = {p["kind"] for p in w["proof"]}
            source = "user" if "user" in kinds else "web" if "web" in kinds and "database" not in kinds else \
                "scene" if "picture" in kinds and not kinds & {"database", "web"} else "ai" if kinds == {"ai"} else "text"
            lib.add_find(iid, "title", title_id=tid, name_raw=w["raw"], source=source, evidence=f"{reason} | {evidence.summary(w['proof'])}",
                         confidence=conf, detail=w.get("detail") or "", score=len([p for p in w["proof"] if p.get("counts")]) / 4,
                         alts=w["hit"].get("alternatives") or [])
            verified += conf == "confirmed"
            possible += conf != "confirmed"
            proof_log[w["hit"]["name"]] = {"verdict": conf, "reason": reason, "proof": w["proof"]}
        meta["proof"] = proof_log
        if waiting_until:
            status, error = "waiting_quota", ""
            lib.update_item(iid, next_try_at=waiting_until)
        elif end == "other" or (not works and (meta.get("ai") or {}).get("is_media") is False):
            status, error = "other", ""
        elif verified:
            status, error = "done", ""
        elif possible:
            status, error = "check", ""
        else:
            status = "skipped"
            tried = [k for k, v in (meta.get("steps") or {}).items() if v.get("ok") is False]
            error = "Not found" + (f" ({', '.join(tried)} failed)" if tried else "") + ". Try Google Lens, or type the name."
        lib.update_item(iid, status=status, stage="", error=error, meta=meta)
        log_event("end", item=iid, status=status, verified=verified, possible=possible)

    def save_web_work(self, work: dict, language: str | None = None) -> int:
        """A work found by web search: use the database entry when one matches, else keep what the web said."""
        hit = self.resolve(work["name"], work.get("type") or "", **({"year": work["year"]} if work.get("year") else {}),
                           **({"language": language} if language else {}))
        if hit and lookups.similarity(hit["name"], work["name"]) >= 0.9 and \
                (not work.get("year") or not hit.get("year") or abs(hit["year"] - work["year"]) <= 1):
            return self.save_title(hit)
        extra = {k: v for k, v in {"url": work.get("url"), "wikipedia_title": work.get("wikipedia_title"),
                                   "found_on": work.get("site")}.items() if v}
        tid = self.lib.upsert_title(f"web:{lookups.norm(work['name'])}:{work.get('year') or ''}", work["name"],
                                    type=work.get("type") if work.get("type") in TITLE_KINDS else "other", year=work.get("year"),
                                    language=identify.LANG_NAMES.get(language or "", ""), extra=extra)
        self.ensure_details(tid)
        return tid

    def _resolver(self):
        return lambda name, hint, **kw: self.resolve(name, hint, **kw)

    @staticmethod
    def _scene_bytes(path: Path) -> bytes:
        """Scene search wants a modest JPEG: smaller uploads, fewer timeouts."""
        import io

        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((640, 640))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            return buf.getvalue()

    def _scene_hit(self, svc: str, res: dict) -> dict | None:
        """The work a picture-search result points to (database entry when available)."""
        if svc == "trace" and res.get("anilist_id"):
            hit = None
            if self.online:
                try:
                    hits = lookups.anilist(id_=int(res["anilist_id"]))
                    hit = hits[0] if hits else None
                except (lookups.ServiceError, lookups.RateLimited, OSError, ValueError):
                    hit = None
            return hit or {"ext_key": res.get("ext_key") or f"anilist:{res['anilist_id']}", "name": res.get("name") or "Unknown anime", "type": "anime"}
        if svc == "sauce" and res.get("name"):
            kind = res.get("kind") or "manga"
            return self.resolve(res["name"], kind, **({"year": res["year"]} if res.get("year") else {})) or \
                {"ext_key": "name:" + lookups.norm(res["name"]), "name": res["name"], "type": kind, "year": res.get("year")}
        return None

    # ------------------------------------------------------------ reels

    def process_reel(self, item: dict) -> None:
        from . import study
        lib, iid = self.lib, item["id"]
        code = item["key"].split(":", 1)[1]
        kind = item_kind(item)
        work_parent = lib.dir / "work"
        lib.update_item(iid, stage="downloading")
        unit = study.prepare_ytdlp({"url": item["source"], "code": code, "collections": item["collections"], "kind": "reel"},
                                   work_parent, comments=kind != "quote")
        steps: dict = {}

        def note(step: str, ok, detail: str) -> None:  # shown in the debug report, like for screenshots
            steps[step] = {"ok": ok, "detail": str(detail)[:300]}
            lib.merge_meta(iid, steps=steps)
            log_event("step", item=iid, step=step, ok=ok, detail=str(detail)[:200])

        if unit.get("error"):
            note("Download", False, unit["error"])
            if BLOCK_RE.search(unit["error"]):  # Instagram is limiting anonymous downloads: try again in an hour
                waits = int(item["meta"].get("ig_waits") or 0) + 1
                if waits > MAX_INSTAGRAM_WAITS:
                    lib.update_item(iid, status="failed", stage="", error=f"Instagram refused this reel {MAX_INSTAGRAM_WAITS} times. "
                                    "Open it in Instagram to check it still exists, then tap Try again.")
                    return
                lib.merge_meta(iid, ig_waits=waits)
                lib.update_item(iid, status="waiting_quota", next_try_at=time.time() + 3600, error=unit["error"][:300], stage="")
            else:
                lib.update_item(iid, status="failed", stage="", error=readable_download_error(unit["error"]))
            return
        work, meta = unit["work"], unit["meta"]
        if not unit.get("media"):  # a picture post or carousel: read the pictures like screenshots
            note("Download", True, f"{len(unit.get('images') or [])} pictures (no video)")
            try:
                self._picture_post(iid, unit, meta, kind, note)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            return
        note("Download", True, "video")
        video = unit["media"][0]
        try:
            lib.update_item(iid, stage="watching and listening")
            v = self.vision() if self.ai else None  # without AI: text on frames + speech + caption + comments
            rec = None
            if v is not None:
                try:
                    with self.heavy:
                        rec, key = study.analyze_video(v, video, work, item["collections"], meta)
                except Exception as e:  # noqa: BLE001  e.g. the model ran out of memory: read the reel without it
                    self.warnings.append(f"AI model failed on a reel: {e}"[:300])
            if rec is None:
                with self.heavy:
                    rec, key = study.analyze_video_basic(video, work)
            words = (rec.get("transcript") or {}).get("words") or []
            m = {"caption": meta.get("caption") or "", "author": meta.get("author"), "post_date": meta.get("post_date"),
                 "reel_language": (rec.get("transcript") or {}).get("language"), "duration": (rec.get("facts") or {}).get("duration_s"),
                 "transcript": ((rec.get("transcript") or {}).get("text") or "")[:3000]}
            if key is not None:
                m["thumb"] = self.thumb(Path(key), iid, "reel")
            lib.merge_meta(iid, **m)
            lib.clear_finds(iid)
            note("Read the reel", True, f"{len((m['transcript'] or '').split())} words said; "
                 f"{sum(len(((f.get('visual') or {}).get('on_screen_text') or '').split()) for f in rec.get('frames') or [])} words on screen")
            if kind == "quote":
                status = self._reel_quote(iid, video, rec, words)
            else:
                status = self._reel_titles(iid, rec, meta, unit.get("comments") or [], kind)
                note("Check names", status != "skipped" or None, {"done": "verified", "check": "possible match", "skipped": "nothing found"}[status])
            lib.update_item(iid, status=status, stage="", error="" if status != "skipped" else "Not found. Type the name, or try again later.")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _picture_post(self, iid: int, unit: dict, meta: dict, kind: str, note) -> None:
        """Instagram post made of pictures (one or a carousel): the text on each picture, the caption and the
        comments are read and checked with the same rule as reels."""
        from . import study
        lib = self.lib
        lib.update_item(iid, stage="reading the pictures")
        texts = []
        for p in unit.get("images") or []:
            try:
                texts.append(study.ocr_image(p))
            except Exception as e:  # noqa: BLE001  one unreadable picture does not stop the others
                log_error("picture text", e, item=iid)
                texts.append("")
        words = sum(len(t.split()) for t in texts)
        note("Read the pictures", bool(words) or None, f"{len(texts)} pictures, {words} words")
        m = {"caption": meta.get("caption") or "", "author": meta.get("author"), "post_date": meta.get("post_date"),
             "post_kind": "pictures", "pictures": len(texts), "picture_text": [t[:300] for t in texts]}
        if unit.get("images"):
            m["thumb"] = self.thumb(Path(unit["images"][0]), iid, "reel")
        lib.merge_meta(iid, **m)
        lib.clear_finds(iid)
        if kind == "quote":  # quote pictures: the longest line of text is the quote
            lines = [ln.strip() for t in texts for ln in t.splitlines() if len(ln.split()) >= 4]
            if not lines:
                lib.update_item(iid, status="skipped", stage="", error="No quote text found on the pictures.")
                return
            lib.add_find(iid, "quote", quote=max(lines, key=len)[:300], source="text", confidence="confirmed")
            lib.update_item(iid, status="done", stage="", error="")
            return
        rec = {"transcript": {"language": None, "text": "", "words": []}, "analysis": {},
               "frames": [{"visual": {"on_screen_text": t}} for t in texts if t]}
        status = self._reel_titles(iid, rec, meta, unit.get("comments") or [], kind)
        note("Check names", status != "skipped" or None, {"done": "verified", "check": "possible match", "skipped": "nothing found"}[status])
        lib.update_item(iid, status=status, stage="", error="" if status != "skipped" else "Not found. Type the name, or try again later.")

    def _reel_titles(self, iid, rec, meta, comments, kind) -> str:
        screen = [f.get("visual", {}).get("on_screen_text") or "" for f in rec.get("frames") or []]
        sources = [("speech", (rec.get("transcript") or {}).get("text") or ""), ("caption", meta.get("caption") or "")]
        sources += [("text", t) for t in dict.fromkeys(screen) if t]
        sources += identify.comment_sources(comments, meta.get("author"))
        cands = identify.extract_candidates(sources)
        lang = (rec.get("transcript") or {}).get("language")
        try:
            found = identify.resolve_candidates(cands, kind, resolver=self._resolver(), language=lang) if self.online else []
        except lookups.QuotaExceeded:
            found = []
        if self.online:
            # names the databases do not have (new or regional titles): search the web for the strong clues left over
            known = {lookups.norm(t["raw"]) for t in found}
            weak_ok = not any(t["confidence"] == "confirmed" for t in found)
            todo = [c for c in cands if c["key"] not in known and (c["score"] >= 2.5 or (weak_ok and c["score"] >= 1.5))][:2]
            for c in todo:
                try:
                    work, _ = lookups.web_identify(identify.search_query("", [c], kind), name_hint=c["name"],
                                                   kind_hint=c.get("type") or (kind if kind in TITLE_KINDS else ""), year=c.get("year"))
                except Exception:  # noqa: BLE001
                    work = None
                if work:
                    proof = [evidence.named(w, c["evidence"]) for w in c["sources"] if evidence.exact(c["name"], work["name"])] + \
                        evidence.web(work, c["name"], c.get("year"))
                    conf, reason = evidence.verdict(proof)
                    tid = self.save_web_work(work, c.get("language") or lang)
                    t = self.lib.one("SELECT * FROM titles WHERE id=?", (tid,))
                    if t["ext_key"] not in {f["ext_key"] for f in found}:
                        found.append({"ext_key": t["ext_key"], "name": t["name"], "raw": c["name"], "source": "web",
                                      "evidence": f"{reason} | {evidence.summary(proof)}"[:300], "confidence": conf, "score": 0.9,
                                      "_tid": tid})
        keys = {t["ext_key"] for t in found}
        for t in found:
            if t.get("proof") and "reason" in t:  # database finds: the reason the rule gave, plus the evidence
                t["evidence"] = f"{t['reason']} | {evidence.summary(t['proof'])}"[:300]
            self.lib.add_find(iid, "title", title_id=t.get("_tid") or self.save_title(t), name_raw=t["raw"], source=t["source"], evidence=t["evidence"],
                              confidence=t["confidence"], score=t.get("score", 1.0), alts=t.get("alternatives") or [])
        analysis = rec.get("analysis") if isinstance(rec.get("analysis"), dict) else {}
        ai = [t for t in analysis.get("titles") or [] if isinstance(t, dict) and str(t.get("name") or "").strip()]
        ai = [t for t in ai if lookups.norm(str(t["name"])) not in {lookups.norm(f["raw"]) for f in found}]
        n_ai = self.add_ai_guesses(iid, ai[:5], kind, skip_keys=keys) if self.ai else 0
        if any(t["confidence"] == "confirmed" for t in found):
            return "done"
        return "check" if (n_ai or found) else "skipped"

    def _reel_quote(self, iid, video, rec, words) -> str:
        screen = [f.get("visual", {}).get("on_screen_text") or "" for f in rec.get("frames") or []]
        q = gif.pick_quote(rec.get("analysis"), words, screen)
        if not q:
            return "skipped"
        keep = self.lib.dir / "media" / f"reel_{iid}.mp4"  # kept so the clip can be re-made in another style or format
        shutil.copy2(video, keep)
        out = self.lib.dir / "media" / f"quote_{iid}_{QUOTE_STYLE_DEFAULT}.gif"
        try:
            gif.make_clip(keep, out, q["start"], q["end"], q["words"], QUOTE_STYLE_DEFAULT, "gif")
            media_name = out.name
        except RuntimeError as e:
            self.warnings.append(str(e)[:200])
            media_name = ""
        self.lib.add_find(iid, "quote", quote=q["text"], source=q["source"], confidence="confirmed", media=media_name,
                          detail=f"{q['start']:.2f}-{q['end']:.2f}", evidence=" ".join(w["w"] for w in q["words"])[:300])
        self.lib.merge_meta(iid, quote_words=q["words"], quote_span=[q["start"], q["end"]])
        return "done"

    # ------------------------------------------------------------ re-render a clip on demand (app buttons)

    def render_quote(self, find_id: int, style: str, fmt: str) -> str:
        f = self.lib.find(find_id)
        if not f or f["kind"] != "quote":
            raise ValueError("not a quote")
        it = self.lib.item(f["item_id"])
        src = self.lib.dir / "media" / f"reel_{it['id']}.mp4"
        if not src.exists():
            raise FileNotFoundError("the reel video is no longer stored")
        s, e = it["meta"].get("quote_span") or [0, 6]
        out = self.lib.dir / "media" / f"quote_{it['id']}_{style}.{fmt}"
        if not out.exists():
            gif.make_clip(src, out, s, e, it["meta"].get("quote_words") or [], style, fmt)
        return out.name


def start_folder_job(lib: Library, folders: list[str], collection: str = "Screenshots", watch: bool = True,
                     skip_dupes: bool = True, name: str | None = None) -> tuple[int, dict]:
    job = lib.add_job(name or "Scan " + ", ".join(Path(f).name for f in folders), "folder",
                      {"folders": folders, "collection": collection, "watch": watch, "skip_dupes": skip_dupes})
    return job, scanner.scan_folders(lib, folders, job, collection, skip_dupes)
