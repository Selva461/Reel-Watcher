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

from . import gif, identify, lookups, scanner
from .library import Library

BLOCK_RE = re.compile(r"login|rate.?limit|429|401|checkpoint|not available", re.I)
QUOTE_STYLE_DEFAULT = "bold"


def tomorrow_ts() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 5, 0, 0, 0, -1))


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
            self.current[name] = item["source"]
            try:
                fn(item)
            except Exception as e:  # noqa: BLE001  one bad item never stops the job
                self.lib.update_item(item["id"], status="failed", error=f"{type(e).__name__}: {e}"[:300], stage="")
                traceback.print_exc()

    def _watch_loop(self) -> None:
        while not self.stop_ev.wait(self.watch_every):
            self.rescan_watched()

    def rescan_watched(self) -> None:
        for j in self.lib.q("SELECT * FROM jobs WHERE kind='folder' AND state='running'"):
            p = j["params"]
            if p.get("watch"):
                scanner.scan_folders(self.lib, p.get("folders") or [], j["id"], p.get("collection") or "Screenshots", p.get("skip_dupes", True))

    # ------------------------------------------------------------ shared helpers

    def save_title(self, hit: dict) -> int:
        return self.lib.upsert_title(hit["ext_key"], hit["name"], type=hit.get("type") or "other", year=hit.get("year"),
                                     language=hit.get("language") or "", genres=hit.get("genres") or [],
                                     cover=hit.get("cover") or "", extra=hit.get("extra") or {})

    def unverified_title(self, name: str, kind: str) -> int:
        t = kind if kind in ("movie", "series", "anime", "manga", "book", "game") else "other"
        return self.lib.upsert_title("name:" + lookups.norm(name), name, type=t)

    def resolve(self, name: str, kind_hint: str) -> dict | None:
        if not self.online:
            return None
        try:
            return lookups.resolve_name(name, kind_hint)
        except (lookups.ServiceError, OSError):
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
        lib, iid = self.lib, item["id"]
        path = Path(item["source"])
        if not path.exists():
            lib.update_item(iid, status="skipped", error="file no longer exists")
            return
        meta = item["meta"]
        kind = item_kind(item)
        if "ocr" not in meta:
            from .study import ocr_image
            lib.update_item(iid, stage="reading text")
            meta["ocr"] = ocr_image(path)
            meta["thumb"] = self.thumb(path, iid, "img")
            lib.update_item(iid, meta=meta)
        text = meta["ocr"]
        if "text_checked" not in meta:
            if identify.looks_like_other(text):
                lib.update_item(iid, status="other", stage="")
                return
            lib.update_item(iid, stage="checking names")
            try:
                found = identify.resolve_candidates(identify.extract_candidates([("text", text)]), kind,
                                                    resolver=self._resolver()) if self.online else []
            except lookups.QuotaExceeded:
                found = []
            meta["text_checked"] = True
            lib.update_item(iid, meta=meta)
            if found:
                for t in found[:3]:
                    lib.add_find(iid, "title", title_id=self.save_title(t), name_raw=t["raw"], source="text", evidence=t["evidence"],
                                 confidence="confirmed", score=t.get("score", 1.0))
                lib.update_item(iid, status="done", stage="")
                return
        if "ai" not in meta:  # the guess is shown right away; scene search may replace it later
            lib.update_item(iid, stage="AI looking at the picture")
            v = self.vision()
            with self.heavy:
                is_media, guesses = identify.ai_image_guesses(v, str(path), text)
            meta["ai"] = {"is_media": is_media, "guesses": guesses, "ran": v is not None}
            lib.update_item(iid, meta=meta)
            if v is not None and not is_media and not identify.extract_candidates([("text", text)]):
                lib.update_item(iid, status="other", stage="")
                return
            self.add_ai_guesses(iid, guesses, kind)
        guesses = meta["ai"].get("guesses") or []
        if not self.online:
            lib.update_item(iid, status="check" if guesses else "skipped", stage="", error="" if guesses else "no name found")
            return
        # scene search: anime (trace.moe) then manga (SauceNAO); skipped when the AI is sure it is a live-action movie/series
        live_action = guesses and all(g.get("type") in ("movie", "series") for g in guesses)
        services = [] if live_action or kind in ("movie", "series", "book", "game") else \
            (["sauce", "trace"] if kind == "manga" else ["trace", "sauce"])
        scene = meta.setdefault("scene", {})
        data = None
        for svc in services:
            if svc in scene:
                continue
            if not lib.quota_take(svc, lookups.DAILY_LIMITS[svc]):
                lib.update_item(iid, status="waiting_quota", next_try_at=tomorrow_ts(), stage="", meta=meta)
                return
            if data is None:
                data = self._scene_bytes(path)
            lib.update_item(iid, stage="searching anime scenes" if svc == "trace" else "searching manga panels")
            try:
                res = lookups.trace_moe(data) if svc == "trace" else lookups.saucenao(data)
            except lookups.QuotaExceeded:
                lib.quota_exhaust(svc)
                lib.update_item(iid, status="waiting_quota", next_try_at=tomorrow_ts(), stage="", meta=meta)
                return
            except (lookups.ServiceError, OSError) as e:
                res = None
                scene[svc + "_error"] = str(e)[:120]
            scene[svc] = res or {}
            lib.update_item(iid, meta=meta)
            if self._accept_scene(iid, svc, res):
                lib.update_item(iid, status="done", stage="")
                return
        lib.update_item(iid, status="check" if guesses else "skipped", stage="", error="" if guesses else "no name found")

    def _resolver(self):
        return lambda name, hint: self.resolve(name, hint)

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

    def _accept_scene(self, iid: int, svc: str, res: dict | None) -> bool:
        if not res:
            return False
        if svc == "trace" and res.get("score", 0) >= 0.87 and res.get("anilist_id"):
            hit = None
            if self.online:
                try:
                    hits = lookups.anilist(id_=int(res["anilist_id"]))
                    hit = hits[0] if hits else None
                except (lookups.ServiceError, OSError, ValueError):
                    hit = None
            hit = hit or {"ext_key": res["ext_key"], "name": res["name"] or "Unknown anime", "type": "anime"}
            at = res.get("at_s") or 0
            detail = " · ".join(x for x in (f"Episode {res['episode']}" if res.get("episode") else "",
                                             f"at {int(at // 60)}:{int(at % 60):02d}" if at else "") if x)
            self._replace_ai(iid, hit, "scene", detail, f"trace.moe {round(res['score'] * 100)}% match", res["score"])
            return True
        if svc == "sauce" and res.get("score", 0) >= 0.75:
            hit = self.resolve(res["name"], "manga") or {"ext_key": "name:" + lookups.norm(res["name"]), "name": res["name"], "type": "manga"}
            detail = f"Chapter {res['part']}" if res.get("part") else ""
            self._replace_ai(iid, hit, "scene", detail, f"SauceNAO {round(res['score'] * 100)}% match", res["score"])
            return True
        return False

    def _replace_ai(self, iid, hit, source, detail, evidence, score):
        self.lib.x("DELETE FROM finds WHERE item_id=? AND source='ai'", (iid,))
        self.lib.add_find(iid, "title", title_id=self.save_title(hit), name_raw=hit["name"], source=source, evidence=evidence,
                          confidence="matched", score=score, detail=detail)

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
        if unit.get("error"):
            if BLOCK_RE.search(unit["error"]):  # Instagram is limiting anonymous downloads: try again in an hour
                lib.update_item(iid, status="waiting_quota", next_try_at=time.time() + 3600, error=unit["error"][:300], stage="")
            else:
                lib.update_item(iid, status="skipped" if "no_video" in unit["error"] else "failed", error=unit["error"][:300], stage="")
            return
        work, video, meta = unit["work"], unit["media"][0], unit["meta"]
        try:
            lib.update_item(iid, stage="watching and listening")
            v = self.vision()
            if v is None:
                raise RuntimeError("the AI model is not available, so reels cannot be read yet")
            with self.heavy:
                rec, key = study.analyze_video(v, video, work, item["collections"], meta)
            words = (rec.get("transcript") or {}).get("words") or []
            m = {"caption": meta.get("caption") or "", "author": meta.get("author"), "post_date": meta.get("post_date"),
                 "reel_language": (rec.get("transcript") or {}).get("language"), "duration": (rec.get("facts") or {}).get("duration_s"),
                 "transcript": ((rec.get("transcript") or {}).get("text") or "")[:3000]}
            if key is not None:
                m["thumb"] = self.thumb(Path(key), iid, "reel")
            lib.merge_meta(iid, **m)
            lib.clear_finds(iid)
            if kind == "quote":
                status = self._reel_quote(iid, video, rec, words)
            else:
                status = self._reel_titles(iid, rec, meta, unit.get("comments") or [], kind)
            lib.update_item(iid, status=status, stage="", error="" if status != "skipped" else "no name found")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _reel_titles(self, iid, rec, meta, comments, kind) -> str:
        screen = [f.get("visual", {}).get("on_screen_text") or "" for f in rec.get("frames") or []]
        sources = [("speech", (rec.get("transcript") or {}).get("text") or ""), ("caption", meta.get("caption") or "")]
        sources += [("text", t) for t in dict.fromkeys(screen) if t]
        sources += identify.comment_sources(comments, meta.get("author"))
        cands = identify.extract_candidates(sources)
        try:
            found = identify.resolve_candidates(cands, kind, resolver=self._resolver()) if self.online else []
        except lookups.QuotaExceeded:
            found = []
        keys = {t["ext_key"] for t in found}
        for t in found:
            self.lib.add_find(iid, "title", title_id=self.save_title(t), name_raw=t["raw"], source=t["source"], evidence=t["evidence"],
                              confidence="confirmed", score=t.get("score", 1.0))
        analysis = rec.get("analysis") if isinstance(rec.get("analysis"), dict) else {}
        ai = [t for t in analysis.get("titles") or [] if isinstance(t, dict) and str(t.get("name") or "").strip()]
        ai = [t for t in ai if lookups.norm(str(t["name"])) not in {lookups.norm(f["raw"]) for f in found}]
        n_ai = self.add_ai_guesses(iid, ai[:5], kind, skip_keys=keys)
        if found:
            return "done"
        return "check" if n_ai else "skipped"

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
